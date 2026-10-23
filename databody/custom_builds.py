"""个人玩法文档校验与本地持久化，独立于游戏存档和内置模板。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from .custom_build_types import BodyDraft, CustomBuild, StrategySelection


def user_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "bb-ee-databody-tool"


class CustomBuildStore:
    def __init__(self, catalog: dict, *, directory: Path | None = None):
        self._path = (directory if directory is not None else user_data_directory()) / "custom-builds.json"
        self._characters = {row["id"] for row in catalog["characters"]}
        self._strategies = {row["id"]: row for row in catalog["strategies"]}

    def list_builds(self) -> list[CustomBuild]:
        if not self._path.exists():
            return []
        try:
            library = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as error:
            raise ValueError(f"个人玩法文件无法读取，原文件已保留：{self._path}") from error
        if (not isinstance(library, dict) or type(library.get("schema_version")) is not int
                or library["schema_version"] != 1 or not isinstance(library.get("builds"), list)):
            raise ValueError("个人玩法文件格式或版本不受支持，原文件已保留")
        builds = [self.validate(document) for document in library["builds"]]
        ids = [document["id"] for document in builds]
        if None in ids or len(set(ids)) != len(ids):
            raise ValueError("个人玩法文件包含缺失或重复的编号，原文件已保留")
        return builds

    def save(self, document: dict) -> CustomBuild:
        saved = self.validate(document)
        builds = self.list_builds()
        if saved["id"] is None:
            saved["id"] = uuid4().hex
            builds.append(saved)
        else:
            index = self._find_build(builds, saved["id"])
            builds[index] = saved
        self._write(builds)
        return saved

    def delete(self, build_id: str) -> str:
        builds = self.list_builds()
        index = self._find_build(builds, build_id)
        builds.pop(index)
        self._write(builds)
        return build_id

    def validate(self, document: dict, *, require_title: bool = True) -> CustomBuild:
        """草稿只校验可保存的结构；激活条件和冲突属于玩法规划。"""
        if not isinstance(document, dict):
            raise ValueError("玩法配置格式不正确")
        build_id = document.get("id")
        if build_id is not None and (not isinstance(build_id, str) or not build_id.strip()):
            raise ValueError("玩法编号格式不正确")
        title = document.get("title")
        if not isinstance(title, str) or (require_title and not title.strip()):
            raise ValueError("请为玩法填写名称")
        bodies = document.get("bodies")
        if not isinstance(bodies, list) or len(bodies) != 2:
            raise ValueError("玩法需要两个数据体配置")
        return {
            "id": build_id,
            "title": title.strip(),
            "target_ids": self._strategy_ids(document.get("target_ids")),
            "preferred_ids": self._strategy_ids(document.get("preferred_ids")),
            "required_inherited": self._strategy_ids(document.get("required_inherited")),
            "bodies": [self._body_draft(body) for body in bodies],
        }

    def _strategy_ids(self, values: list[int]) -> list[int]:
        if not isinstance(values, list) or any(
            type(value) is not int or value not in self._strategies for value in values
        ):
            raise ValueError("所选策略不在当前游戏配置中")
        return list(dict.fromkeys(values))

    def _body_draft(self, body: dict) -> BodyDraft:
        if not isinstance(body, dict):
            raise ValueError("数据体配置格式不正确")
        character_id = body.get("character_id")
        if character_id is not None and (type(character_id) is not int or character_id not in self._characters):
            raise ValueError("请选择有效的数据体角色")
        quality = body.get("body_quality")
        if type(quality) is not int or quality not in (3, 4):
            raise ValueError("数据体颜色请选择紫色或金色")
        slots = body.get("slots")
        if not isinstance(slots, list) or len(slots) != 2:
            raise ValueError("每个数据体需要两个继承策略位置")
        return {"character_id": character_id, "body_quality": quality,
                "slots": [self._strategy_selection(slot) for slot in slots]}

    def _strategy_selection(self, slot: dict | None) -> StrategySelection | None:
        if slot is None:
            return None
        if not isinstance(slot, dict):
            raise ValueError("继承策略配置格式不正确")
        strategy_id = slot.get("id")
        quality = slot.get("quality")
        if type(strategy_id) is not int or strategy_id not in self._strategies:
            raise ValueError("所选策略不在当前游戏配置中")
        if type(quality) is not int or quality not in self._strategies[strategy_id]["qualities"]:
            raise ValueError("所选策略品质不在当前游戏配置中")
        return {"id": strategy_id, "quality": quality}

    def _find_build(self, builds: list[CustomBuild], build_id: str) -> int:
        if not isinstance(build_id, str) or not build_id.strip():
            raise ValueError("玩法编号格式不正确")
        for index, document in enumerate(builds):
            if document["id"] == build_id:
                return index
        raise ValueError("该个人玩法已不存在，请重新载入")

    def _write(self, builds: list[CustomBuild]) -> None:
        library = {"schema_version": 1, "builds": builds}
        encoded = json.dumps(library, ensure_ascii=False, indent=2).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            # 与目标同目录完成替换；写入失败时保留上一份完整的个人玩法。
            with tempfile.NamedTemporaryFile(prefix=".custom-builds-", dir=self._path.parent, delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
