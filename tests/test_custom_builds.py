"""个人玩法草稿独立持久化，不触碰模板或游戏存档。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from databody.custom_builds import CustomBuildStore
from test_service import CATALOG


def draft():
    return {
        "id": None, "title": "我的寒气玩法", "target_ids": [2227],
        "preferred_ids": [2226], "required_inherited": [],
        "bodies": [
            {"character_id": 101101, "body_quality": 3,
             "slots": [{"id": 2227, "quality": 4}, None]},
            {"character_id": None, "body_quality": 4, "slots": [None, None]},
        ],
    }


class CustomBuildStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "personal"
        self.catalog = copy.deepcopy(CATALOG)
        self.catalog["strategies"][-1]["qualities"] = [4]
        self.store = CustomBuildStore(self.catalog, directory=self.directory)
        self.path = self.directory / "custom-builds.json"

    def test_partial_draft_survives_restart_and_updates_without_duplicating(self):
        original = draft()
        saved = self.store.save(original)
        self.assertIsNone(original["id"])
        self.assertTrue(saved["id"])
        self.assertEqual(saved["bodies"], original["bodies"])
        another_draft = draft()
        another_draft["title"] = "保留的另一套搭配"
        another = self.store.save(another_draft)
        self.assertNotEqual(saved["id"], another["id"])
        restarted = CustomBuildStore(self.catalog, directory=self.directory)
        self.assertEqual(restarted.list_builds(), [saved, another])
        saved["title"] = "另一个名称"
        saved["target_ids"] = [2113, 2227]
        saved["bodies"][1]["character_id"] = 102101
        updated = restarted.save(saved)
        self.assertEqual(updated["id"], saved["id"])
        self.assertEqual(self.store.list_builds(), [updated, another])
        self.assertEqual(self.store.delete(saved["id"]), saved["id"])
        self.assertEqual(restarted.list_builds(), [another])

    def test_empty_library_is_read_only_and_default_location_is_stable(self):
        self.assertEqual(self.store.list_builds(), [])
        self.assertFalse(self.directory.exists())
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.directory)}):
            default_store = CustomBuildStore(self.catalog)
            saved = default_store.save(draft())
        expected = self.directory / "bb-ee-databody-tool" / "custom-builds.json"
        self.assertEqual(json.loads(expected.read_text(encoding="utf-8"))["builds"], [saved])

    def test_invalid_catalog_values_and_document_shapes_preserve_existing_file(self):
        self.store.save(draft())
        original_bytes = self.path.read_bytes()
        invalid = []
        for key, value in (("title", "  "), ("title", 3), ("id", True),
                           ("target_ids", [99999]), ("preferred_ids", [True]),
                           ("required_inherited", ["2113"]), ("bodies", [])):
            document = draft()
            document[key] = value
            invalid.append(document)
        for key, value in (("character_id", 99999), ("character_id", True),
                           ("body_quality", 2), ("body_quality", True),
                           ("slots", [None]), ("slots", [{"id": 99999, "quality": 4}, None]),
                           ("slots", [{"id": 2227, "quality": 3}, None]),
                           ("slots", [{"id": 2113, "quality": True}, None])):
            document = draft()
            document["bodies"][0][key] = value
            invalid.append(document)
        for document in [None, [], {}, *invalid]:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.store.save(document)
            self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_failed_atomic_replace_preserves_previous_library(self):
        saved = self.store.save(draft())
        original_bytes = self.path.read_bytes()
        saved["title"] = "不能丢失原版本"
        with patch("databody.custom_builds.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.store.save(saved)
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.store.delete(saved["id"])
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_corrupt_or_unsupported_library_is_not_replaced(self):
        self.directory.mkdir()
        for content in ("broken JSON", '{"schema_version": 2, "builds": []}',
                        '{"schema_version": 1, "builds": [null]}'):
            self.path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.store.save(draft())
            self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_unknown_update_or_delete_does_not_create_a_new_document(self):
        self.store.save(draft())
        original_bytes = self.path.read_bytes()
        document = draft()
        document["id"] = "missing"
        with self.assertRaises(ValueError):
            self.store.save(document)
        with self.assertRaises(ValueError):
            self.store.delete("missing")
        self.assertEqual(self.path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
