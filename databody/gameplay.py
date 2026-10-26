"""按玩家的最终目标和实际继承，生成同一份搭配图与局内路线。"""
from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations

from .planner import BuildPlanner, TRIGGER_NAMES
from .planner_types import BuildDefinition, RouteSearchExpired


class GameplayGuideService:
    def __init__(self, catalog: dict, rules: dict, knowledge: dict):
        self.planner = BuildPlanner(catalog, rules, knowledge)

    def list_builds(self) -> list[dict]:
        return [self._build_summary(build) for build in self.planner.builds]

    def strategy_positions(self) -> dict[int, list[str]]:
        """选择列表展示所有可选占有位，具体搭配仍按实际基础策略归位。"""
        candidates = tuple(self.planner.strategies)
        positions = {}
        for strategy_id in candidates:
            sources = set(self._trigger_sources(strategy_id, candidates))
            positions[strategy_id] = [label for trigger, label in TRIGGER_NAMES.items() if trigger in sources]
        return positions

    def describe(self, build_id: str, inherited_ids=()) -> dict:
        build = self.planner.build_by_id.get(build_id)
        if build is None:
            raise ValueError('请选择有效玩法')
        return self._describe(build, tuple(inherited_ids))

    def describe_owned(self, strategy_ids: list[int]) -> dict:
        # 单体是同一套目标规划；传给其他角色的两项策略不是本体的传入继承。
        return self.describe_custom({'target_ids': strategy_ids})

    def describe_custom(self, definition: dict, inherited_ids=()) -> dict:
        """自定义只提供目标与偏好，取得条件仍由游戏规则求解。"""
        targets = self._strategy_ids(definition.get('target_ids', []))
        preferred = self._strategy_ids(definition.get('preferred_ids', []))
        required = self._strategy_ids(definition.get('required_inherited', []))
        if not set(required).issubset(targets):
            raise ValueError('需继承的策略应包含在目标搭配中')
        build = BuildDefinition(
            id=definition.get('id') or 'custom', title=definition.get('title') or '未命名玩法',
            summary='', targets=targets, starters=preferred, required_inherited=required,
        )
        return self._describe(build, tuple(inherited_ids))

    def _strategy_ids(self, values) -> tuple[int, ...]:
        if not isinstance(values, (list, tuple)) or any(type(value) is not int for value in values):
            raise ValueError('请选择有效策略')
        ids = tuple(dict.fromkeys(values))
        self.planner.evaluate_start(ids)
        return ids

    def _describe(self, build: BuildDefinition, inherited: tuple[int, ...]) -> dict:
        activation = self.planner.evaluate_start(inherited)
        assumed = tuple(strategy_id for strategy_id in build.required_inherited if strategy_id not in inherited)
        errors = list(activation.conflicts)
        if len(inherited) > 4:
            errors.append('两个数据体最多继承四项策略')
        if len(inherited) + len(assumed) > 4:
            names = '、'.join(self.planner.name(strategy_id) for strategy_id in assumed)
            errors.append(f'这套玩法需继承{names}，请替换相应策略')
        # 特殊多红路线需要先继承、后激活。未选满时只预览条件，不代填用户的四槽。
        route_start = (*inherited, *assumed)
        goals = tuple(dict.fromkeys((*build.targets, *inherited)))
        route = None
        if not errors:
            try:
                route = self.planner.complete_route(goals, route_start, build.starters)
            except RouteSearchExpired:
                errors.append('搭配较复杂，暂未算完完整路线。可先选择继承策略，或减少目标后重试；玩法仍可保存。')
        if not errors and route is None:
            errors.extend(self._unreachable_reasons(goals, route_start))
        # 无解的草稿保留明确选择，帮助玩家修改；可行时图严格来自继承与实际取得路线。
        complete = tuple(dict.fromkeys((*route_start, *(route if route is not None else goals))))
        lanes, other = self._strategy_lanes(complete)
        suggestions = build.required_inherited or self.planner.recommend_start(build.targets, build.starters)
        return {
            **self._build_summary(build),
            'definition': {
                'target_ids': list(build.targets), 'preferred_ids': list(build.starters),
                'required_inherited': list(build.required_inherited),
            },
            'chain': list(build.chain),
            'lanes': lanes,
            'other_strategy_ids': other,
            'strategy_ids': list(complete),
            'suggested_ids': list(suggestions),
            'required_inherited': list(build.required_inherited),
            'assumed_inherited_ids': list(assumed),
            'optional_ids': [strategy_id for strategy_id in build.upgrades if strategy_id not in complete],
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

    def _unreachable_reasons(self, goals: tuple[int, ...], inherited: tuple[int, ...]) -> list[str]:
        # 只报告确定的基础位冲突。红策略可通过延后激活共存，不能套用继承合并互斥。
        bases = [strategy_id for strategy_id in dict.fromkeys((*goals, *inherited))
                 if self.planner.rules[strategy_id]['trigger_group']]
        reasons = []
        for left, right in combinations(bases, 2):
            a, b = self.planner.rules[left], self.planner.rules[right]
            names = f'“{self.planner.name(left)}”与“{self.planner.name(right)}”'
            if a['trigger_group'] == b['trigger_group']:
                reasons.append(names + f'占用同一个{TRIGGER_NAMES[a["trigger_group"]]}位置')
            elif a['faction'] == b['faction']:
                reasons.append(names + '属于同一派系的基础策略，请保留其中一项')
        if not reasons:
            names = '、'.join(self.planner.name(strategy_id) for strategy_id in goals)
            reasons.append(f'当前继承下无法同时取得并激活：{names}。请调整目标策略或继承选择')
        return reasons

    def _build_summary(self, build: BuildDefinition) -> dict:
        elements = []
        for strategy_id in (*build.starters, *build.targets):
            for category in self.planner.strategies[strategy_id]['category'].split(' / '):
                if category not in elements:
                    elements.append(category)
        return {'id': build.id, 'title': build.title, 'summary': build.summary, 'elements': elements}

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
        return next(self._trigger_sources(strategy_id, complete), 0)

    def _trigger_sources(self, strategy_id: int, complete: tuple[int, ...]) -> Iterator[int]:
        rule = self.planner.rules[strategy_id]
        if rule['trigger_group']:
            yield rule['trigger_group']
            return
        strategy = self.planner.strategies[strategy_id]
        if not strategy['true_pre']:
            return
        # 双重的首个激活前置表示触发源；输出派系不决定它归属哪个动作位。
        source_label = strategy['true_pre'][0]
        providers = [candidate for candidate in complete
                     if source_label in self.planner.strategies[candidate]['labels']
                     and self.planner.strategies[candidate]['gradation'] < strategy['gradation']]
        for candidate in providers:
            yield from self._trigger_sources(candidate, complete)

    def _route_step(self, strategy_id: int, build: BuildDefinition) -> dict:
        if strategy_id in build.targets:
            purpose = '目标策略'
        elif self.planner.rules[strategy_id]['trigger_group']:
            purpose = '基础触发'
        else:
            purpose = '补齐前置'
        return {'strategy_id': strategy_id, 'purpose': purpose}

    def _missing_requirements(self, missing: tuple, complete: tuple[int, ...]) -> list[dict]:
        requirements = []
        for strategy_id, labels in missing:
            required = []
            for label in labels:
                choices = sorted(self.planner.label_choices(label), key=lambda candidate: candidate not in complete)
                required.append({'label': label, 'choices': choices})
            requirements.append({'strategy_id': strategy_id, 'required': required})
        return requirements
