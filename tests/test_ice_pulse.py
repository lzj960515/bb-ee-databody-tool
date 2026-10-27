"""冰霜脉冲两种前置对应的真实规划、桌面桥与存档保存回归。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from databody.bodies import body_entries, nested, pack_from_save
from databody.desktop_api import DesktopAPI
from databody.save_codec import SaveDocument
from databody.service import DataBodyService
from test_service import sample_save


class IcePulseSaveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.path = root / 'Save/4'
        self.path.parent.mkdir()
        self.original = sample_save()
        self.path.write_bytes(self.original)
        self.service = DataBodyService()
        running = patch.object(self.service, 'game_running', return_value=False)
        running.start()
        self.addCleanup(running.stop)
        self.api = DesktopAPI(self.service, user_data_directory=root / 'personal')
        self.assertTrue(self.api.load_save(str(self.path))['ok'])

    def assert_saved_and_restored(self, requests):
        saved = self.api.save_bodies(requests)
        self.assertTrue(saved['ok'], saved)
        _, pack = pack_from_save(SaveDocument.from_compressed(self.path.read_bytes()))
        bodies = dict(body_entries(pack))
        created = [bodies[uid] for uid in saved['data']['uids']]
        self.assertEqual(Path(saved['data']['backup_path']).read_bytes(), self.original)
        for body, request in zip(created, requests):
            self.assertEqual([nested(f).get_varint(1) for f in body.fields(30)], request['strategy_ids'])
        self.service.restore_backup(self.path, saved['data']['backup_path'])
        self.assertEqual(self.path.read_bytes(), self.original)
        return created

    def test_single_body_adds_normal_prerequisites_then_saves_active_ice_pulse(self):
        preview = self.api.describe_owned_strategies([2253, 2226])
        self.assertTrue(preview['ok'], preview)
        guide = preview['data']
        self.assertEqual(guide['selection']['errors'], [])
        self.assertEqual(set(guide['strategy_ids']), {2226, 2227, 2248, 2168, 2253})
        request = dict(character_id=103501, strategy_ids=[2253, 2227], qualities=[4, 4],
                       owned_strategies=[dict(id=s, quality=4) for s in guide['strategy_ids']])
        body, = self.assert_saved_and_restored([request])
        self.assertEqual({nested(f).get_varint(1) for f in body.fields(8)}, set(guide['strategy_ids']))
        self.assertTrue(all(nested(f).get_varint(3) for f in body.fields(8)))

    def test_frost_build_saves_four_inherited_strategies_without_electric_base(self):
        selected = [2253, 2283, 3448, 2252]
        preview = self.api.describe_build('skill-cold', selected)
        self.assertTrue(preview['ok'], preview)
        guide = preview['data']
        self.assertEqual(guide['selection']['errors'], [])
        self.assertTrue({2226, 2227, 2253}.issubset(guide['strategy_ids']))
        self.assertFalse({2111, 2168}.intersection(guide['strategy_ids']))
        requests = [dict(character_id=character, strategy_ids=selected[i:i + 2], qualities=[4, 4])
                    for i, character in ((0, 100101), (2, 103501))]
        self.assertEqual(len(self.assert_saved_and_restored(requests)), 2)


if __name__ == '__main__':
    unittest.main()
