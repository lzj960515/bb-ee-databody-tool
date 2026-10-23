"""流派目标、开局激活结果与局内获取路线。"""
from dataclasses import dataclass


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


@dataclass(frozen=True)
class RouteStep:
    strategy_id: int
    purpose: str


@dataclass(frozen=True)
class BuildPlan:
    build: BuildDefinition
    targets: tuple[int, ...]
    starting_ids: tuple[int, ...]
    activation: Activation
    steps: tuple[RouteStep, ...]
    errors: tuple[str, ...]
    notes: tuple[str, ...]
