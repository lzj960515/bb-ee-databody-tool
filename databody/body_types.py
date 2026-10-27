"""数据体的角色、潜能、自身策略和传出继承策略。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BodyStrategy:
    id: int
    quality: int


@dataclass(frozen=True)
class BodyInheritance:
    character_id: int
    skill_id: int


@dataclass(frozen=True)
class BodyAttribute:
    type: int
    value: float


@dataclass(frozen=True)
class BodyTalent:
    id: int
    quality: int
    inherit_num: int = 0
    from_actor_id: int = 0


@dataclass(frozen=True)
class BodySkill:
    id: int
    from_actor_id: int
    level: int = 1


@dataclass(frozen=True)
class BodyRequest:
    character_id: int
    strategy_ids: tuple[int, int]
    qualities: tuple[int, int]
    body_quality: int = 3
    owned_strategies: tuple[BodyStrategy, ...] | None = None
    full_potentials: bool = False
    max_hp: int | None = None
    max_mp: int | None = None
    inheritances: tuple[BodyInheritance, ...] = ()


@dataclass(frozen=True)
class BodyContent:
    owned_strategies: tuple[BodyStrategy, ...]
    active_strategy_ids: frozenset[int]
    potential_ids: tuple[int, ...]
    attributes: tuple[BodyAttribute, ...] | None = None
    talents: tuple[BodyTalent, ...] | None = None
    skills: tuple[BodySkill, ...] = ()
