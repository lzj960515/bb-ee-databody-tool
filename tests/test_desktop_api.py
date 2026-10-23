"""网页桌面桥与真实存档服务的受控集成测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from databody.desktop_api import DesktopAPI
from databody.service import DataBodyService
from test_service import CATALOG, sample_save


class DesktopAPITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "Save" / "4"
        self.path.parent.mkdir()
        self.original = sample_save()
        self.path.write_bytes(self.original)
        data = self.root / "data"
        data.mkdir()
        self.catalog = json.loads(json.dumps(CATALOG))
        rules = []
        for index, strategy in enumerate(self.catalog["strategies"]):
            strategy.update(labels=[], true_pre=[], pre_labels=[], gradation=1, is_combined=False)
            rules.append({"id": strategy["id"], "faction": index + 1, "second_faction": 0, "trigger_group": 0})
        (data / "catalog.json").write_text(json.dumps(self.catalog), encoding="utf-8")
        (data / "planner_rules.json").write_text(json.dumps({"strategies": rules}), encoding="utf-8")
        (data / "builds.json").write_text('{"builds": []}', encoding="utf-8")
        self.service = DataBodyService(data / "catalog.json")
        running = patch.object(self.service, "game_running", return_value=False)
        running.start()
        self.addCleanup(running.stop)
        self.window = Mock()
        self.api = DesktopAPI(self.service, resource_directory=self.root)
        self.api._window = self.window

    def requests(self):
        return [{"character_id": 101101, "strategy_ids": [2113, 2120],
                 "qualities": [4, 3], "body_quality": 3},
                {"character_id": 102101, "strategy_ids": [2226, 2227],
                 "qualities": [3, 4], "body_quality": 4}]

    def assert_unchanged(self, expected=None):
        self.assertEqual(self.path.read_bytes(), self.original if expected is None else expected)
        self.assertFalse((self.root / "DataBodyToolBackups").exists())

    def test_initial_data_and_discovery_do_not_load_a_save(self):
        initial = self.api.get_initial_data()
        self.assertTrue(initial["ok"])
        self.assertEqual(initial["data"]["catalog"], self.catalog)
        found = [{"path": str(self.path), "label": "测试存档", "modified": 1}]
        with patch.object(self.service, "discover_saves", return_value=found):
            self.assertEqual(self.api.discover_saves(), {"ok": True, "data": found})
        result = self.api.save_bodies(self.requests())
        self.assertFalse(result["ok"])
        self.assertIn("载入", result["error"])
        self.assert_unchanged()

    def test_explicit_load_then_pair_writes_one_backup_and_returns_updated_save(self):
        loaded = self.api.load_save(str(self.path))
        self.assertEqual(loaded["data"]["count"], 1)
        result = self.api.save_bodies(self.requests())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["uids"], [6, 7])
        self.assertEqual(result["data"]["save"]["count"], 3)
        self.assertEqual(len(result["data"]["save"]["bodies"]), 3)
        backups = list((self.root / "DataBodyToolBackups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_single_body_and_confirmed_restore_round_trip_original_bytes(self):
        self.api.load_save(str(self.path))
        added = self.api.save_bodies(self.requests()[:1])
        self.assertTrue(added["ok"], added)
        self.assertEqual(added["data"]["count"], 2)
        updated = self.path.read_bytes()
        self.window.create_file_dialog.return_value = (added["data"]["backup_path"],)
        self.window.create_confirmation_dialog.return_value = True
        restored = self.api.restore_backup()
        self.assertTrue(restored["ok"], restored)
        self.assertEqual(restored["data"]["save"]["count"], 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(Path(restored["data"]["backup_path"]).read_bytes(), updated)

    def test_browse_cancel_leaves_current_save_unchanged_and_selected_file_loads(self):
        self.window.create_file_dialog.return_value = None
        self.assertEqual(self.api.browse_save(), {"ok": True, "data": None})
        self.window.create_file_dialog.return_value = (str(self.path),)
        self.assertEqual(self.api.browse_save()["data"]["path"], str(self.path.resolve()))
        self.window.create_file_dialog.return_value = None
        self.assertEqual(self.api.browse_save(), {"ok": True, "data": None})
        self.assertTrue(self.api.save_bodies(self.requests()[:1])["ok"])

    def test_restore_cancel_and_decline_leave_file_unchanged(self):
        self.api.load_save(str(self.path))
        self.window.create_file_dialog.return_value = None
        self.assertEqual(self.api.restore_backup(), {"ok": True, "data": None})
        self.window.create_file_dialog.return_value = (str(self.root / "unused.bak"),)
        self.window.create_confirmation_dialog.return_value = False
        self.assertEqual(self.api.restore_backup(), {"ok": True, "data": None})
        self.assert_unchanged()

    def test_duplicate_carrier_and_invalid_second_selection_reject_entire_pair(self):
        self.api.load_save(str(self.path))
        duplicate = self.requests()
        duplicate[1]["character_id"] = duplicate[0]["character_id"]
        invalid_strategy = self.requests()
        invalid_strategy[1]["strategy_ids"] = [9999, 2227]
        invalid_quality = self.requests()
        invalid_quality[1]["body_quality"] = 2
        for requests in (duplicate, invalid_strategy, invalid_quality, [], self.requests() * 2):
            with self.subTest(requests=requests):
                self.assertFalse(self.api.save_bodies(requests)["ok"])
                self.assert_unchanged()

    def test_stale_and_running_game_are_rejected_through_service(self):
        self.api.load_save(str(self.path))
        with patch.object(self.service, "game_running", return_value=True):
            running = self.api.save_bodies(self.requests())
        self.assertFalse(running["ok"])
        self.assertIn("退出", running["error"])
        self.assert_unchanged()
        changed = self.original + b"external change"
        self.path.write_bytes(changed)
        stale = self.api.save_bodies(self.requests())
        self.assertFalse(stale["ok"])
        self.assertIn("重新载入", stale["error"])
        self.assert_unchanged(changed)

    def test_pair_merge_conflict_is_rejected_before_any_write(self):
        self.api.load_save(str(self.path))
        rules_path = self.root / "data" / "planner_rules.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules["strategies"][0]["trigger_group"] = 3
        rules["strategies"][2]["trigger_group"] = 3
        rules_path.write_text(json.dumps(rules), encoding="utf-8")
        result = self.api.save_bodies(self.requests())
        self.assertFalse(result["ok"])
        self.assertIn("触发位", result["error"])
        self.assert_unchanged()

    def test_successful_write_is_reported_when_refresh_fails(self):
        self.api.load_save(str(self.path))
        with patch.object(self.service, "load_save", side_effect=OSError("文件暂时不可读")):
            result = self.api.save_bodies(self.requests())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["uids"], [6, 7])
        self.assertIsNone(result["data"]["save"])
        self.assertIn("重新读取失败", result["data"]["warning"])
        self.assertEqual(self.service.load_save(self.path)["count"], 3)
        self.assertFalse(self.api.save_bodies(self.requests())["ok"])

    def test_restore_rechecks_loaded_hash_after_backup_selection(self):
        self.api.load_save(str(self.path))
        added = self.api.save_bodies(self.requests()[:1])["data"]
        changed = self.path.read_bytes() + b"external change"
        self.path.write_bytes(changed)
        self.window.create_file_dialog.return_value = (added["backup_path"],)
        self.window.create_confirmation_dialog.return_value = True
        result = self.api.restore_backup()
        self.assertFalse(result["ok"])
        self.assertIn("重新载入", result["error"])
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(len(list((self.root / "DataBodyToolBackups").glob("*.bak"))), 1)

    def test_failed_load_clears_writable_target_and_allows_selected_corrupt_save_restore(self):
        self.api.load_save(str(self.path))
        added = self.api.save_bodies(self.requests()[:1])["data"]
        damaged = b"damaged game save"
        self.path.write_bytes(damaged)
        self.assertFalse(self.api.load_save(str(self.path))["ok"])
        self.assertFalse(self.api.save_bodies(self.requests())["ok"])
        self.window.create_file_dialog.return_value = (added["backup_path"],)
        self.window.create_confirmation_dialog.return_value = True
        restored = self.api.restore_backup()
        self.assertTrue(restored["ok"], restored)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(Path(restored["data"]["backup_path"]).read_bytes(), damaged)

    def test_restore_requires_selected_save_before_showing_dialog(self):
        result = self.api.restore_backup()
        self.assertFalse(result["ok"])
        self.assertIn("选择", result["error"])
        self.window.create_file_dialog.assert_not_called()
        self.assert_unchanged()

    def test_malformed_web_inputs_return_errors_without_modification(self):
        self.api.load_save(str(self.path))
        malformed = self.requests()
        malformed[0]["qualities"][0] = True
        for request in (None, {}, "not requests", [None], [{"character_id": 101101}], malformed):
            with self.subTest(request=request):
                result = self.api.save_bodies(request)
                self.assertFalse(result["ok"])
                self.assertIsInstance(result["error"], str)
                self.assert_unchanged()


if __name__ == "__main__":
    unittest.main()
