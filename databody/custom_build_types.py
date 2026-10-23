"""本地个人玩法与尚未完成的继承配置。"""
from typing import TypedDict


class StrategySelection(TypedDict):
    id: int
    quality: int


class BodyDraft(TypedDict):
    character_id: int | None
    body_quality: int
    slots: list[StrategySelection | None]


class CustomBuild(TypedDict):
    id: str | None
    title: str
    target_ids: list[int]
    preferred_ids: list[int]
    required_inherited: list[int]
    bodies: list[BodyDraft]
