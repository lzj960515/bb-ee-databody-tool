"""把策略规则整理成稳定的最终搭配，以及玩家自己选择的继承路线。"""
from __future__ import annotations

from .planner import BuildPlanner, TRIGGER_NAMES
from .planner_types import BuildDefinition


class GameplayGuideService:
    def __init__(self, catalog: dict, rules: dict, knowledge: dict):
        self.planner = BuildPlanner(catalog, rules, knowledge)
        self._complete_builds: dict[str, tuple[int, ...]] = {}

    def list_builds(self) -> list[dict]:
        return [self._build_summary(build) for build in self.planner.builds]

    def describe(self, build_id: str, inherited_ids=()) -> dict:
        build = self.planner.build_by_id.get(build_id)
        if build is None:
            raise ValueError('请选择有效玩法')
        inherited = tuple(inherited_ids)
        activation = self.planner.evaluate_start(inherited)
        complete = self._complete_build(build)
        lanes, other = self._strategy_lanes(complete)
        errors = list(activation.conflicts)
        if len(inherited) > 4:
            errors.append('两个数据体最多继承四项策略')
        if any(strategy_id not in complete for strategy_id in inherited):
            errors.append('请从当前玩法中选择继承策略')
        missing_inherited = [strategy_id for strategy_id in build.required_inherited if strategy_id not in inherited]
        if len(inherited) == 4 and missing_inherited:
            names = '、'.join(self.planner.name(strategy_id) for strategy_id in missing_inherited)
            errors.append(f'这套玩法需继承{names}，请替换相应策略')
        # 未填满时可以先预览必须继承项带来的路线，但四个选择槽仍只保留用户自己选的内容。
        route_start = tuple(dict.fromkeys((*inherited, *missing_inherited)))
        required = tuple(dict.fromkeys((*build.targets, *build.upgrades, *inherited)))
        route = None if errors or len(route_start) > 4 else self.planner.complete_route(required, route_start, complete)
        if not errors and route is None and len(route_start) <= 4:
            errors.append('当前继承搭配无法补齐这套玩法，请调整继承策略')
        suggested = build.required_inherited or self.planner.recommend_start(build.targets, build.starters or complete)
        return {
            **self._build_summary(build),
            'chain': list(build.chain),
            'lanes': lanes,
            'other_strategy_ids': other,
            'strategy_ids': list(complete),
            'suggested_ids': [strategy_id for strategy_id in suggested if strategy_id in complete],
            'required_inherited': list(build.required_inherited),
            'steps': [self._route_step(strategy_id, build) for strategy_id in route or ()],
            'notes': list(build.notes),
            'selection': {
                'inherited_ids': list(inherited),
                'active_ids': list(activation.active_ids),
                'missing': self._missing_requirements(activation.missing_labels, complete),
                'conflicts': list(activation.conflicts),
                'errors': list(dict.fromkeys(errors)),
            },
        }

    def _build_summary(self, build: BuildDefinition) -> dict:
        elements = []
        for strategy_id in (*build.starters, *build.targets):
            for category in self.planner.strategies[strategy_id]['category'].split(' / '):
                if category not in elements:
                    elements.append(category)
        return {'id': build.id, 'title': build.title, 'summary': build.summary, 'elements': elements}

    def _complete_build(self, build: BuildDefinition) -> tuple[int, ...]:
        if build.id not in self._complete_builds:
            # 完整玩法包含普通获取需要的前置；继承可以省去获取步骤，但不改变最终搭配图。
            inherited = build.required_inherited
            required = tuple(dict.fromkeys((*build.targets, *build.upgrades))) if inherited else tuple(
                dict.fromkeys((*build.starters, *build.targets, *build.upgrades)))
            route = self.planner.complete_route(required, inherited, (*build.starters, *build.upgrades))
            if route is None:
                raise ValueError(f'“{build.title}”的完整搭配无法按当前规则取得')
            self._complete_builds[build.id] = (*inherited, *route)
        return self._complete_builds[build.id]

    def _strategy_lanes(self, complete: tuple[int, ...]) -> tuple[list[dict], list[int]]:
        lanes = {trigger: [] for trigger in TRIGGER_NAMES}
        other = []
        for strategy_id in complete:
            trigger = self._trigger_source(strategy_id, complete)
            (lanes[trigger] if trigger else other).append(strategy_id)
        for strategies in lanes.values():
            strategies.sort(key=lambda strategy_id: self.planner.strategies[strategy_id]['gradation'])
        return ([{'trigger': trigger, 'label': label, 'strategies': lanes[trigger]}
                 for trigger, label in TRIGGER_NAMES.items()], other)

    def _trigger_source(self, strategy_id: int, complete: tuple[int, ...]) -> int:
        rule = self.planner.rules[strategy_id]
        if rule['trigger_group']:
            return rule['trigger_group']
        strategy = self.planner.strategies[strategy_id]
        if not strategy['true_pre']:
            return 0
        # 双重的首个激活前置表示触发源；输出派系并不决定它归属哪个动作位。
        source_label = strategy['true_pre'][0]
        providers = [candidate for candidate in complete
                     if source_label in self.planner.strategies[candidate]['labels']
                     and self.planner.strategies[candidate]['gradation'] < strategy['gradation']]
        for candidate in providers:
            trigger = self._trigger_source(candidate, complete)
            if trigger:
                return trigger
        return 0

    def _route_step(self, strategy_id: int, build: BuildDefinition) -> dict:
        if strategy_id in build.targets:
            purpose = '核心效果'
        elif self.planner.rules[strategy_id]['trigger_group']:
            purpose = '基础触发'
        elif strategy_id in build.upgrades:
            purpose = '后续强化'
        else:
            purpose = '补齐前置'
        return {'strategy_id': strategy_id, 'purpose': purpose}

    def _missing_requirements(self, missing: tuple, complete: tuple[int, ...]) -> list[dict]:
        requirements = []
        for strategy_id, labels in missing:
            required = []
            for label in labels:
                choices = [candidate for candidate in complete
                           if label in self.planner.strategies[candidate]['labels']]
                required.append({'label': label, 'choices': choices})
            requirements.append({'strategy_id': strategy_id, 'required': required})
        return requirements
