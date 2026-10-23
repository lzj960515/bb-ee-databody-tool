"""创建继承用数据体的输入契约。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BodyRequest:
    character_id: int
    strategy_ids: tuple[int, int]
    qualities: tuple[int, int]
    body_quality: int = 3
