"""本地网页的桌面边界：选择存档、返回玩法资料和执行存档事务。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .body_types import BodyRequest
from .custom_builds import CustomBuildStore
from .planner import BuildPlanner
from .service import DataBodyService, application_directory


class DesktopAPI:
    def __init__(self, service: DataBodyService | None = None, *, resource_directory: Path | None = None,
                 user_data_directory: Path | None = None):
        self._service = service or DataBodyService()
        self._resources = resource_directory or application_directory()
        self._custom_builds = CustomBuildStore(self._service.catalog, directory=user_data_directory)
        self._window = None
        self._selected_path: Path | None = None
        self._current_save: dict | None = None
        self._guides = None
        # pywebview 在独立线程调用每个 API；载入切换与写入必须按同一顺序执行。
        self._operation_lock = threading.RLock()

    def get_initial_data(self) -> dict:
        return self._respond(self._get_initial_data)

    def list_builds(self) -> dict:
        return self._respond(self._list_builds)

    def describe_build(self, build_id: str, inherited_ids: list[int] | None = None) -> dict:
        return self._respond(self._describe_build, build_id, inherited_ids)

    def list_custom_builds(self) -> dict:
        return self._respond_serialized(self._custom_builds.list_builds)

    def save_custom_build(self, document: dict) -> dict:
        return self._respond_serialized(self._custom_builds.save, document)

    def delete_custom_build(self, build_id: str) -> dict:
        return self._respond_serialized(self._custom_builds.delete, build_id)

    def describe_custom_build(self, document: dict) -> dict:
        return self._respond(self._describe_custom_build, document)

    def discover_saves(self) -> dict:
        return self._respond(self._service.discover_saves)

    def load_save(self, path: str) -> dict:
        return self._respond_serialized(self._load_save, path)

    def browse_save(self) -> dict:
        return self._respond_serialized(self._browse_save)

    def save_bodies(self, requests: list[dict]) -> dict:
        return self._respond_serialized(self._save_bodies, requests)

    def restore_backup(self) -> dict:
        return self._respond_serialized(self._restore_backup)

    def _respond(self, operation, *args) -> dict:
        try:
            return {"ok": True, "data": operation(*args)}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def _respond_serialized(self, operation, *args) -> dict:
        # 文件读写和游戏存档切换保持串行；只读规划不持此锁，避免阻塞草稿保存。
        with self._operation_lock:
            return self._respond(operation, *args)

    def _get_initial_data(self) -> dict:
        data = self._read_initial_data()
        data["strategy_positions"] = self._get_guides().strategy_positions()
        return data

    def _read_initial_data(self) -> dict:
        rules = self._read_data("planner_rules.json")
        knowledge = self._read_data("builds.json")
        return {"catalog": self._service.catalog, "rules": rules, "knowledge": knowledge}

    def _read_data(self, filename: str) -> dict:
        return json.loads((self._resources / "data" / filename).read_text(encoding="utf-8"))

    def _get_guides(self):
        with self._operation_lock:
            if self._guides is None:
                from .gameplay import GameplayGuideService

                data = self._read_initial_data()
                self._guides = GameplayGuideService(data["catalog"], data["rules"], data["knowledge"])
        return self._guides

    def _list_builds(self) -> list[dict]:
        return self._get_guides().list_builds()

    def _describe_build(self, build_id: str, inherited_ids: list[int] | None) -> dict:
        inherited = [] if inherited_ids is None else inherited_ids
        if not isinstance(build_id, str) or not isinstance(inherited, list):
            raise ValueError("玩法或继承策略格式不正确")
        if any(type(strategy_id) is not int for strategy_id in inherited):
            raise ValueError("请选择有效策略")
        return self._get_guides().describe(build_id, inherited)

    def _describe_custom_build(self, document: dict) -> dict:
        definition = self._custom_builds.validate(document, require_title=False)
        inherited = [slot["id"] for body in definition["bodies"] for slot in body["slots"] if slot is not None]
        return self._get_guides().describe_custom(definition, inherited)

    def _load_save(self, path: str) -> dict:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("请选择要载入的存档")
        self._selected_path = Path(path).resolve()
        self._current_save = None
        # 解析失败仍保留所选目标，便于用该槽的备份恢复损坏存档。
        saved = self._service.load_save(self._selected_path)
        self._current_save = saved
        return saved

    def _browse_save(self) -> dict | None:
        window = self._require_window()
        directory = self._selected_path.parent if self._selected_path else Path.home()
        files = window.create_file_dialog(directory=str(directory), allow_multiple=False,
                                          file_types=("游戏存档 (*.*)",))
        return self._load_save(files[0]) if files else None

    def _save_bodies(self, requests: list[dict]) -> dict:
        if self._current_save is None or self._selected_path is None:
            raise ValueError("请先载入目标存档")
        if not isinstance(requests, list) or len(requests) not in (1, 2):
            raise ValueError("每次请选择一个或两个数据体")
        bodies = [self._body_request(request) for request in requests]
        if len(bodies) == 2:
            self._validate_pair(bodies)
        result = self._service.add_bodies(self._selected_path, bodies)
        return self._saved_result(result)

    def _body_request(self, request: dict) -> BodyRequest:
        if not isinstance(request, dict):
            raise ValueError("数据体配置格式不正确")
        character_id = request.get("character_id")
        strategy_ids = request.get("strategy_ids")
        qualities = request.get("qualities")
        body_quality = request.get("body_quality", 3)
        if type(character_id) is not int or type(body_quality) is not int:
            raise ValueError("请选择数据体角色和颜色")
        if not isinstance(strategy_ids, list) or not isinstance(qualities, list):
            raise ValueError("请为每个数据体选择两项策略")
        if len(strategy_ids) != 2 or len(qualities) != 2:
            raise ValueError("请为每个数据体选择两项策略")
        if any(type(value) is not int for value in [*strategy_ids, *qualities]):
            raise ValueError("请选择有效策略和品质")
        return BodyRequest(character_id, tuple(strategy_ids), tuple(qualities), body_quality)

    def _validate_pair(self, bodies: list[BodyRequest]) -> None:
        if bodies[0].character_id == bodies[1].character_id:
            raise ValueError("两个数据体请选择不同角色")
        data = self._read_initial_data()
        planner = BuildPlanner(data["catalog"], data["rules"], data["knowledge"])
        strategy_ids = tuple(strategy_id for body in bodies for strategy_id in body.strategy_ids)
        activation = planner.evaluate_start(strategy_ids)
        if activation.conflicts:
            raise ValueError("；".join(activation.conflicts))

    def _restore_backup(self) -> dict | None:
        if self._selected_path is None:
            raise ValueError("请先选择要恢复的目标存档")
        window = self._require_window()
        directory = self._selected_path.parent.parent / "DataBodyToolBackups"
        files = window.create_file_dialog(directory=str(directory), allow_multiple=False,
                                          file_types=("数据体工具备份 (*.bak)",))
        if not files:
            return None
        backup_path = files[0]
        confirmed = window.create_confirmation_dialog(
            "恢复备份", f"将以下备份恢复到当前存档：\n{backup_path}\n\n目标：{self._selected_path}\n\n"
            "恢复前会备份当前存档。是否继续？",
        )
        if not confirmed:
            return None
        result = self._service.restore_backup(self._selected_path, backup_path)
        return self._saved_result(result)

    def _saved_result(self, result: dict) -> dict:
        # 写入已提交，刷新失败仍需明确报告保存成功，避免用户重试而重复添加。
        try:
            saved = self._load_save(str(self._selected_path))
        except Exception as error:
            return {**result, "save": None, "warning": f"保存已完成，但重新读取失败：{error}。请重新载入存档。"}
        return {**result, "save": saved}

    def _require_window(self):
        if self._window is None:
            raise ValueError("桌面窗口尚未准备好")
        return self._window
