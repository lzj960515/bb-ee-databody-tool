"""基础玩法只保留核心，完整搭配按真实策略覆盖五个位置。"""
import json
from pathlib import Path
import unittest

from databody.gameplay import GameplayGuideService

ROOT = Path(__file__).resolve().parent.parent


class BuildCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        read = lambda name: json.loads((ROOT / 'data' / name).read_text(encoding='utf-8'))
        cls.guides = GameplayGuideService(read('catalog.json'), read('planner_rules.json'), read('builds.json'))

    def test_complete_builds_cover_each_dash_and_skill_base_with_full_five_positions(self):
        planner = self.guides.planner
        basic_ids = {'bleed-storm', 'ice-pulse', 'tentacle-blackhole'}
        complete_builds = [build for build in planner.builds if build.id not in basic_ids]
        self.assertEqual(len(complete_builds), 20)
        covered = {2: set(), 3: set()}
        for build in complete_builds:
            for inherited in ((), build.starters):
                with self.subTest(build=build.id, inherited=inherited):
                    guide = self.guides.describe(build.id, inherited)
                    self.assertEqual(guide['selection']['errors'], [])
                    self.assertEqual(guide['selection']['inherited_ids'], list(inherited))
                    for lane in guide['lanes']:
                        gradations = {planner.strategies[i]['gradation'] for i in lane['strategies']}
                        self.assertTrue({1, 2, 3, 4}.issubset(gradations), (build.id, lane))
                        bases = [i for i in lane['strategies'] if planner.rules[i]['trigger_group']]
                        self.assertEqual(len(bases), 1)
                        if lane['trigger'] in covered:
                            covered[lane['trigger']].update(bases)
        for trigger in (2, 3):
            expected = {i for i, rule in planner.rules.items() if rule['trigger_group'] == trigger}
            self.assertEqual(covered[trigger], expected)

    def test_ordinary_chains_keep_their_names_without_contract_requirements(self):
        expected = {'pure-light-seven': '纯光七红', 'poison-cycle': '毒弹催化',
                    'skill-poison-ring': '中毒毒弹', 'skill-poison-pool': '毒液催化',
                    'shadow-pile': '影链电桩', 'lightwave': '光波传递', 'lance-ice': '光枪冰锥'}
        for build_id, title in expected.items():
            with self.subTest(build=build_id):
                guide = self.guides.describe(build_id)
                self.assertEqual(guide['title'], title)
                text = ' '.join([guide['title'], guide['summary'], *guide['notes']])
                self.assertNotIn('脚底抹油', text)
                self.assertNotIn('融会贯通', text)
                self.assertEqual(guide['selection']['errors'], [])
        self.assertEqual(self.guides.describe('lightning-lance')['title'], '脚底抹油 · 落雷光枪')
        self.assertEqual(self.guides.describe('storm-fire')['title'], '融会贯通 · 风暴火环')
        contract_ids = {build.id for build in self.guides.planner.builds
                        if build.title.startswith(('脚底抹油', '融会贯通'))}
        self.assertEqual(contract_ids, {'lightning-lance', 'storm-fire'})

    def test_three_basic_builds_keep_the_requested_core_without_forcing_five_lanes(self):
        expected = {'bleed-storm': {3227, 3236, 3277},
                    'ice-pulse': {2226, 2227, 2248, 2253},
                    'tentacle-blackhole': {3403, 3438, 3435, 3448}}
        basics = [b for b in self.guides.planner.builds if b.title.startswith('基础玩法')]
        self.assertEqual({b.id for b in basics}, set(expected))
        for build in basics:
            self.assertTrue(expected[build.id].issubset(build.targets))
            self.assertFalse(self.guides.describe(build.id)['selection']['errors'])

    def test_basic_previews_inherit_core_duals_without_unrelated_acquisition_branches(self):
        cases = [('bleed-storm', 3277, {2}),
                 ('ice-pulse', 2253, {2}),
                 ('tentacle-blackhole', 3448, {4, 5})]
        for build_id, core_dual, expected_positions in cases:
            with self.subTest(build=build_id):
                preview = self.guides.describe(build_id)
                self.assertEqual(preview['selection']['inherited_ids'], [])
                self.assertEqual(preview['selection']['errors'], [])
                occupied = {lane['trigger'] for lane in preview['lanes'] if lane['strategies']}
                self.assertEqual(occupied, expected_positions)
                self.assertIn(core_dual, preview['required_inherited'])
                self.assertNotIn(core_dual, [step['strategy_id'] for step in preview['steps']])
                selected = self.guides.describe(build_id, [core_dual])
                self.assertEqual(selected['selection']['errors'], [])
                self.assertEqual(selected['assumed_inherited_ids'], [])
                self.assertEqual(selected['lanes'], preview['lanes'])

    def test_built_in_previews_do_not_fill_extra_trigger_positions_for_acquisition(self):
        planner = self.guides.planner
        for build in planner.builds:
            with self.subTest(build=build.id):
                guide = self.guides.describe(build.id)
                additional_bases = [planner.name(i) for i in guide['strategy_ids']
                                    if planner.rules[i]['trigger_group'] and i not in build.targets]
                self.assertEqual(additional_bases, [])

    def test_bleed_builds_use_blade_recall_instead_of_an_unrelated_burning_branch(self):
        for build_id in ('dash-sword', 'skill-bleed'):
            for inherited in ((), (3255, 3257, 3256, 3276)):
                with self.subTest(build=build_id, inherited=inherited):
                    guide = self.guides.describe(build_id, inherited)
                    self.assertEqual(guide['selection']['errors'], [])
                    ids = set(guide['strategy_ids'])
                    self.assertTrue({3268, 3276, 3227, 3255, 3256, 3257}.issubset(ids))
                    self.assertFalse(ids.intersection({2403, 2405, 2409, 2482}))
                    self.assertNotIn(2482, guide['required_inherited'])

    def test_fire_builds_support_burning_with_a_damage_field_instead_of_detached_branches(self):
        for build_id in ('dash-burning', 'skill-fireball', 'skill-burning'):
            with self.subTest(build=build_id):
                guide = self.guides.describe(build_id)
                self.assertEqual(guide['selection']['errors'], [])
                ids = set(guide['strategy_ids'])
                self.assertTrue({2482, 2463, 2461, 3526, 3539}.issubset(ids))
                self.assertFalse(ids.intersection({3555, 3518, 3519, 3545, 2443, 2469, 2464}))
                self.assertIn(3539, guide['required_inherited'])

    def test_cold_builds_use_continuous_icicles_without_requiring_non_cold_targets(self):
        for build_id in ('lance-ice', 'skill-cold', 'skill-hail'):
            with self.subTest(build=build_id):
                guide = self.guides.describe(build_id)
                self.assertEqual(guide['selection']['errors'], [])
                ids = set(guide['strategy_ids'])
                self.assertTrue({2227, 2248, 2253, 2252, 2255}.issubset(ids))
                self.assertNotIn(2254, ids)
                self.assertIn(2252, guide['required_inherited'])
                if build_id == 'skill-hail':
                    self.assertTrue({2203, 2281}.issubset(ids))
                    self.assertFalse(ids.intersection({2274, 2287}))

    def test_poison_and_shadow_support_branches_feed_their_core_effects(self):
        cases = [('skill-lightning', {3337, 2175, 2124}, {2125}),
                 ('skill-shadow-spike', {3263, 3463}, {3262})]
        for build_id, core, detached in cases:
            with self.subTest(build=build_id):
                guide = self.guides.describe(build_id)
                self.assertEqual(guide['selection']['errors'], [])
                self.assertTrue(core.issubset(guide['strategy_ids']))
                self.assertFalse(detached.intersection(guide['strategy_ids']))


if __name__ == '__main__':
    unittest.main()
