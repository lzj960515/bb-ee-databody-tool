"""完整单体配置通过真实桌面桥保存；只使用合成存档。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from databody.bodies import body_entries, double_value, nested, pack_from_save
from databody.desktop_api import DesktopAPI
from databody.save_codec import SaveDocument
from databody.service import DataBodyService
from test_service import sample_save


class BodyConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'Save/4'
        self.path.parent.mkdir()
        self.original = sample_save()
        self.path.write_bytes(self.original)
        self.service = DataBodyService()
        self.api = DesktopAPI(self.service, user_data_directory=self.root / 'personal')
        self.api.load_save(str(self.path))
        running = patch.object(self.service, 'game_running', return_value=False)
        running.start()
        self.addCleanup(running.stop)

    def request(self, **options):
        return dict(character_id=103501, strategy_ids=[2226, 2227], qualities=[4, 3],
                    owned_strategies=[dict(id=2226, quality=4), dict(id=2227, quality=3)],
                    **options)

    def save(self, request):
        result = self.api.save_bodies([request])
        self.assertTrue(result['ok'], result)
        _, pack = pack_from_save(SaveDocument.from_compressed(self.path.read_bytes()))
        return dict(body_entries(pack))[result['data']['uids'][0]], result['data']

    def test_custom_hp_mp_are_saved_without_changing_other_attributes_and_restore(self):
        body, result = self.save(self.request(max_hp=5000, max_mp=500, full_potentials=True))
        attrs = {nested(f).get_varint(1): double_value(nested(f), 3) for f in body.fields(6)}
        expected = {a['type']: a['value'] for a in self.service.characters[103501]['base_attrs']}
        expected.update({1: 5000, 18: 500})
        self.assertEqual(attrs, expected)
        self.assertEqual(len(body.fields(15)), 26)
        self.assertEqual(double_value(body, 16), 600)
        self.service.restore_backup(self.path, result['backup_path'])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_invalid_attribute_input_is_rejected_before_any_write(self):
        for field in ('max_hp', 'max_mp'):
            for value in (True, '500', 0, -1, 1.5, float('nan'), float('inf'), 2**31):
                with self.subTest(field=field, value=value):
                    result = self.api.save_bodies([self.request(**{field: value})])
                    self.assertFalse(result['ok'], result)
                    self.assertEqual(self.path.read_bytes(), self.original)
                    self.assertFalse((self.root / 'DataBodyToolBackups').exists())

    def test_omitted_attributes_keep_original_character_values(self):
        body, _ = self.save(self.request())
        self.assertEqual([(nested(f).get_varint(1), double_value(nested(f), 3)) for f in body.fields(6)],
                         [(a['type'], a['value']) for a in self.service.characters[103501]['base_attrs']])
        self.assertFalse(body.fields(26))

    def test_two_teachers_keep_skill_talent_and_attack_order(self):
        body, _ = self.save(self.request(max_hp=6000, max_mp=600, inheritances=[
            dict(character_id=100301, skill_id=1003013),
            dict(character_id=100101, skill_id=1001012),
        ]))
        self.assertEqual([tuple(nested(f).get_varint(i) for i in (1, 2, 3)) for f in body.fields(26)],
                         [(1003013, 1, 100301), (1001012, 1, 100101)])
        talents = [tuple(nested(f).get_varint(i) for i in (1, 2, 3, 4)) for f in body.fields(17)]
        self.assertEqual(talents[1:], [(5025, 1, 0, 100301), (5049, 1, 0, 100101)])
        self.assertEqual(talents[0][3], 0)
        attrs = {nested(f).get_varint(1): double_value(nested(f), 3) for f in body.fields(6)}
        self.assertEqual((attrs[111], attrs[112], attrs[1], attrs[18]), (160, 170, 6000, 600))
        self.assertEqual((body.get_varint(36), body.get_varint(37)), (0, 0))
        self.assertEqual([nested(f).get_varint(1) for f in body.fields(30)], [2226, 2227])

    def test_invalid_teachers_are_rejected_before_write(self):
        teacher = dict(character_id=100101, skill_id=1001011)
        invalid = [None, {}, [None], [dict(character_id=True, skill_id=1001011)],
                   [dict(character_id=999, skill_id=9991)],
                   [dict(character_id=103501, skill_id=1035011)],
                   [dict(character_id=100301, skill_id=1001011)],
                   [teacher, teacher], [teacher, teacher, teacher]]
        for selections in invalid:
            with self.subTest(selections=selections):
                result = self.api.save_bodies([self.request(inheritances=selections)])
                self.assertFalse(result['ok'], result)
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertFalse((self.root / 'DataBodyToolBackups').exists())

    def test_initial_catalog_exposes_each_characters_actual_skill_choices(self):
        result = self.api.get_initial_data()
        self.assertTrue(result['ok'], result)
        for character in result['data']['catalog']['characters']:
            self.assertEqual([s['id'] for s in character['inherit_skill_details']], character['inherit_skills'])
            for skill in character['inherit_skill_details']:
                self.assertTrue(skill['name'])
                self.assertTrue(skill['description'])
                self.assertNotIn('{', skill['description'])


if __name__ == '__main__':
    unittest.main()
