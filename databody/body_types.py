"""数据体的角色、潜能、自身策略和传出继承策略。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BodyStrategy:
    id: int
    quality: int


@dataclass(frozen=True)
class BodyRequest:
    character_id: int
    strategy_ids: tuple[int, int]
    qualities: tuple[int, int]
    body_quality: int = 3
    owned_strategies: tuple[BodyStrategy, ...] | None = None
    full_potentials: bool = False


@dataclass(frozen=True)
class BodyContent:
    owned_strategies: tuple[BodyStrategy, ...]
    active_strategy_ids: frozenset[int]
    potential_ids: tuple[int, ...]
