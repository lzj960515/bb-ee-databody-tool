"""玩法面向玩家的最终搭配与手动继承选择，不读取玩家存档。"""
import json
from pathlib import Path
import unittest

from databody.gameplay import GameplayGuideService


ROOT = Path(__file__).resolve().parent.parent


class GameplayGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        cls.service = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), read('builds.json'))

    def test_empty_selection_shows_complete_guide_without_filling_inheritance(self):
        guide = self.service.describe('lightning-lance')
        self.assertEqual(guide['selection']['inherited_ids'], [])
        self.assertEqual(guide['selection']['active_ids'], [])
        self.assertEqual(guide['selection']['errors'], [])
        self.assertGreater(len(guide['strategy_ids']), 4)
        self.assertEqual([lane['label'] for lane in guide['lanes']], ['普攻', '技能', '冲刺', '传承技', '召唤'])
        self.assertTrue(guide['steps'])

    def test_dual_effect_stays_with_its_trigger_source_not_output_faction(self):
        guide = self.service.describe('storm-fire')
        lanes = {lane['trigger']: lane['strategies'] for lane in guide['lanes']}
        self.assertIn(3264, lanes[2])  # 技能风暴
        self.assertIn(2470, lanes[2])  # 风暴火环，输出火环但触发源是风暴
        self.assertIn(2474, lanes[4])  # 传承技火环
        self.assertIn(2462, lanes[4])  # 火环燃烧，触发源是火环
        self.assertIn(3249, lanes[2])  # 刀刃风暴强化仍属于技能位
        self.assertIn(2454, lanes[4])  # 双发火环仍属于传承技位

    def test_manual_selection_is_preserved_and_complete_map_is_stable(self):
        empty = self.service.describe('storm-fire')
        selected = self.service.describe('storm-fire', [2470, 2462])
        self.assertEqual(selected['selection']['inherited_ids'], [2470, 2462])
        self.assertEqual(selected['selection']['active_ids'], [])
        self.assertEqual(selected['lanes'], empty['lanes'])
        self.assertEqual(selected['strategy_ids'], empty['strategy_ids'])
        self.assertEqual(selected['selection']['errors'], [])
        self.assertTrue(selected['selection']['missing'])
        self.assertTrue(all(step['strategy_id'] not in (2470, 2462) for step in selected['steps']))
        # 已经继承火环燃烧，就不要求再为抽这张红补整条燃烧分支。
        self.assertNotIn(2401, [step['strategy_id'] for step in selected['steps']])

    def test_conflicting_inheritance_is_explained_without_changing_selection(self):
        selection = [3264, 3549, 2470, 2462]
        guide = self.service.describe('storm-fire', selection)
        self.assertEqual(guide['selection']['inherited_ids'], selection)
        self.assertTrue(guide['selection']['conflicts'])
        self.assertTrue(guide['selection']['errors'])

    def test_all_builds_have_serializable_guides_and_each_strategy_has_one_place(self):
        builds = self.service.list_builds()
        self.assertGreaterEqual(len(builds), 109)
        for item in builds:
            with self.subTest(build=item['id']):
                guide = self.service.describe(item['id'])
                json.dumps(guide, ensure_ascii=False)
                mapped = [strategy_id for lane in guide['lanes'] for strategy_id in lane['strategies']]
                mapped.extend(guide['other_strategy_ids'])
                self.assertEqual(set(mapped), set(guide['strategy_ids']))
                self.assertEqual(len(mapped), len(set(mapped)))
                self.assertEqual(guide['selection']['errors'], [])
                self.assertNotIn('character_id', guide)
                self.assertNotIn('sources', guide)

    def test_delayed_activation_guide_keeps_required_inheritance_empty_until_chosen(self):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        knowledge = {'builds': [{
            'id': 'pure-light-seven', 'title': '纯光七红', 'summary': '最后拿光阵，点亮七张双重策略。',
            'targets': [3557, 3545, 3543, 3556, 3534, 3546, 3539],
            'starters': [3534, 3546, 3539], 'required_inherited': [3534, 3546, 3539],
        }]}
        service = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), knowledge)
        empty = service.describe('pure-light-seven')
        self.assertEqual(empty['selection']['inherited_ids'], [])
        self.assertEqual(empty['required_inherited'], [3534, 3546, 3539])
        self.assertEqual(empty['selection']['errors'], [])
        self.assertEqual(empty['steps'][-1]['strategy_id'], 3526)
        selected = service.describe('pure-light-seven', [3534, 3546, 3539, 3505])
        self.assertEqual(selected['selection']['errors'], [])
        self.assertEqual(selected['lanes'], empty['lanes'])
        self.assertNotIn(3505, [step['strategy_id'] for step in selected['steps']])
        wrong = service.describe('pure-light-seven', [3534, 3546, 3539, 3526])
        self.assertTrue(wrong['selection']['errors'])
        missing = service.describe('pure-light-seven', [3521, 3549, 3550, 3555])
        self.assertIn('需继承', '；'.join(missing['selection']['errors']))


if __name__ == '__main__':
    unittest.main()
