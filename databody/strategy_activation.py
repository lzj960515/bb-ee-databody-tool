"""游戏按四层扫描策略标签；继承用truePre，自身普通策略用preLabels。"""
from .planner_types import Activation


def activate_strategies(strategies: dict[int, dict], inherited: tuple[int, ...],
                        acquired: tuple[int, ...]) -> Activation:
    labels: set[int] = set()
    active, missing = [], []
    rows = [(strategy_id, True) for strategy_id in inherited]
    rows.extend((strategy_id, False) for strategy_id in acquired)
    rows.sort(key=lambda row: strategies[row[0]]['gradation'])
    for strategy_id, is_inherited in rows:
        strategy = strategies[strategy_id]
        requirements = strategy['true_pre'] if is_inherited else strategy['pre_labels']
        absent = tuple(label for label in requirements if label not in labels)
        if absent:
            missing.append((strategy_id, absent))
        else:
            active.append(strategy_id)
            labels.update(strategy['labels'])
    return Activation(tuple(active), frozenset(labels), tuple(missing), ())
