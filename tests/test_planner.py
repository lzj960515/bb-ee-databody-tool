"""用当前游戏的策略关系核验规划结果，不接触玩家存档。"""
import json
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
        plan = self.planner.plan('lightning-lance')
        self.assertEqual(set(plan.starting_ids), {2115, 3549, 3540, 3543})
        self.assertEqual(set(plan.activation.active_ids), set(plan.starting_ids))
        self.assertFalse(plan.errors)

    def test_dual_effect_label_does_not_replace_base_gun_requirement(self):
        activation = self.planner.evaluate_start((2115, 3540, 3543, 3505))
        self.assertIn(3540, activation.active_ids)
        self.assertNotIn(3543, activation.active_ids)
        self.assertNotIn(3505, activation.active_ids)
        self.assertIn(6031, dict(activation.missing_labels)[3543])

    def test_fire_chain_is_active_with_skill_storm_and_inherit_fire_ring(self):
        plan = self.planner.plan('storm-fire')
        self.assertEqual(set(plan.starting_ids), {3264, 2474, 2470, 2462})
        self.assertEqual(len(plan.activation.active_ids), 4)
        self.assertFalse(plan.errors)

    def test_same_trigger_and_same_dual_trigger_are_reported(self):
        self.assertTrue(self.planner.evaluate_start((3264, 3549, 2470, 2462)).conflicts)
        self.assertTrue(self.planner.evaluate_start((2115, 3549, 3543, 3544)).conflicts)
        self.assertTrue(self.planner.evaluate_start((2115, 2115, 3540, 3543)).conflicts)

    def test_all_combined_strategies_have_selectable_routes(self):
        targets = {row['id'] for row in self.planner.strategies.values() if row['is_combined']}
        automatic = {build.targets[0] for build in self.planner.builds if build.id.startswith('strategy-')}
        self.assertEqual(targets, automatic)
        self.assertEqual(len(targets), 100)

    def test_generated_routes_use_viable_inheritance_for_each_build(self):
        for build in self.planner.builds:
            with self.subTest(build=build.id):
                plan = self.planner.plan(build.id)
                if build.required_inherited:
                    self.assertEqual(plan.starting_ids, build.required_inherited)
                else:
                    self.assertEqual(len(plan.starting_ids), 4)
                    self.assertEqual(set(plan.starting_ids), set(plan.activation.active_ids))
                self.assertFalse(plan.activation.conflicts)
                self.assertFalse(plan.errors)

    def test_normal_route_obeys_draw_rules_at_each_step(self):
        for build in self.planner.builds:
            plan = self.planner.plan(build.id)
            acquired = []
            for step in plan.steps:
                with self.subTest(build=build.id, strategy=step.strategy_id):
                    self.assertTrue(self.planner.can_draw(step.strategy_id, plan.starting_ids, acquired))
                acquired.append(step.strategy_id)

    def test_inheritance_can_skip_normal_draw_prerequisites(self):
        starts = (2115, 3549, 3540, 3543)
        self.assertFalse(self.planner.can_draw(3540, (2115, 3549), ()))
        self.assertIn(3540, self.planner.evaluate_start(starts).active_ids)

    def test_custom_incompatible_goals_are_explicit(self):
        plan = self.planner.plan('lightning-lance', targets=(3540, 3543, 3544))
        self.assertTrue(plan.errors)

    def test_inactive_inherited_tier_does_not_block_normal_same_tier_draw(self):
        # 原游戏 BuildSpecifyFactionBless / blessFilter 的独立重放回归。
        starts = (3355, 3361, 2253, 2459)
        for strategy_id in (3358, 3359, 3360, 3363):
            self.assertTrue(self.planner.can_draw(strategy_id, starts, ()))
        self.assertFalse(self.planner.can_draw(3361, starts, ()))

    def test_multiple_goals_choose_complementary_base_trigger_slots(self):
        plan = self.planner.plan('strategy-2470', targets=(2470, 2481))
        self.assertFalse(plan.errors)
        self.assertEqual(set(plan.starting_ids), {3264, 2474, 2470, 2481})

    def test_planning_does_not_need_a_character_catalog(self):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        catalog = read('catalog.json')
        catalog.pop('characters')
        planner = BuildPlanner(catalog, read('planner_rules.json'), read('builds.json'))
        self.assertFalse(planner.plan('storm-fire').errors)

    def test_manual_selection_can_be_partial_and_inactive(self):
        selected = (2470, 2462)
        plan = self.planner.plan('storm-fire', starting_ids=selected)
        self.assertEqual(plan.starting_ids, selected)
        self.assertEqual(plan.activation.active_ids, ())
        self.assertFalse(plan.errors)
        acquired = ()
        for step in plan.steps:
            self.assertTrue(self.planner.can_draw(step.strategy_id, selected, acquired))
            acquired += (step.strategy_id,)

    def test_final_dual_effects_can_coexist_after_delayed_inheritance_activation(self):
        # 先拿四张局内红，再拿召唤光阵，才激活带进来的三张红。
        inherited = (3534, 3546, 3539)
        goals = (3557, 3545, 3543, 3556, 3534, 3546, 3539)
        plan = self.planner.plan('strategy-3557', starting_ids=inherited, targets=goals)
        self.assertFalse(plan.errors)
        acquired = ()
        for step in plan.steps:
            self.assertTrue(self.planner.can_draw(step.strategy_id, inherited, acquired))
            acquired += (step.strategy_id,)
        final = self.planner._activate(inherited, acquired)
        self.assertTrue(set(goals).issubset(final.active_ids))


if __name__ == '__main__':
    unittest.main()
