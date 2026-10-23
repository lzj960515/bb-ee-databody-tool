import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lz4.frame

from databody.save_codec import Field, Message, SaveDocument
from databody.bodies import MODEL_NAME, body_entries, double_field, double_value, nested, pack_from_save
from databody.body_types import BodyRequest
from databody.service import DataBodyService


def msg(*fields):
    return Message(fields).to_bytes()


CATALOG = {
    "characters": [{"id": 101101, "name": "白面", "base_attrs": [{"type": 1, "value": 1000}],
                    "talents": [{"id": 5034, "quality": 1, "inheritNum": 1}], "potentials": []},
                   {"id": 102101, "name": "拉格纳", "base_attrs": [{"type": 1, "value": 900}],
                    "talents": [], "potentials": []}],
    "strategies": [{"id": n, "name": str(n), "qualities": [1, 2, 3, 4]} for n in (2113, 2120, 2226, 2227)],
    "rules": {"inherit_score": 600, "page_size": 30, "page_unlock_scores": [0, 10000, 30000],
              "body_colors": [{"quality": 3, "name": "紫色", "score": 600},
                              {"quality": 4, "name": "金色", "score": 700}]},
}


def sample_save():
    actor = msg(Field.varint(1, 5), Field.varint(2, 101101), Field.bytes(99, b"existing-unknown"))
    entry = msg(Field.varint(1, 5), Field.bytes(2, actor))
    pack = msg(Field.bytes(1, entry), Field.varint(2, 5), Field.varint(5, 30000), Field.bytes(77, b"unknown"))
    model = msg(Field.bytes(1, b"ModelPlayerNewFesActorPack"), Field.bytes(2, msg(Field.bytes(1, pack))))
    other = msg(Field.bytes(1, b"ModelPlayer"), Field.bytes(2, b"do-not-change"))
    root = msg(Field.bytes(1, b"AutoSave"), Field.bytes(2, other), Field.bytes(2, model), Field.varint(6, 91))
    return lz4.frame.compress(root)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "Save" / "4"
        self.path.parent.mkdir()
        self.original = sample_save()
        self.path.write_bytes(self.original)
        catalog_path = self.root / "catalog.json"
        catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")
        self.service = DataBodyService(catalog_path=catalog_path)
        self.running = patch.object(self.service, "game_running", return_value=False)
        self.running.start()
        self.addCleanup(self.running.stop)
        self.service.load_save(self.path)

    def add(self):
        return self.service.add_body(self.path, 101101, [2113, 2120], [4, 3])

    def batch_requests(self):
        return [BodyRequest(101101, (2113, 2120), (4, 3)),
                BodyRequest(102101, (2226, 2227), (3, 4), body_quality=4)]

    def test_batch_adds_two_bodies_with_one_original_backup_and_can_restore(self):
        result = self.service.add_bodies(self.path, self.batch_requests())
        updated = self.path.read_bytes()
        document = SaveDocument.from_compressed(updated)
        _, pack = pack_from_save(document)
        _, original_pack = pack_from_save(SaveDocument.from_compressed(self.original))
        bodies = dict(body_entries(pack))
        self.assertEqual(result["uids"], [6, 7])
        self.assertEqual(result["count"], 3)
        self.assertEqual(pack.get_varint(2), 7)
        self.assertEqual(pack.get_varint(5), 31300)
        self.assertEqual(pack.fields(1)[0].raw, original_pack.fields(1)[0].raw)
        self.assertEqual(pack.get_bytes(77), b"unknown")
        self.assertEqual(document.get_model("ModelPlayer"), b"do-not-change")
        for uid, request, score in zip(result["uids"], self.batch_requests(), (600, 700)):
            with self.subTest(uid=uid):
                body = bodies[uid]
                self.assertEqual(body.get_varint(2), request.character_id)
                self.assertEqual(double_value(body, 16), score)
                inherited = [(nested(f).get_varint(1), nested(f).get_varint(2)) for f in body.fields(30)]
                self.assertEqual(inherited, list(zip(request.strategy_ids, request.qualities)))
        backups = list((self.root / "DataBodyToolBackups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        # Windows 临时目录可能用短路径，服务返回的长路径仍指向同一备份。
        self.assertTrue(backups[0].samefile(result["backup_path"]))
        self.assertEqual(backups[0].read_bytes(), self.original)
        restored = self.service.restore_backup(self.path, backups[0])
        self.assertEqual(restored["count"], 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(Path(restored["backup_path"]).read_bytes(), updated)

    def test_batch_rejects_empty_requests_without_backup_or_write(self):
        with self.assertRaisesRegex(ValueError, "至少|不能为空"):
            self.service.add_bodies(self.path, [])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_invalid_second_request_rejects_entire_batch_without_backup(self):
        invalid_requests = [BodyRequest(999999, (2226, 2227), (4, 3)),
                            BodyRequest(102101, (9999, 2227), (4, 3)),
                            BodyRequest(102101, (2226, 2226), (4, 3)),
                            BodyRequest(102101, (2226, 2227), (5, 3)),
                            BodyRequest(102101, (2226, 2227), (4, 3), body_quality=2)]
        for invalid in invalid_requests:
            with self.subTest(request=invalid), self.assertRaises(ValueError):
                self.service.add_bodies(self.path, [self.batch_requests()[0], invalid])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_batch_checks_initial_capacity_before_new_scores_unlock_another_page(self):
        self.service.catalog["rules"].update(page_size=2, page_unlock_scores=[0, 30600])
        with self.assertRaisesRegex(ValueError, "容量|位置|仓库"):
            self.service.add_bodies(self.path, self.batch_requests())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_batch_uid_overflow_rejects_entire_batch_without_backup(self):
        document = SaveDocument.from_compressed(self.original)
        model, pack = pack_from_save(document)
        pack = pack.replace(2, [Field.varint(2, (1 << 32) - 2)])
        document.replace_model(MODEL_NAME, model.replace(1, [Field.bytes(1, pack.to_bytes())]).to_bytes())
        original = document.to_compressed()
        self.path.write_bytes(original)
        self.service.load_save(self.path)
        with self.assertRaisesRegex(ValueError, "编号|上限"):
            self.service.add_bodies(self.path, self.batch_requests())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_batch_verifies_each_character_strategy_quality_and_score_before_writing(self):
        encode = SaveDocument.to_compressed

        def encode_with_mismatch(document):
            corrupted = SaveDocument.from_compressed(encode(document))
            model, pack = pack_from_save(corrupted)
            entry = nested(pack.fields(1)[-1])
            body = Message.parse(entry.get_bytes(2))
            if mismatch == "character":
                body = body.replace(2, [Field.varint(2, 101101)])
            elif mismatch == "score":
                body = body.replace(16, [double_field(16, 600)])
            else:
                blessings = list(body.fields(30))
                first = nested(blessings[0])
                field_number, value = (1, 2113) if mismatch == "strategy" else (2, 1)
                first = first.replace(field_number, [Field.varint(field_number, value)])
                blessings[0] = Field.bytes(30, first.to_bytes())
                body = body.replace(30, blessings)
            entry = entry.replace(2, [Field.bytes(2, body.to_bytes())])
            entries = [*pack.fields(1)[:-1], Field.bytes(1, entry.to_bytes())]
            pack = pack.replace(1, entries)
            corrupted.replace_model(MODEL_NAME, model.replace(1, [Field.bytes(1, pack.to_bytes())]).to_bytes())
            return encode(corrupted)

        for mismatch in ("character", "strategy", "quality", "score"):
            with self.subTest(mismatch=mismatch), patch.object(SaveDocument, "to_compressed", encode_with_mismatch):
                with self.assertRaisesRegex(ValueError, "回读验证"):
                    self.service.add_bodies(self.path, self.batch_requests())
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_batch_replace_failure_keeps_original_and_removes_temporary_file(self):
        with patch("databody.service.os.replace", side_effect=OSError("replace unavailable")):
            with self.assertRaisesRegex(OSError, "replace unavailable"):
                self.service.add_bodies(self.path, self.batch_requests())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.glob(".databody-*")), [])
        backups = list((self.root / "DataBodyToolBackups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_batch_detects_external_change_during_backup_before_replacing_file(self):
        backup = self.service._backup
        external_update = self.original + b"external update"

        def save_changed_during_backup(path, original):
            result = backup(path, original)
            path.write_bytes(external_update)
            return result

        with patch.object(self.service, "_backup", side_effect=save_changed_during_backup):
            with self.assertRaisesRegex(ValueError, "变化|重新"):
                self.service.add_bodies(self.path, self.batch_requests())
        self.assertEqual(self.path.read_bytes(), external_update)
        self.assertEqual(list(self.path.parent.glob(".databody-*")), [])
        backups = list((self.root / "DataBodyToolBackups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_add_preserves_existing_models_and_body_and_allocates_unique_id(self):
        result = self.add()
        updated = SaveDocument.from_compressed(self.path.read_bytes())
        original = SaveDocument.from_compressed(self.original)
        self.assertEqual(updated.get_model("ModelPlayer"), original.get_model("ModelPlayer"))
        old_pack = Message.parse(Message.parse(original.get_model("ModelPlayerNewFesActorPack")).get_bytes(1))
        pack = Message.parse(Message.parse(updated.get_model("ModelPlayerNewFesActorPack")).get_bytes(1))
        self.assertEqual(pack.fields(1)[0].raw, old_pack.fields(1)[0].raw)
        self.assertEqual(pack.get_bytes(77), b"unknown")
        self.assertEqual(pack.get_varint(2), 6)
        self.assertEqual(pack.get_varint(5), 30600)
        body = Message.parse(Message.parse(pack.fields(1)[1].value).get_bytes(2))
        self.assertEqual([Message.parse(f.value).get_varint(1) for f in body.fields(30)], [2113, 2120])
        self.assertEqual([Message.parse(f.value).get_varint(2) for f in body.fields(30)], [4, 3])
        self.assertEqual(Path(result["backup_path"]).read_bytes(), self.original)
        self.assertEqual(self.service.load_save(self.path)["count"], 2)

    def test_stale_loaded_save_is_rejected_without_writing(self):
        changed = self.original + b"different"
        self.path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "变化|重新"):
            self.add()
        self.assertEqual(self.path.read_bytes(), changed)

    def test_selected_color_score_is_saved_and_updates_score_records(self):
        gold = self.service.add_body(self.path, 101101, [2113, 2120], [4, 3], body_quality=4)
        added = SaveDocument.from_compressed(self.path.read_bytes())
        _, pack = pack_from_save(added)
        body = dict(body_entries(pack))[gold["uid"]]
        self.assertEqual(double_value(body, 16), 700)
        self.assertEqual(pack.get_varint(5), 30700)
        self.assertEqual(double_value(nested(pack.fields(4)[0]), 2), 700)
        self.assertEqual([nested(f).get_varint(1) for f in body.fields(30)], [2113, 2120])
        self.assertEqual([nested(f).get_varint(2) for f in body.fields(30)], [4, 3])
        self.assertEqual(Path(gold["backup_path"]).read_bytes(), self.original)

        purple = self.service.add_body(self.path, 101101, [2113, 2120], [4, 3], body_quality=3)
        _, pack = pack_from_save(SaveDocument.from_compressed(self.path.read_bytes()))
        self.assertEqual(double_value(dict(body_entries(pack))[purple["uid"]], 16), 600)
        self.assertEqual(pack.get_varint(5), 31300)
        self.assertEqual(double_value(nested(pack.fields(4)[0]), 2), 700)

    def test_unsupported_body_color_is_rejected_before_backup_or_write(self):
        for quality in (0, 1, 2, 5):
            with self.subTest(quality=quality), self.assertRaisesRegex(ValueError, "颜色"):
                self.service.add_body(self.path, 101101, [2113, 2120], [4, 3], body_quality=quality)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_running_game_is_rejected_without_writing(self):
        with patch.object(self.service, "game_running", return_value=True):
            with self.assertRaisesRegex(ValueError, "退出"):
                self.add()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_invalid_or_duplicate_strategy_is_rejected(self):
        for ids, qualities in [([2113, 2113], [4, 4]), ([9999, 2120], [4, 4]), ([2113, 2120], [5, 4])]:
            with self.subTest(ids=ids, qualities=qualities), self.assertRaises(ValueError):
                self.service.add_body(self.path, 101101, ids, qualities)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_restore_recovers_exact_original_and_backs_up_current(self):
        result = self.add()
        added = self.path.read_bytes()
        restored = self.service.restore_backup(self.path, result["backup_path"])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(Path(restored["backup_path"]).read_bytes(), added)

    def test_valid_backup_can_restore_a_selected_corrupt_save(self):
        result = self.add()
        damaged = b"damaged game save"
        self.path.write_bytes(damaged)
        with self.assertRaises(ValueError):
            self.service.load_save(self.path)
        restored = self.service.restore_backup(self.path, result["backup_path"])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(Path(restored["backup_path"]).read_bytes(), damaged)

    def test_corrupt_backup_and_wrong_target_are_rejected(self):
        result = self.add()
        before = self.path.read_bytes()
        other = self.root / "Save" / "3"
        other.write_bytes(self.original)
        self.service.load_save(other)
        with self.assertRaisesRegex(ValueError, "对应|属于"):
            self.service.restore_backup(other, result["backup_path"])
        self.service.load_save(self.path)
        Path(result["backup_path"]).write_bytes(self.original + b"corrupt")
        with self.assertRaisesRegex(ValueError, "校验|损坏"):
            self.service.restore_backup(self.path, result["backup_path"])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
