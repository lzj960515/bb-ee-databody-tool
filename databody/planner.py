"""依据游戏标签与默认互斥规则规划继承开局和局内路线。

继承策略使用 truePre，普通获得的策略使用 preLabels。策略标签保持原值，
双重策略产生的 IV 级标签不能代替同派系的 I 级基础策略。
"""
from __future__ import annotations

from itertools import combinations

from .planner_types import Activation, BuildDefinition, BuildPlan, RouteStep


TRIGGER_NAMES = {1: '普攻', 2: '技能', 3: '冲刺', 4: '传承技', 5: '召唤'}


class BuildPlanner:
    def __init__(self, catalog: dict, rules: dict, knowledge: dict):
        self.strategies = {row['id']: row for row in catalog['strategies']}
        self.rules = {row['id']: row for row in rules['strategies']}
        if self.strategies.keys() != self.rules.keys():
            raise ValueError('策略目录与规划规则版本不一致')
        self.providers: dict[int, list[int]] = {}
        for strategy in self.strategies.values():
            for label in strategy['labels']:
                self.providers.setdefault(label, []).append(strategy['id'])
        self.builds = self._build_definitions(knowledge)
        self.build_by_id = {build.id: build for build in self.builds}
        self._recommended: dict[tuple[tuple[int, ...], tuple[int, ...]], tuple[int, ...]] = {}

    def _build_definitions(self, knowledge: dict) -> tuple[BuildDefinition, ...]:
        builds = []
        for row in knowledge['builds']:
            builds.append(BuildDefinition(
                id=row['id'], title=row['title'], summary=row['summary'], targets=tuple(row['targets']),
                starters=tuple(row.get('starters', [])), chain=tuple(row.get('chain', [])),
                upgrades=tuple(row.get('upgrades', [])), notes=tuple(row.get('notes', [])),
                required_inherited=tuple(row.get('required_inherited', [])),
            ))
        for strategy in self.strategies.values():
            if strategy['is_combined']:
                builds.append(BuildDefinition(
                    f"strategy-{strategy['id']}", strategy['name'], strategy['description'],
                    (strategy['id'],),
                ))
        return tuple(builds)

    def name(self, strategy_id: int) -> str:
        return self.strategies[strategy_id]['name']

    def label_choices(self, label: int) -> tuple[int, ...]:
        return tuple(self.providers.get(label, ()))

    def _conflict(self, left: int, right: int) -> str | None:
        a, b = self.strategies[left], self.strategies[right]
        ra, rb = self.rules[left], self.rules[right]
        names = f'“{a["name"]}”与“{b["name"]}”'
        if left == right:
            return names + '重复，继承时会合并'
        if ra['trigger_group'] and ra['trigger_group'] == rb['trigger_group']:
            return names + f'占用同一个{TRIGGER_NAMES[ra["trigger_group"]]}触发位'
        if a['gradation'] == b['gradation'] < 4 and ra['faction'] == rb['faction']:
            return names + '是同派系同层策略，默认契约下只能保留一个'
        if (ra['second_faction'] and rb['second_faction']
                and a['true_pre'][:1] == b['true_pre'][:1]):
            return names + '使用同一双重策略触发前置，默认规则下不能同时保留'
        return None

    def _conflicts(self, ids: tuple[int, ...]) -> tuple[str, ...]:
        return tuple(reason for a, b in combinations(ids, 2) if (reason := self._conflict(a, b)))

    def evaluate_start(self, starting_ids: tuple[int, ...]) -> Activation:
        self._validate_ids(starting_ids)
        return self._activate(starting_ids, ())

    def _activate(self, inherited: tuple[int, ...], acquired: tuple[int, ...]) -> Activation:
        labels: set[int] = set()
        active, missing = [], []
        # 保留同层顺序，与游戏的四层扫描一致；不做虚构的标签降级或循环补全。
        rows = [(strategy_id, True) for strategy_id in inherited]
        rows.extend((strategy_id, False) for strategy_id in acquired)
        rows.sort(key=lambda row: self.strategies[row[0]]['gradation'])
        for strategy_id, is_inherited in rows:
            strategy = self.strategies[strategy_id]
            requirements = strategy['true_pre'] if is_inherited else strategy['pre_labels']
            absent = tuple(label for label in requirements if label not in labels)
            if absent:
                missing.append((strategy_id, absent))
            else:
                active.append(strategy_id)
                labels.update(strategy['labels'])
        return Activation(tuple(active), frozenset(labels), tuple(missing), self._conflicts(inherited))

    def _validate_ids(self, ids: tuple[int, ...]) -> None:
        if any(strategy_id not in self.strategies for strategy_id in ids):
            raise ValueError('路线含当前目录不存在的策略')

    def _candidate_key(self, strategy_id: int, preferred: tuple[int, ...]) -> tuple:
        strategy = self.strategies[strategy_id]
        preference = preferred.index(strategy_id) if strategy_id in preferred else len(preferred)
        # 基础动作优先于受击、闪避一类附加触发；同等选择保持目录顺序稳定。
        reactive = any(word in strategy['name'] for word in ('受击', '闪避'))
        return preference, reactive, strategy['gradation'], strategy_id

    def _inherit_bundles(self, required: tuple[int, ...], preferred: tuple[int, ...]):
        if len(required) > 4 or self._conflicts(required):
            return
        activation = self.evaluate_start(required)
        if not activation.missing_labels:
            yield required
            return
        strategy_id, missing = activation.missing_labels[0]
        candidates = sorted(self.providers.get(missing[0], ()), key=lambda c: self._candidate_key(c, preferred))
        for candidate in candidates:
            if candidate in required or self.strategies[candidate]['gradation'] >= self.strategies[strategy_id]['gradation']:
                continue
            yield from self._inherit_bundles((*required, candidate), preferred)

    def recommend_start(self, targets: tuple[int, ...], preferred: tuple[int, ...] = ()) -> tuple[int, ...]:
        if preferred and len(preferred) == 4:
            activation = self.evaluate_start(preferred)
            if not activation.conflicts and len(activation.active_ids) == 4 and set(targets).issubset(preferred):
                return preferred
        cache_key = targets, preferred
        if cache_key in self._recommended:
            return self._recommended[cache_key]
        # 先整体求解，允许为后一个目标回溯调整前一个目标的基础触发位。
        chosen = next(self._inherit_bundles(targets, preferred), ())
        for target in (() if chosen else targets):
            options = self._inherit_bundles((*chosen, target), preferred) if target not in chosen else iter((chosen,))
            bundle = next(options, None)
            if bundle is not None:
                chosen = bundle
        relevant = {self.rules[c]['faction'] for c in (*targets, *chosen)}
        relevant.update(self.rules[c]['second_faction'] for c in targets)
        candidates = [c for c in self.strategies if self.rules[c]['faction'] in relevant and not self.strategies[c]['is_combined']]
        candidates.sort(key=lambda c: (c not in preferred, -self.strategies[c]['gradation'],
                                       self._candidate_key(c, preferred)))
        for candidate in candidates:
            if len(chosen) == 4:
                break
            if candidate not in chosen:
                bundle = next(self._inherit_bundles((*chosen, candidate), preferred), None)
                if bundle is not None:
                    chosen = bundle
        # 显示与保存顺序统一：先基础动作，再强化，再双重。
        chosen = tuple(sorted(chosen, key=lambda c: self.strategies[c]['gradation']))
        self._recommended[cache_key] = chosen
        return chosen

    def can_draw(self, strategy_id: int, inherited: tuple[int, ...], acquired: tuple[int, ...]) -> bool:
        obtained = (*inherited, *acquired)
        if strategy_id in obtained:
            return False
        strategy, rule = self.strategies[strategy_id], self.rules[strategy_id]
        activation = self._activate(inherited, tuple(acquired))
        active = set(activation.active_ids)
        if not set(strategy['pre_labels']).issubset(activation.labels):
            return False
        if self._draw_blocked(strategy_id, obtained, active):
            return False
        progress = self._faction_progress(rule['faction'], obtained, active)
        if strategy['gradation'] == 1:
            return progress == 0
        # 普通抽取需本派系基础入口；继承红色本身并不开放其所属派系。
        active_factions = {self.rules[c]['faction'] for c in active if self.rules[c]['trigger_group']}
        if rule['faction'] not in active_factions:
            return False
        if strategy['gradation'] < 4 and strategy['gradation'] <= progress:
            return False
        if strategy['gradation'] == 4 and rule['second_faction'] not in active_factions:
            return False
        return True

    def _draw_blocked(self, candidate: int, obtained: tuple[int, ...], active: set[int]) -> bool:
        rule, strategy = self.rules[candidate], self.strategies[candidate]
        for other in obtained:
            if rule['trigger_group'] and rule['trigger_group'] == self.rules[other]['trigger_group']:
                return True
            if (strategy['gradation'] == self.strategies[other]['gradation'] == 4 and other in active
                    and strategy['true_pre'][:1] == self.strategies[other]['true_pre'][:1]):
                return True
        return False

    def _faction_progress(self, faction: int, obtained: tuple[int, ...], active: set[int]) -> int:
        progress = 0
        for grade in range(1, 5):
            same_tier = [c for c in obtained if self.rules[c]['faction'] == faction
                         and self.strategies[c]['gradation'] == grade]
            if not any(c in active for c in same_tier):
                break
            progress = grade
        return progress

    def _obtain_options(self, strategy_id: int, inherited: tuple[int, ...], acquired: tuple[int, ...],
                        visiting: frozenset[int] = frozenset(), preferred: tuple[int, ...] = ()):
        if strategy_id in visiting:
            return
        current = self._activate(inherited, acquired)
        if strategy_id in current.active_ids:
            yield acquired
            return
        obtained = (*inherited, *acquired)
        if strategy_id not in obtained and self._draw_blocked(strategy_id, obtained, set(current.active_ids)):
            return
        strategy, rule = self.strategies[strategy_id], self.rules[strategy_id]
        requirements = list(strategy['true_pre'] if strategy_id in inherited else strategy['pre_labels'])
        if strategy_id not in inherited and strategy['gradation'] > 1:
            factions = [rule['faction']]
            if strategy['gradation'] == 4:
                factions.append(rule['second_faction'])
            active_factions = {self.rules[c]['faction'] for c in current.active_ids if self.rules[c]['trigger_group']}
            for faction in factions:
                if faction not in active_factions:
                    # 基础派系标签不由 faction*10 推导，直接从实际 I 级配置中选择。
                    bases = [c for c in self.strategies if self.rules[c]['faction'] == faction
                             and self.strategies[c]['gradation'] == 1]
                    for base in sorted(bases, key=lambda c: self._candidate_key(c, preferred)):
                        for state in self._obtain_options(base, inherited, acquired, visiting | {strategy_id}, preferred):
                            yield from self._obtain_options(strategy_id, inherited, state, visiting, preferred)
                    return
        missing = [label for label in requirements if label not in current.labels]
        if missing:
            candidates = sorted(self.providers.get(missing[0], ()), key=lambda c: self._candidate_key(c, preferred))
            for candidate in candidates:
                for state in self._obtain_options(candidate, inherited, acquired, visiting | {strategy_id}, preferred):
                    yield from self._obtain_options(strategy_id, inherited, state, visiting, preferred)
            return
        if strategy_id in inherited:
            yield acquired
        elif self.can_draw(strategy_id, inherited, acquired):
            yield (*acquired, strategy_id)

    def _growth_targets(self, inherited: tuple[int, ...]) -> tuple[int, ...]:
        active = self.evaluate_start(inherited).active_ids
        factions = {self.rules[c]['faction'] for c in active if self.rules[c]['trigger_group']}
        return tuple(c for c in self.strategies if self.strategies[c]['gradation'] == 3
                     and self.rules[c]['faction'] in factions)

    def complete_route(self, required: tuple[int, ...], inherited: tuple[int, ...],
                       preferred: tuple[int, ...] = ()) -> tuple[int, ...] | None:
        """补齐整套目标；后续目标受阻时回溯前面的基础触发位选择。"""
        self._validate_ids((*required, *inherited))
        if self._conflicts(inherited):
            return None
        return next(self._route_options(required, inherited, (), preferred), None)

    def _route_options(self, remaining: tuple[int, ...], inherited: tuple[int, ...],
                       acquired: tuple[int, ...], preferred: tuple[int, ...]):
        if not remaining:
            yield acquired
            return
        for state in self._obtain_options(remaining[0], inherited, acquired, preferred=preferred):
            yield from self._route_options(remaining[1:], inherited, state, preferred)

    def plan(self, build_id: str, *, starting_ids: tuple[int, ...] | None = None,
             targets: tuple[int, ...] | None = None) -> BuildPlan:
        build = self.build_by_id[build_id]
        goals = tuple(dict.fromkeys(targets if targets is not None else build.targets))
        self._validate_ids(goals)
        if starting_ids is None:
            starters = build.required_inherited or self.recommend_start(goals, build.starters)
        else:
            starters = tuple(starting_ids)
        activation = self.evaluate_start(starters)
        errors = list(activation.conflicts)
        if len(starters) > 4:
            errors.append('两个数据体最多继承四项策略')
        steps: list[RouteStep] = []
        acquired: tuple[int, ...] = ()
        if not errors:
            required = tuple(dict.fromkeys((*goals, *(c for c, _ in activation.missing_labels))))
            route = self.complete_route(required, starters, build.starters)
            if route is None:
                errors.append('当前继承搭配无法补齐这套玩法，请调整继承策略')
            else:
                acquired = route
                steps.extend(RouteStep(c, '补齐成型') for c in acquired)
            growth = build.upgrades or self._growth_targets(starters)
            for goal in growth:
                route = next(self._obtain_options(goal, starters, acquired, preferred=build.starters), None)
                if route is not None:
                    steps.extend(RouteStep(c, '后续强化') for c in route[len(acquired):])
                    acquired = route
        return BuildPlan(build, goals, starters, activation, tuple(steps),
                         tuple(dict.fromkeys(errors)), build.notes)
