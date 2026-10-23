const test = require("node:test");
const assert = require("node:assert/strict");
const { BodyEditor } = require("../frontend/model.js");

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
