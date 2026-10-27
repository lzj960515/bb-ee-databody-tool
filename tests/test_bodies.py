"""以游戏自带 protobuf 解码器及已恢复配置核验数据体创建契约。"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import lz4.frame

from databody.bodies import append_body, body_entries, create_body, pack_from_save
from databody.save_codec import Field, Message, SaveDocument
from databody.service import DataBodyService
from databody.body_types import BodyInheritance, BodyRequest, BodyStrategy


ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))


def sample_document(uid_next=8, existing_uid=3, total=30000):
    actor = Message([Field.varint(1, existing_uid), Field.varint(2, 100101)])
    entry = Message([Field.varint(1, existing_uid), Field.bytes(2, actor.to_bytes())])
    pack = Message([Field.bytes(1, entry.to_bytes()), Field.varint(2, uid_next),
                    Field.varint(5, total), Field.bytes(99, b"pack-unknown")])
    wrapper = Message([Field.bytes(1, pack.to_bytes())])
    model = Message([Field.bytes(1, b"ModelPlayerNewFesActorPack"),
                     Field.bytes(2, wrapper.to_bytes())])
    root = Message([Field.bytes(1, b"AutoSave"), Field.bytes(2, model.to_bytes())])
    return SaveDocument.from_compressed(lz4.frame.compress(root.to_bytes()))


def decode_encrypted_js(path: Path, expected_prefix: bytes) -> bytes:
    raw = path.read_bytes()
    if not raw.startswith(b"NOAH"):
        raise AssertionError("调查资源必须保持游戏原始 NOAH 包装")
    encrypted = raw[4:]
    seed = bytes(a ^ b for a, b in zip(encrypted[:4], expected_prefix[:4]))
    key = b"".join(seed[index:] + seed[:index] for index in range(4))
    decoded = bytes(value ^ key[index % 16] for index, value in enumerate(encrypted))
    if not decoded.startswith(expected_prefix):
        raise AssertionError("游戏 protobuf JS 解密前缀不匹配")
    return decoded


NODE_ORACLE = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const protobuf = require(input.minimal);
const moduleState = {exports: {}};
vm.runInNewContext(fs.readFileSync(input.pbdef, 'utf8'), {
  module: moduleState,
  require(name) {
    if (name === 'protobufjs/minimal') return protobuf;
    throw new Error('Unexpected generated-code dependency: ' + name);
  }
}, {timeout: 30000});
const P = moduleState.exports;
function replayInheritance(actor) {
  const paths = input.replayPaths;
  const readRows = (name) => JSON.parse(fs.readFileSync(paths.configs + '/' + name + '.json', 'utf8'));
  const actorConfigs = readRows('BaseActorConf').map(row => P.BaseActorConf.fromObject(row));
  const blessConfigs = readRows('BlessConf').map(row => P.BlessConf.fromObject(row));
  const rewards = readRows('BreedDungeonInheritReward').map(row => P.BreedDungeonInheritReward.fromObject(row));
  const source = fs.readFileSync(paths.dungeon, 'utf8');
  const actorSource = fs.readFileSync(paths.actor, 'utf8');
  const actorUtilSource = fs.readFileSync(paths.actorUtil, 'utf8');
  const between = (text, start, end) => {
    const offset = text.indexOf(start);
    if (offset < 0) throw new Error('Original method not found: ' + start);
    const limit = text.indexOf(end, offset + start.length);
    if (limit < 0) throw new Error('Original method boundary not found: ' + end);
    return text.slice(offset, limit).trim();
  };
  const context = vm.createContext({P,
    Misc_1: {Misc: readRows('Misc')[0]},
    Xlsx_1: {Xlsx: {
      BaseActorConf: {Get(id) {return actorConfigs.find(row => row.actorId === id);}},
      BlessConf: {Get(id) {return blessConfigs.find(row => row.id === id);}},
      BreedDungeonInheritReward: {All: rewards}
    }},
    Player_1: {ModelPlayer: {Instance: {GetFesActor(uid) {return uid === actor.uid ? actor : undefined;}}}},
    Task_1: {TaskUtil: {CheckTask() {}}},
  });
  const addSkill = between(actorSource, 'function AddSkill(', 'function AddBless(');
  const addTalent = between(actorSource, 'function AddTalent(', 'function AttrValid(');
  context.Actor_1 = {
    FesActorUtils: vm.runInContext('(' + 'function(){' + addSkill + addTalent + ';return {AddSkill, AddTalent};})()', context),
    MergeAttr(...attributes) {return attributes;}
  };
  const blessMethod = between(source, 'getInheritBless() {', 'sanBuffFunctions() {');
  const rewardMethod = between(source, 'initFactorActorRewards() {', 'extraAddResource() {');
  const dungeon = vm.runInContext('({' + blessMethod + ',' + rewardMethod + '})', context);
  const colorMethod = between(actorUtilSource, 'static GetFactorActorQuality(', 'static InitPlayerObjAttrFromFesActor(').replace(/^static /, '');
  const colorRules = vm.runInContext('({' + colorMethod + '})', context);
  dungeon.baseInfo = {factorActorUid: [actor.uid]};
  dungeon.rewardInfo = {inheritBlessEnable: [], inheritAttrs: []};
  dungeon.FesActor = P.STFesActor.create();
  dungeon.dungeonFunctions = () => [];
  dungeon.initFactorActorRewards();
  return {
    bodyQuality: colorRules.GetFactorActorQuality(actor.score),
    strategies: dungeon.getInheritBless().map(row => ({id: row.id, quality: row.quality})),
    skills: dungeon.FesActor.skills.map(row => ({id: row.id, level: row.level, fromActorId: row.fromActorId})),
    talents: dungeon.FesActor.talents.map(row => ({id: row.id, quality: row.quality, fromActorId: row.fromActorId}))
  };
}
const result = input.records.map(record => {
  const type = P[record.type];
  const decoded = type.decode(Buffer.from(record.payload, 'base64'));
  const error = type.verify(decoded);
  if (error) throw new Error(error);
  const output = type.toObject(decoded, {defaults: true, longs: String, bytes: String});
  if (record.refreshOwned) {
    const actorSource = fs.readFileSync(input.replayPaths.actor, 'utf8');
    const start = actorSource.indexOf('function RefreshBlessActive(');
    const end = actorSource.indexOf('function GetFesActorAttrByType(', start);
    if (start < 0 || end < 0) throw new Error('Original activation method missing');
    const configs = JSON.parse(fs.readFileSync(input.replayPaths.configs + '/BlessConf.json', 'utf8'));
    const context = vm.createContext({P,
      Xlsx_1: {Xlsx: {BlessConf: {Get(id) {return P.BlessConf.fromObject(configs.find(row => row.id === id));}}}},
      Bless_1: {BlessUtils: {BLESS_SPECIAL_SOURCE: [P.EBreedDungeonBlessSource.Master, P.EBreedDungeonBlessSource.Special]}},
      Quest_1: {QuestUtil: {CheckTarget() {}}}, Task_1: {TaskUtil: {CheckTask() {}}},
    });
    const refresh = vm.runInContext('(' + actorSource.slice(start, end).trim() + ')', context);
    refresh(decoded.blesses);
    output.refreshedOwned = decoded.blesses.map(row => ({id: row.id, quality: row.quality, active: row.active}));
  }
  if (record.replay) output.inheritanceReplay = replayInheritance(decoded);
  return output;
});
process.stdout.write(JSON.stringify(result, (_, value) => typeof value === 'bigint' ? value.toString() : value));
"""


class GameSchemaOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        assets = ROOT / "research/resources/extracted/data/js"
        pbdef = list((assets / "gen/pbdef").glob("*.txt"))
        minimal = list((assets / "protobufjs/minimal").glob("*.txt"))
        if not cls.node or len(pbdef) != 1 or len(minimal) != 1:
            raise unittest.SkipTest("独立游戏解码验证需要调查资源和 Node.js")
        cls.temp = tempfile.TemporaryDirectory(prefix="bb-ee-protobuf-oracle-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cls.pbdef = directory / "pbdef.js"
        cls.minimal = directory / "minimal.js"
        cls.pbdef.write_bytes(decode_encrypted_js(pbdef[0], b'"use strict";var $protobuf='))
        cls.minimal.write_bytes(decode_encrypted_js(minimal[0], b"/*!\n * protobuf.js"))

    def decode(self, records, replay=False):
        request = {"minimal": str(self.minimal), "pbdef": str(self.pbdef), "records": records}
        if replay:
            request["replayPaths"] = {
                "configs": str(ROOT / "research/resources/configs"),
                "dungeon": str(ROOT / "research/js-selected/server/model/breeddungeon.js"),
                "actor": str(ROOT / "research/js-selected/server/module/actor.js"),
                "actorUtil": str(ROOT / "research/js-selected/core/actorutil.js"),
            }
        completed = subprocess.run([self.node, "-e", NODE_ORACLE], input=json.dumps(request),
                                   capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr[-8000:])
        return json.loads(completed.stdout)

    def record(self, type_name, payload):
        return {"type": type_name, "payload": base64.b64encode(payload).decode("ascii")}

    def test_all_characters_are_decoded_by_shipped_game_schema(self):
        strategy_ids = [CATALOG["strategies"][0]["id"], CATALOG["strategies"][1]["id"]]
        qualities = [4, 3]
        records = []
        for index, character in enumerate(CATALOG["characters"]):
            body = create_body(200 + index, character, strategy_ids, qualities, 600)
            records.append(self.record("STFesActor", body.to_bytes()))
        decoded = self.decode(records)
        self.assertEqual(len(decoded), 17)
        for index, (character, actor) in enumerate(zip(CATALOG["characters"], decoded)):
            with self.subTest(character=character["id"]):
                self.assertEqual(actor["uid"], 200 + index)
                self.assertEqual(actor["id"], character["id"])
                self.assertEqual(actor["score"], 600)
                self.assertEqual(actor["inheritSkillIndex"], 0)
                self.assertEqual(actor["inheritSkillLevel"], 0)
                self.assertTrue(actor["isGenerated"])
                self.assertEqual([(a["type"], a["value"]) for a in actor["baseAttrs"]],
                                 [(a["type"], a["value"]) for a in character["base_attrs"]])
                expected = list(zip(strategy_ids, qualities, [True, True]))
                for field in ("blesses", "inheritBlesses"):
                    self.assertEqual([(b["id"], b["quality"], b["active"]) for b in actor[field]], expected)
                self.assertEqual([(t["id"], t["quality"], t["inheritNum"]) for t in actor["talents"]],
                                 [(t["id"], t["quality"], t.get("inheritNum", 0)) for t in character["talents"]])
                self.assertEqual([p["id"] for p in actor["potentials"]],
                                 [p["id"] for p in character["potentials"]])

    def test_modified_real_save_copy_is_decoded_by_shipped_game_schema(self):
        original_path = ROOT / "research/save-slot4.decoded"
        if not original_path.exists():
            self.skipTest("需要只读调查提取的存档副本")
        original = original_path.read_bytes()
        document = SaveDocument.from_compressed(lz4.frame.compress(original))
        before = document.message.fields()
        uid = append_body(document, CATALOG["characters"][0], [2226, 2227], [4, 3], CATALOG["rules"])
        _, pack = pack_from_save(document)
        records = [self.record("DataSave", document.message.to_bytes()),
                   self.record("STPlayerNewFesActorPack", document.get_model("ModelPlayerNewFesActorPack"))]
        root, player_pack = self.decode(records)
        self.assertEqual(root["id"], "AutoSave")
        self.assertEqual(len(root["messages"]), 30)
        actor_pack = player_pack["fesActorPack"]
        self.assertEqual(len(actor_pack["dict"]), 42)
        self.assertEqual(actor_pack["uidNext"], uid)
        self.assertEqual(actor_pack["dict"][str(uid)]["inheritBlesses"][0]["id"], 2226)
        self.assertEqual(len(body_entries(pack)), 42)
        changed = [a.number for a, b in zip(before, document.message.fields()) if a.raw != b.raw]
        self.assertEqual(changed, [2])
        self.assertEqual(original_path.read_bytes(), original)

    def test_original_inheritance_methods_accept_all_created_characters(self):
        records = []
        for index, character in enumerate(CATALOG["characters"]):
            body = create_body(300 + index, character, [2226, 2227], [4, 3], 600)
            record = self.record("STFesActor", body.to_bytes())
            record["replay"] = True
            records.append(record)
        results = self.decode(records, replay=True)
        for character, result in zip(CATALOG["characters"], results):
            with self.subTest(character=character["id"]):
                inherited = result["inheritanceReplay"]
                self.assertEqual(inherited["strategies"], [{"id": 2226, "quality": 4}, {"id": 2227, "quality": 3}])
                self.assertEqual(inherited["skills"], [{"id": character["inherit_skills"][0], "level": 1,
                                                       "fromActorId": character["id"]}])
                self.assertEqual(inherited["talents"], [{"id": character["talents"][0]["id"],
                                                        "quality": character["talents"][0]["quality"],
                                                        "fromActorId": character["id"]}])

    def test_full_bodies_decode_and_preserve_game_activation_and_two_item_inheritance(self):
        potentials = json.loads((ROOT / 'research/resources/configs/BaseActorPotentialConf.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(prefix='bb-ee-full-body-') as directory:
            path = Path(directory) / 'Save/4'
            path.parent.mkdir()
            path.write_bytes(sample_document().to_compressed())
            service = DataBodyService()
            service.load_save(path)
            records = []
            for character in CATALOG['characters']:
                # 高阶排前面，原始游戏仍按层级扫描；2253缺前置应保持未激活。
                owned = (BodyStrategy(2253, 4), BodyStrategy(2227, 3), BodyStrategy(2226, 4))
                with patch.object(service, 'game_running', return_value=False):
                    result = service.add_body(path, character['id'], [2226, 2227], [4, 3],
                                              owned_strategies=owned, full_potentials=True)
                _, pack = pack_from_save(SaveDocument.from_compressed(path.read_bytes()))
                record = self.record('STFesActor', dict(body_entries(pack))[result['uid']].to_bytes())
                record.update(replay=True, refreshOwned=True)
                records.append(record)
            for character, actor in zip(CATALOG['characters'], self.decode(records, replay=True)):
                with self.subTest(character=character['id']):
                    expected_ids = {p['id'] for p in potentials if p.get('actorId') == character['id'] and not p.get('invalid')}
                    self.assertEqual({p['id'] for p in actor['potentials']}, expected_ids)
                    self.assertEqual(len(actor['potentials']), len(expected_ids))
                    expected_owned = [{'id': 2253, 'quality': 4, 'active': False},
                                      {'id': 2227, 'quality': 3, 'active': True},
                                      {'id': 2226, 'quality': 4, 'active': True}]
                    self.assertEqual(actor['refreshedOwned'], expected_owned)
                    self.assertEqual([(r['id'], r['quality'], r['active']) for r in actor['blesses']],
                                     [(r['id'], r['quality'], r['active']) for r in expected_owned])
                    self.assertEqual(actor['inheritanceReplay']['strategies'],
                                     [{'id': 2226, 'quality': 4}, {'id': 2227, 'quality': 3}])

    def test_selected_colors_match_original_color_and_inheritance_rules(self):
        records = []
        character = CATALOG["characters"][0]
        with tempfile.TemporaryDirectory(prefix="bb-ee-color-save-") as directory:
            path = Path(directory) / "Save/4"
            path.parent.mkdir()
            path.write_bytes(sample_document().to_compressed())
            service = DataBodyService()
            service.load_save(path)
            for color in CATALOG["rules"]["body_colors"]:
                with patch.object(service, "game_running", return_value=False):
                    added = service.add_body(path, character["id"], [2226, 2227], [4, 3],
                                             body_quality=color["quality"])
                _, pack = pack_from_save(SaveDocument.from_compressed(path.read_bytes()))
                body = dict(body_entries(pack))[added["uid"]]
                record = self.record("STFesActor", body.to_bytes())
                record["replay"] = True
                records.append(record)
        results = self.decode(records, replay=True)
        for color, actor in zip(CATALOG["rules"]["body_colors"], results):
            with self.subTest(color=color["name"]):
                self.assertEqual(actor["score"], color["score"])
                self.assertEqual(actor["inheritanceReplay"]["bodyQuality"], color["quality"])
                self.assertEqual(actor["inheritanceReplay"]["strategies"],
                                 [{"id": 2226, "quality": 4}, {"id": 2227, "quality": 3}])

    def test_configured_attributes_and_all_teacher_skills_decode_by_game_schema(self):
        original_characters = json.loads((ROOT / 'research/resources/configs/BaseActorConf.json').read_text('utf-8'))
        original_attrs = json.loads((ROOT / 'research/resources/configs/BaseActorAttrConf.json').read_text('utf-8'))
        characters = {c['actorId']: c for c in original_characters}
        attrs = {c['actorId']: c['attr'] for c in original_attrs}
        records, expected = [], []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Save/4'
            path.parent.mkdir()
            path.write_bytes(sample_document().to_compressed())
            service = DataBodyService()
            service.load_save(path)
            for index, character in enumerate(CATALOG['characters']):
                teachers = [CATALOG['characters'][(index + offset) % 17]['id'] for offset in (1, 2)]
                for variant in (0, 1):
                    selections = tuple(BodyInheritance(t, characters[t]['inheritSkill'][variant]) for t in teachers)
                    request = BodyRequest(character['id'], (2226, 2227), (4, 3), full_potentials=True,
                                          max_hp=5000 + index, max_mp=500 + index, inheritances=selections)
                    with patch.object(service, 'game_running', return_value=False):
                        result = service.add_bodies(path, [request])
                    _, pack = pack_from_save(SaveDocument.from_compressed(path.read_bytes()))
                    records.append(self.record('STFesActor', dict(body_entries(pack))[result['uids'][0]].to_bytes()))
                    expected.append((request, teachers))
        for actor, (request, teachers) in zip(self.decode(records), expected):
            with self.subTest(character=request.character_id, skills=request.inheritances):
                values = {a['type']: a['value'] for a in actor['baseAttrs']}
                self.assertEqual((values[1], values[18]), (request.max_hp, request.max_mp))
                self.assertEqual(len(actor['skills']), 2)
                self.assertEqual(len(actor['talents']), 3)
                for slot, (selection, teacher) in enumerate(zip(request.inheritances, teachers)):
                    skill = actor['skills'][slot]
                    self.assertEqual((skill['id'], skill['level'], skill['fromActorId']),
                                     (selection.skill_id, 1, teacher))
                    talent = actor['talents'][slot + 1]
                    self.assertEqual((talent['id'], talent['quality'], talent['fromActorId']),
                                     (characters[teacher]['talents'][0]['id'],
                                      characters[teacher]['talents'][0]['quality'], teacher))
                    self.assertEqual(values[111 + slot], next(a['value'] for a in attrs[teacher] if a['type'] == 6))
                self.assertEqual(actor['inheritSkillIndex'], 0)
                self.assertEqual(actor['inheritSkillLevel'], 0)


class BodyLifecycleTests(unittest.TestCase):
    def test_uid_follows_game_preincrement_and_preserves_unknown_pack_data(self):
        document = sample_document(uid_next=8)
        uid = append_body(document, CATALOG["characters"][0], [2226, 2227], [4, 3], CATALOG["rules"])
        _, pack = pack_from_save(document)
        self.assertEqual(uid, 9)
        self.assertEqual(pack.get_varint(2), 9)
        self.assertEqual(pack.get_varint(5), 30600)
        self.assertEqual(pack.get_bytes(99), b"pack-unknown")

    def test_full_capacity_rejects_without_mutating_document(self):
        document = sample_document()
        original = document.to_compressed()
        rules = {"inherit_score": 600, "page_size": 1, "page_unlock_scores": [0]}
        with self.assertRaisesRegex(ValueError, "已满"):
            append_body(document, CATALOG["characters"][0], [2226, 2227], [4, 3], rules)
        self.assertEqual(document.to_compressed(), original)

    def test_change_during_backup_is_detected_before_file_replace(self):
        with tempfile.TemporaryDirectory(prefix="bb-ee-commit-check-") as directory:
            path = Path(directory) / "Save/4"
            path.parent.mkdir()
            original = sample_document().to_compressed()
            external_update = sample_document(uid_next=12).to_compressed()
            path.write_bytes(original)
            service = DataBodyService()
            service.load_save(path)
            real_backup = service._backup

            def concurrent_save(target, contents):
                result = real_backup(target, contents)
                target.write_bytes(external_update)
                return result

            with patch.object(service, "game_running", return_value=False), \
                 patch.object(service, "_backup", side_effect=concurrent_save):
                with self.assertRaisesRegex(ValueError, "变化|重新"):
                    service.add_body(path, CATALOG["characters"][0]["id"], [2226, 2227], [4, 3])
            self.assertEqual(path.read_bytes(), external_update)
            self.assertEqual(len(list(path.parent.glob(".databody-*"))), 0)
            backups = list((path.parent.parent / "DataBodyToolBackups").glob("*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
