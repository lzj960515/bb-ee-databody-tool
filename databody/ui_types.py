"""主窗口和策略弹窗之间传递的选择结果。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategySelection:
    strategy_id: int
    quality: int
