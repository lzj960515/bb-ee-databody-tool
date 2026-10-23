"""用当前游戏的策略关系核验规划结果，不接触玩家存档。"""
import json
import subprocess
import sys
from pathlib import Path
import unittest

from databody.planner import BuildPlanner


ROOT = Path(__file__).resolve().parent.parent


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        cls.planner = BuildPlanner(read('catalog.json'), read('planner_rules.json'), read('builds.json'))

    def test_lightning_chain_has_both_base_triggers_and_all_four_active(self):
        build = self.planner.build_by_id['lightning-lance']
        starters = self.planner.recommend_start(build.targets, build.starters)
        self.assertEqual(set(starters), {2115, 3549, 3540, 3543})
        self.assertEqual(set(self.planner.evaluate_start(starters).active_ids), set(starters))

    def test_large_custom_selection_finishes_within_interactive_budget(self):
        # 曾触发分钟级排列搜索的火系草稿；独立进程让旧代码稳定失败而不挂住测试。
        script = '''
import json
from pathlib import Path
from databody.gameplay import GameplayGuideService
read = lambda n: json.loads((Path('data') / n).read_text(encoding='utf8'))
guides = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), read('builds.json'))
result = guides.describe_custom({'target_ids': [2409,2404,2482,2466,2464,2462,2461,2463,2425,2469]})
assert result['definition']['target_ids'] == [2409,2404,2482,2466,2464,2462,2461,2463,2425,2469]
assert result['selection']['errors'] or result['steps']
assert not guides.describe_custom({'target_ids': [2253]}, [2253])['selection']['errors']
'''
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_activation_prerequisites_come_from_lower_tiers(self):
        # 相同已取得集合可共享搜索结果的前提：当前目录的激活顺序不依赖同阶取得次序。
        for strategy in self.planner.strategies.values():
            for label in (*strategy['true_pre'], *strategy['pre_labels']):
                for provider in self.planner.label_choices(label):
                    self.assertLess(self.planner.strategies[provider]['gradation'], strategy['gradation'])

    def test_dual_effect_label_does_not_replace_base_gun_requirement(self):
        activation = self.planner.evaluate_start((2115, 3540, 3543, 3505))
        self.assertIn(3540, activation.active_ids)
        self.assertNotIn(3543, activation.active_ids)
        self.assertNotIn(3505, activation.active_ids)
        self.assertIn(6031, dict(activation.missing_labels)[3543])

    def test_fire_chain_is_active_with_skill_storm_and_inherit_fire_ring(self):
        build = self.planner.build_by_id['storm-fire']
        starters = self.planner.recommend_start(build.targets, build.starters)
        self.assertEqual(set(starters), {3264, 2474, 2470, 2462})
        self.assertEqual(len(self.planner.evaluate_start(starters).active_ids), 4)

    def test_same_trigger_and_same_dual_trigger_are_reported(self):
        self.assertTrue(self.planner.evaluate_start((3264, 3549, 2470, 2462)).conflicts)
        self.assertTrue(self.planner.evaluate_start((2115, 3549, 3543, 3544)).conflicts)
        self.assertTrue(self.planner.evaluate_start((2115, 2115, 3540, 3543)).conflicts)

    def test_all_combined_strategies_can_be_planned_without_fake_recipe_entries(self):
        targets = {row['id'] for row in self.planner.strategies.values() if row['is_combined']}
        self.assertEqual(len(targets), 100)
        for strategy_id in targets:
            with self.subTest(strategy_id=strategy_id):
                self.assertIsNotNone(self.planner.complete_route((strategy_id,), ()))

    def test_generated_routes_use_viable_inheritance_for_each_build(self):
        for build in self.planner.builds:
            with self.subTest(build=build.id):
                inherited = build.required_inherited or self.planner.recommend_start(build.targets, build.starters)
                self.assertFalse(self.planner.evaluate_start(inherited).conflicts)
                self.assertIsNotNone(self.planner.complete_route(build.targets, inherited, build.starters))

    def test_normal_route_obeys_draw_rules_at_each_step(self):
        for build in self.planner.builds:
            inherited = build.required_inherited
            acquired = ()
            route = self.planner.complete_route(build.targets, inherited, build.starters)
            self.assertIsNotNone(route)
            for strategy_id in route:
                with self.subTest(build=build.id, strategy=strategy_id):
                    self.assertTrue(self.planner.can_draw(strategy_id, inherited, acquired))
                acquired += (strategy_id,)

    def test_inheritance_can_skip_normal_draw_prerequisites(self):
        starts = (2115, 3549, 3540, 3543)
        self.assertFalse(self.planner.can_draw(3540, (2115, 3549), ()))
        self.assertIn(3540, self.planner.evaluate_start(starts).active_ids)

    def test_custom_incompatible_goals_are_explicit(self):
        self.assertIsNone(self.planner.complete_route((3540, 3543, 3544), ()))

    def test_inactive_inherited_tier_does_not_block_normal_same_tier_draw(self):
        # 原游戏 BuildSpecifyFactionBless / blessFilter 的独立重放回归。
        starts = (3355, 3361, 2253, 2459)
        for strategy_id in (3358, 3359, 3360, 3363):
            self.assertTrue(self.planner.can_draw(strategy_id, starts, ()))
        self.assertFalse(self.planner.can_draw(3361, starts, ()))

    def test_multiple_goals_choose_complementary_base_trigger_slots(self):
        inherited = self.planner.recommend_start((2470, 2481))
        self.assertEqual(set(inherited), {3264, 2474, 2470, 2481})
        self.assertEqual(self.planner.complete_route((2470, 2481), inherited), ())

    def test_planning_does_not_need_a_character_catalog(self):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        catalog = read('catalog.json')
        catalog.pop('characters')
        planner = BuildPlanner(catalog, read('planner_rules.json'), read('builds.json'))
        self.assertIsNotNone(planner.complete_route((2470, 2462), ()))

    def test_manual_selection_can_be_partial_and_inactive(self):
        selected = (2470, 2462)
        self.assertEqual(self.planner.evaluate_start(selected).active_ids, ())
        route = self.planner.complete_route(selected, selected)
        self.assertIsNotNone(route)
        acquired = ()
        for strategy_id in route:
            self.assertTrue(self.planner.can_draw(strategy_id, selected, acquired))
            acquired += (strategy_id,)

    def test_final_dual_effects_can_coexist_after_delayed_inheritance_activation(self):
        # 先拿四张局内红，再拿召唤光阵，才激活带进来的三张红。
        inherited = (3534, 3546, 3539)
        goals = (3557, 3545, 3543, 3556, 3534, 3546, 3539)
        route = self.planner.complete_route(goals, inherited)
        self.assertIsNotNone(route)
        acquired = ()
        for strategy_id in route:
            self.assertTrue(self.planner.can_draw(strategy_id, inherited, acquired))
            acquired += (strategy_id,)
        final = self.planner._activate(inherited, acquired)
        self.assertTrue(set(goals).issubset(final.active_ids))


if __name__ == '__main__':
    unittest.main()
