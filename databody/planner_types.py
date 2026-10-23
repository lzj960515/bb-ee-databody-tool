"""流派目标、开局激活结果与局内获取路线。"""
from dataclasses import dataclass


class RouteSearchExpired(RuntimeError):
    """交互时间内尚未穷尽路线，不表示目标无解。"""


@dataclass(frozen=True)
class BuildDefinition:
    id: str
    title: str
    summary: str
    targets: tuple[int, ...]
    starters: tuple[int, ...] = ()
    chain: tuple[str, ...] = ()
    upgrades: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()
    required_inherited: tuple[int, ...] = ()


@dataclass(frozen=True)
class Activation:
    active_ids: tuple[int, ...]
    labels: frozenset[int]
    missing_labels: tuple[tuple[int, tuple[int, ...]], ...]
    conflicts: tuple[str, ...]
