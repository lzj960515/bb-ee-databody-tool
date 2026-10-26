"""玩法面向玩家的最终搭配与手动继承选择，不读取玩家存档。"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from databody.gameplay import GameplayGuideService


ROOT = Path(__file__).resolve().parent.parent


class GameplayGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        cls.service = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), read('builds.json'))
        # 规则回归使用最小目标，独立于产品模板是否要求填满五位。
        cls.rules_service = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), {'builds': [
            {'id': 'storm-fire', 'title': '风暴火环', 'summary': '', 'targets': [2470, 2462],
             'starters': [3264, 2474, 2470, 2462], 'upgrades': [3246, 3249, 2452, 2454]},
            {'id': 'bleed-storm', 'title': '撕裂斩杀', 'summary': '', 'targets': [3277],
             'starters': [3227, 3236, 3277]},
            {'id': 'ice-pulse', 'title': '寒气脉冲', 'summary': '', 'targets': [2226, 2227, 2253],
             'starters': [2226, 2227, 2248, 2253]},
            {'id': 'lance-ice', 'title': '光枪冰锥', 'summary': '', 'targets': [2256, 2255],
             'starters': [3549, 2258, 2256, 2255], 'upgrades': [2213, 2218, 2238]},
        ]})

    def test_empty_selection_shows_complete_guide_without_filling_inheritance(self):
        guide = self.service.describe('lightning-lance')
        self.assertEqual(guide['selection']['inherited_ids'], [])
        self.assertEqual(guide['selection']['active_ids'], [])
        self.assertEqual(guide['selection']['errors'], [])
        self.assertGreater(len(guide['strategy_ids']), 4)
        self.assertEqual([lane['label'] for lane in guide['lanes']], ['普攻', '技能', '冲刺', '传承技', '召唤'])
        self.assertTrue(guide['steps'])

    def test_search_timeout_keeps_draft_without_claiming_it_is_impossible(self):
        with patch('databody.planner.ROUTE_SEARCH_SECONDS', 0):
            guide = self.service.describe_custom({'target_ids': [2253]}, [2253])
        self.assertEqual(guide['definition']['target_ids'], [2253])
        self.assertIn(2253, guide['strategy_ids'])
        self.assertIn('暂未算完', '；'.join(guide['selection']['errors']))
        self.assertNotIn('无法同时取得', '；'.join(guide['selection']['errors']))
        self.assertEqual(guide['steps'], [])
        self.assertFalse(self.service.describe_custom({'target_ids': [2253]}, [2253])['selection']['errors'])

    def test_dual_effect_stays_with_its_trigger_source_not_output_faction(self):
        guide = self.rules_service.describe('storm-fire')
        lanes = {lane['trigger']: lane['strategies'] for lane in guide['lanes']}
        self.assertIn(3264, lanes[2])  # 技能风暴
        self.assertIn(2470, lanes[2])  # 风暴火环，输出火环但触发源是风暴
        self.assertIn(2474, lanes[4])  # 传承技火环
        self.assertIn(2462, lanes[4])  # 火环燃烧，触发源是火环
        self.assertIn(3249, guide['optional_ids'])
        self.assertIn(2454, lanes[4])  # 未继承风暴火环时，III级火环仍是取得前置。
        inherited = self.rules_service.describe('storm-fire', [2470, 2462])
        self.assertIn(2454, inherited['optional_ids'])

    def test_picker_positions_follow_activation_source_and_include_alternative_slots(self):
        positions = self.service.strategy_positions()
        self.assertEqual(positions[2401], ['冲刺'])
        self.assertEqual(positions[2474], ['传承技'])
        self.assertEqual(positions[3277], ['普攻', '技能'])  # 斩杀风暴不占获取前置的传承技位。
        self.assertEqual(positions[2253], ['普攻', '技能'])  # 冰霜脉冲跟随寒气爆发。
        self.assertEqual(positions[2470], ['技能', '传承技'])  # 风暴火环跟随风暴，而非输出火环。
        self.assertEqual(set(positions), set(self.service.planner.strategies))
        self.assertTrue(all(positions.values()))

    def test_manual_selection_updates_map_and_route_from_the_same_requirements(self):
        empty = self.rules_service.describe('storm-fire')
        selected = self.rules_service.describe('storm-fire', [2470, 2462])
        self.assertEqual(selected['selection']['inherited_ids'], [2470, 2462])
        self.assertEqual(selected['selection']['active_ids'], [])
        self.assertNotEqual(selected['lanes'], empty['lanes'])
        self.assertNotIn(2401, selected['strategy_ids'])
        self.assertEqual(set(selected['strategy_ids']), {2470, 2462} |
                         {step['strategy_id'] for step in selected['steps']})
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
        self.assertEqual(len(builds), 23)
        self.assertFalse(any(item['id'].startswith('strategy-') for item in builds))
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
        self.assertEqual(selected['assumed_inherited_ids'], [])
        self.assertEqual(empty['assumed_inherited_ids'], [3534, 3546, 3539])
        self.assertNotIn(3505, [step['strategy_id'] for step in selected['steps']])
        wrong = service.describe('pure-light-seven', [3534, 3546, 3539, 3526])
        self.assertTrue(wrong['selection']['errors'])
        missing = service.describe('pure-light-seven', [3521, 3549, 3550, 3555])
        self.assertIn('需继承', '；'.join(missing['selection']['errors']))

    def test_inherited_execute_storm_frees_teacher_slot_but_keeps_execute(self):
        guide = self.service.describe('bleed-storm', [3277])
        self.assertEqual(guide['selection']['errors'], [])
        self.assertNotIn(3254, guide['strategy_ids'])
        self.assertIn(3236, guide['strategy_ids'])
        self.assertEqual(guide['lanes'][3]['strategies'], [])
        inherited_execute = self.service.describe('bleed-storm', [3236, 3277])
        self.assertNotIn(3265, inherited_execute['strategy_ids'])

    def test_inherited_ice_pulse_removes_draw_only_ice_and_lightning_requirements(self):
        regular = self.rules_service.describe('ice-pulse')
        inherited = self.rules_service.describe('ice-pulse', [2253])
        self.assertTrue({2168, 2248}.issubset(regular['strategy_ids']))
        self.assertEqual(set(inherited['strategy_ids']), {2226, 2227, 2253})
        self.assertEqual(inherited['lanes'][3]['strategies'], [])
        self.assertEqual(self.rules_service.describe('ice-pulse')['strategy_ids'], regular['strategy_ids'])

    def test_owned_dual_targets_share_the_custom_build_route_and_fill_prerequisites(self):
        for row in self.service.planner.strategies.values():
            if not row['is_combined']:
                continue
            with self.subTest(strategy=row['name']):
                owned = self.service.describe_owned([row['id']])
                expected = self.service.describe_custom({'target_ids': [row['id']]})
                self.assertEqual(owned, expected)
                self.assertGreater(len(owned['strategy_ids']), 1)
                self.assertEqual(owned['selection']['errors'], [])
                self.assert_route_legal(owned)

    def test_owned_targets_keep_explicit_bases_and_report_conflicts_like_custom_builds(self):
        owned = self.service.describe_owned([2253, 2226])
        self.assertEqual(owned['selection']['errors'], [])
        self.assertIn(2226, owned['lanes'][1]['strategies'])
        self.assertTrue({2227, 2248}.issubset(owned['strategy_ids']))
        self.assert_route_legal(owned)
        conflict = self.service.describe_owned([3227, 2226])
        self.assertTrue(conflict['selection']['errors'])
        self.assertEqual(set(conflict['strategy_ids']), {3227, 2226})

    def test_full_catalog_selection_can_change_trigger_and_use_the_freed_slot(self):
        inherited = [3226, 3236, 3277, 2170]
        guide = self.rules_service.describe('bleed-storm', inherited)
        self.assertEqual(guide['selection']['errors'], [])
        self.assertEqual(guide['selection']['inherited_ids'], inherited)
        self.assertNotIn(3227, guide['strategy_ids'])
        self.assertEqual(set(guide['lanes'][0]['strategies']), {3226, 3236, 3277})
        self.assertIn(2170, guide['lanes'][3]['strategies'])

    def test_optional_upgrades_do_not_reoccupy_released_positions(self):
        guide = self.rules_service.describe('lance-ice', [2256, 3517, 3549])
        self.assertEqual(guide['selection']['errors'], [])
        self.assertFalse({2213, 2218, 2238}.intersection(guide['strategy_ids']))
        self.assertTrue({2213, 2218, 2238}.issubset(guide['optional_ids']))

    def test_blank_custom_build_has_no_invented_strategy_or_inheritance(self):
        guide = self.service.describe_custom({'title': '', 'target_ids': []}, [])
        self.assertEqual(guide['strategy_ids'], [])
        self.assertEqual(guide['steps'], [])
        self.assertEqual(guide['suggested_ids'], [])
        self.assertEqual(guide['selection']['errors'], [])

    def test_custom_targets_and_inheritance_are_independent(self):
        definition = {'title': '冰霜斩杀', 'target_ids': [2226, 2227, 3226, 3236, 2253, 3277]}
        guide = self.service.describe_custom(definition, [2253, 3277, 3236])
        self.assertEqual(guide['selection']['errors'], [])
        self.assertTrue(set(definition['target_ids']).issubset(guide['strategy_ids']))
        self.assertEqual(guide['selection']['inherited_ids'], [2253, 3277, 3236])
        self.assertEqual(guide['lanes'][3]['strategies'], [])
        self.assert_route_legal(guide)

    def test_template_copy_preserves_delayed_activation_and_can_be_edited(self):
        source = self.service.describe('pure-light-seven')
        draft = {'title': '我的七红', **source['definition']}
        inherited = [3534, 3546, 3539, 3505]
        guide = self.service.describe_custom(draft, inherited)
        self.assertEqual(guide['selection']['errors'], [])
        acquired_ids = [step['strategy_id'] for step in guide['steps']]
        self.assertLess(acquired_ids.index(3557), acquired_ids.index(3526))
        self.assertLess(acquired_ids.index(3545), acquired_ids.index(3526))
        self.assert_route_legal(guide)

    def test_custom_target_click_order_does_not_force_acquisition_order(self):
        for targets in ([3534, 3557], [3557, 3534], [3526, 3534, 3557]):
            with self.subTest(targets=targets):
                guide = self.service.describe_custom({'target_ids': targets}, [3534])
                self.assertEqual(guide['selection']['errors'], [])
                self.assertEqual(guide['steps'][-1]['strategy_id'], 3526)
                self.assert_route_legal(guide)

    def test_seven_reds_can_plan_with_light_array_selected_first(self):
        targets = [3526, 3534, 3557, 3545, 3543, 3556, 3546, 3539]
        guide = self.service.describe_custom({'target_ids': targets}, [3534, 3546, 3539])
        self.assertEqual(guide['selection']['errors'], [])
        self.assert_route_legal(guide)

    def test_incompatible_custom_targets_stay_visible_and_explain_trigger_conflict(self):
        guide = self.service.describe_custom({'target_ids': [3227, 2226]}, [])
        self.assertTrue(guide['selection']['errors'])
        self.assertTrue({3227, 2226}.issubset(guide['strategy_ids']))
        self.assertIn('技能', '；'.join(guide['selection']['errors']))

    def test_all_dual_strategies_remain_available_as_custom_targets(self):
        for row in self.service.planner.strategies.values():
            if row['is_combined']:
                with self.subTest(strategy=row['name']):
                    guide = self.service.describe_custom({'target_ids': [row['id']]}, [])
                    self.assertEqual(guide['selection']['errors'], [])
                    self.assertIn(row['id'], guide['strategy_ids'])
                    self.assert_route_legal(guide)

    def assert_route_legal(self, guide):
        inherited = tuple(guide['selection']['inherited_ids'] + guide['assumed_inherited_ids'])
        acquired = ()
        for step in guide['steps']:
            self.assertTrue(self.service.planner.can_draw(step['strategy_id'], inherited, acquired))
            acquired += (step['strategy_id'],)
        final = self.service.planner._activate(inherited, acquired)
        self.assertTrue(set(guide['definition']['target_ids']).issubset(final.active_ids))


if __name__ == '__main__':
    unittest.main()
