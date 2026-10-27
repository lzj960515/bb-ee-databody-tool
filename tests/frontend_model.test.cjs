const test = require("node:test");
const assert = require("node:assert/strict");
const {
  BodyEditor,
  CustomBuildDraft,
  GuideRequestQueue,
  StrategyPickerModel,
  SingleBodyEditor,
} = require("../frontend/model.js");

const guide = (ids) => ({ strategy_ids: ids, selection: { errors: [] } });
const characters = [
  {id: 1, base_attrs: [{type: 1, value: 1300}, {type: 18, value: 100}], inherit_skills: [12, 11]},
  {id: 2, base_attrs: [{type: 1, value: 1000}, {type: 18, value: 100}], inherit_skills: [22, 23]},
  {id: 3, base_attrs: [{type: 1, value: 800}, {type: 18, value: 120}], inherit_skills: [31, 32]},
];

test("单体属性默认跟随角色，改值保留；继承技能随来源切换且不能串角色", () => {
  const single = new SingleBodyEditor(characters);
  single.selectCharacter(1);
  assert.equal(single.attributeValue('max_hp'), 1300);
  assert.equal(single.attributeValue('max_mp'), 100);
  single.attributes.max_hp = '5000';
  single.selectInheritance(0, 2);
  assert.deepEqual(single.inheritances[0], {character_id: 2, skill_id: 22});
  single.inheritances[0].skill_id = 23;
  single.selectInheritance(1, 3);
  assert.throws(() => single.selectInheritance(1, 2), /重复/);
  assert.throws(() => single.selectInheritance(1, 1), /相同/);
  single.selectCharacter(2);
  assert.equal(single.inheritances[0], null);
  assert.equal(single.inheritances[1].character_id, 3);
  assert.equal(single.attributeValue('max_hp'), 5000);
  single.attributes.max_hp = '';
  assert.equal(single.attributeValue('max_hp'), 1000);
  single.add(2226, 4); single.add(2227, 4);
  assert.deepEqual(single.requests(guide([2226, 2227]))[0].inheritances,
    [{character_id: 3, skill_id: 31}]);
  single.selectInheritance(1, null);
  assert.deepEqual(single.requests(guide([2226, 2227]))[0].inheritances, []);
});

test("单体提交冻结自选属性和传承技能，非法数值在确认前拦截", () => {
  const single = new SingleBodyEditor(characters);
  single.selectCharacter(1);
  single.add(2226, 4); single.add(2227, 4);
  single.selectInheritance(0, 2);
  single.inheritances[0].skill_id = 23;
  single.attributes.max_hp = '5000'; single.attributes.max_mp = '500';
  const request = single.requests(guide([2226, 2227]))[0];
  assert.equal(request.max_hp, 5000); assert.equal(request.max_mp, 500);
  single.inheritances[0].skill_id = 22;
  assert.equal(request.inheritances[0].skill_id, 23);
  for (const value of ['0', '-1', '1.5', 'NaN', 'Infinity', '2147483648']) {
    single.attributes.max_hp = value;
    assert.throws(() => single.requests(guide([2226, 2227])), /生命上限/);
  }
});

test("单体写入包含自动前置，品质与继承同步，自动项不永久污染目标", () => {
  const single = new SingleBodyEditor();
  single.bodies[0].character_id = 100101;
  single.setOwned(2253, 3);
  single.setOwned(2226, 4);
  single.set(0, 0, 2253, 3);
  single.set(0, 1, 2226, 4);
  single.setOwned(2253, 2);
  assert.equal(single.bodies[0].slots[0].quality, 2);
  const planned = guide([2226,2227,2248,2168,2253]);
  const request = single.requests(planned)[0];
  assert.equal(request.full_potentials, false);
  assert.deepEqual(request.owned_strategies, [
    {id:2226,quality:4}, {id:2227,quality:4}, {id:2248,quality:4},
    {id:2168,quality:4}, {id:2253,quality:2},
  ]);
  assert.deepEqual(single.owned.map(row => row.id), [2253,2226]);
  assert.deepEqual(request.strategy_ids, [2253,2226]);
  single.setOwned(2248, 3);
  assert.equal(single.requests(planned)[0].owned_strategies.find(row => row.id===2248).quality, 3);
  single.removeOwned(2253);
  assert.equal(single.locate(2253), null);
  assert.throws(() => single.requests(planned), /两项/);
  single.set(0, 0, 2248, 3);
  const updated = single.requests(guide([2226,2227,2248]))[0];
  assert.ok(!updated.owned_strategies.some(row => row.id===2168));
});

test("单体计算尚未完成、冲突或过期时不能写入未补齐的策略", () => {
  const single = new SingleBodyEditor();
  single.bodies[0].character_id = 100101;
  single.add(2253,4); single.add(2226,4);
  assert.throws(() => single.requests(null), /计算/);
  assert.throws(() => single.requests({strategy_ids:[2253,2226],selection:{errors:['技能位冲突']}}), /技能位冲突/);
  assert.throws(() => single.requests(guide([2226])), /计算/);
});

test("全潜能默认关闭，切换只改变潜能选择并跟随当前角色", () => {
  const single = new SingleBodyEditor();
  single.bodies[0].character_id = 100101;
  single.add(2226,4); single.add(2227,3);
  assert.throws(() => single.add(2253,4), /两项已选满/);
  const planned = guide([2226,2227]);
  const original = single.requests(planned)[0];
  assert.equal(original.full_potentials,false);
  single.fullPotentials = true;
  assert.deepEqual(single.requests(planned)[0], {...original, full_potentials:true});
  single.bodies[0].character_id = 103501;
  assert.equal(single.requests(planned)[0].character_id, 103501);
  single.fullPotentials = false;
  assert.deepEqual(single.requests(planned)[0], {...original, character_id:103501});
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

test("搭配计算期间合并后续编辑，只返回最新草稿的结果", async () => {
  const computations = [];
  const queue = new GuideRequestQueue((input) => {
    const response = deferred();
    computations.push({ input, ...response });
    return response.promise;
  });
  const first = queue.request([1, 2]);
  const superseded = queue.request([1]);
  const latest = queue.request([3]);
  assert.equal(await superseded, null);
  assert.deepEqual(
    computations.map((entry) => entry.input),
    [[1, 2]],
  );
  computations[0].resolve("旧搭配");
  assert.equal(await first, null);
  assert.deepEqual(
    computations.map((entry) => entry.input),
    [[1, 2], [3]],
  );
  computations[1].resolve("最新搭配");
  assert.equal(await latest, "最新搭配");
});

test("返回或切换玩法后丢弃旧计算与错误，新计算仍可执行", async () => {
  const computations = [];
  const queue = new GuideRequestQueue(() => {
    const response = deferred();
    computations.push(response);
    return response.promise;
  });
  const first = queue.request("旧玩法");
  const pending = queue.request("已离开的草稿");
  queue.invalidate();
  assert.equal(await pending, null);
  const next = queue.request("新玩法");
  computations[0].reject(new Error("旧计算失败"));
  assert.equal(await first, null);
  computations[1].reject(new Error("当前计算失败"));
  await assert.rejects(next, /当前计算失败/);
  const retry = queue.request("修改后重算");
  computations[2].resolve("可用搭配");
  assert.equal(await retry, "可用搭配");
});

test("玩法初始四槽为空，两数据体的角色颜色相互独立", () => {
  const editor = new BodyEditor(2);
  assert.deepEqual(editor.strategyIds(), []);
  editor.bodies[0].character_id = 100101;
  editor.bodies[1].character_id = 100301;
  editor.bodies[0].body_quality = 4;
  assert.equal(editor.bodies[1].body_quality, 3);
  assert.throws(() => editor.requests(), /策略/);
});
test("用户逐项选入，满四项后不能静默覆盖，移除后可重新选择", () => {
  const editor = new BodyEditor(2);
  for (const id of [2115, 3549, 3540, 3543]) editor.add(id, 4);
  assert.deepEqual(editor.strategyIds(), [2115, 3549, 3540, 3543]);
  assert.throws(() => editor.add(2401, 4), /替换/);
  assert.throws(() => editor.set(1, 1, 2115, 4), /已选/);
  editor.remove(0, 1);
  editor.add(2474, 3);
  assert.deepEqual(editor.strategyIds(), [2115, 2474, 3540, 3543]);
});
test("两体打包保持用户指定策略品质颜色；相同载体角色不允许", () => {
  const editor = new BodyEditor(2);
  for (const id of [2115, 3549, 3540, 3543]) editor.add(id, 4);
  editor.bodies[0].character_id = 100101;
  editor.bodies[1].character_id = 100101;
  assert.throws(() => editor.requests(), /不同/);
  editor.bodies[1].character_id = 100301;
  editor.bodies[1].body_quality = 4;
  editor.bodies[0].slots[0].quality = 3;
  assert.deepEqual(editor.requests(), [
    {
      character_id: 100101,
      strategy_ids: [2115, 3549],
      qualities: [3, 4],
      body_quality: 3,
    },
    {
      character_id: 100301,
      strategy_ids: [3540, 3543],
      qualities: [4, 4],
      body_quality: 4,
    },
  ]);
});
test("单体编辑状态与流派编辑相互隔离，替换只改变指定槽", () => {
  const single = new BodyEditor(1),
    pair = new BodyEditor(2);
  single.add(2115, 4);
  single.add(3540, 4);
  single.set(0, 1, 3543, 3);
  assert.deepEqual(single.strategyIds(), [2115, 3543]);
  assert.deepEqual(pair.strategyIds(), []);
});

test("推荐只影响排序，完整目录可搜索，任一所属元素均可筛选", () => {
  const rows = [
    { id: 1, name: "普攻火焰", description: "燃烧", category: "火系" },
    {
      id: 2,
      name: "冰霜脉冲",
      description: "寒气",
      category: "冰系/电系",
      is_combined: true,
    },
    { id: 3, name: "技能风暴", description: "风暴", category: "刃系" },
  ];
  const picker = new StrategyPickerModel(rows, [3]);
  assert.deepEqual(
    picker.visible().map((row) => row.id),
    [3, 1, 2],
  );
  picker.query = "冰霜";
  assert.deepEqual(
    picker.visible().map((row) => row.id),
    [2],
  );
  picker.element = "电系";
  assert.deepEqual(
    picker.visible().map((row) => row.id),
    [2],
  );
  assert.equal(picker.selected, null);
  picker.selected = 2;
  picker.element = "火系";
  assert.deepEqual(picker.visible(), []);
  assert.equal(picker.selected, 2);
});

test("自定义复制模板和继承配置，编辑与原模板隔离，完整目标不受四槽限制", () => {
  const source = new BodyEditor(2);
  source.add(3277, 4);
  const guide = {
    title: "斩杀风暴",
    definition: {
      target_ids: [3277],
      preferred_ids: [3236],
      required_inherited: [3277],
    },
  };
  const draft = CustomBuildDraft.fromGuide(guide, source);
  for (const id of [1, 2, 3, 4, 5]) draft.addTarget(id);
  draft.editor.remove(0, 0);
  assert.equal(draft.targetIds.length, 6);
  assert.deepEqual(source.strategyIds(), [3277]);
  draft.removeTarget(3277);
  assert.deepEqual(draft.document().required_inherited, []);
  assert.deepEqual(guide.definition.required_inherited, [3277]);
});

test("命名玩法可保存未完成草稿，保存标识与后续编辑状态独立", () => {
  const draft = new CustomBuildDraft();
  assert.equal(draft.dirty, true);
  assert.throws(() => draft.forSave(), /名称/);
  draft.title = "我的火环";
  draft.addTarget(2470);
  const sent = draft.forSave();
  assert.deepEqual(
    sent.bodies.map((body) => body.slots),
    [
      [null, null],
      [null, null],
    ],
  );
  draft.title = "修改中的火环";
  draft.acknowledgeSave({ ...sent, id: "saved-1" });
  assert.equal(draft.id, "saved-1");
  assert.equal(draft.title, "修改中的火环");
  assert.equal(draft.dirty, true);
  draft.acknowledgeSave(draft.forSave());
  assert.equal(draft.dirty, false);
  draft.editor.bodies[1].body_quality = 4;
  assert.equal(draft.dirty, true);
});

test("载入保存的玩法后修改不会污染保存快照，再次保存可完整还原", () => {
  const document = {
    id: "a",
    title: "火环",
    target_ids: [2470],
    preferred_ids: [],
    required_inherited: [],
    bodies: new BodyEditor(2).bodies,
  };
  const draft = new CustomBuildDraft(document, true);
  assert.equal(draft.dirty, false);
  draft.editor.add(2470, 3);
  draft.editor.bodies[0].character_id = 100101;
  draft.editor.bodies[0].body_quality = 4;
  assert.deepEqual(document.bodies[0].slots, [null, null]);
  const reloaded = new CustomBuildDraft(draft.forSave(), true);
  assert.deepEqual(reloaded.editor.strategyIds(), [2470]);
  assert.equal(reloaded.editor.bodies[0].body_quality, 4);
  assert.equal(reloaded.dirty, false);
});
