import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lz4.frame

from databody.save_codec import Field, Message, SaveDocument
from databody.service import DataBodyService


def msg(*fields):
    return Message(fields).to_bytes()


CATALOG = {
    "characters": [{"id": 101101, "name": "白面", "base_attrs": [{"type": 1, "value": 1000}],
                    "talents": [{"id": 5034, "quality": 1, "inheritNum": 1}], "potentials": []}],
    "strategies": [{"id": n, "name": str(n), "qualities": [1, 2, 3, 4]} for n in (2113, 2120)],
    "rules": {"inherit_score": 600, "page_size": 30, "page_unlock_scores": [0, 10000, 30000]},
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
