"""桌面工具的存档工作流：读取、校验、备份、原子替换及恢复。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .bodies import append_body, body_entries, capacity, double_value, nested, pack_from_save
from .body_types import BodyRequest
from .save_codec import SaveDocument


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def application_directory() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


class DataBodyService:
    def __init__(self, catalog_path: Path | None = None):
        catalog_path = catalog_path or application_directory() / "data" / "catalog.json"
        self.catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        self.characters = {row["id"]: row for row in self.catalog["characters"]}
        self.strategies = {row["id"]: row for row in self.catalog["strategies"]}
        self.loaded_digests: dict[Path, str] = {}

    def game_running(self) -> bool:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq BlazblueEntropyEffect.exe", "/FO", "CSV", "/NH"],
            capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return b'"blazblueentropyeffect.exe"' in result.stdout.lower()

    def discover_saves(self) -> list[dict]:
        root = Path.home() / "AppData" / "LocalLow" / "91Act" / "BlazBlueEntropyEffect" / "Steam"
        saves = []
        for path in root.glob("*/Save/*"):
            if not path.is_file() or not path.name.isdecimal():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            account = path.parent.parent.name
            label = f"槽 {path.name} · {modified:%Y-%m-%d %H:%M} · 账号尾号 {account[-4:]}"
            saves.append({"path": str(path), "label": label, "modified": path.stat().st_mtime})
        return sorted(saves, key=lambda row: row["modified"], reverse=True)

    def load_save(self, path: str | Path) -> dict:
        path = Path(path).resolve()
        raw = path.read_bytes()
        # 记录用户选中的文件，即使解析失败，也允许用该槽的有效备份恢复。
        self.loaded_digests[path] = digest(raw)
        document = SaveDocument.from_compressed(raw)
        _, pack = pack_from_save(document)
        bodies = []
        for uid, body in body_entries(pack):
            character_id = body.get_varint(2)
            strategies = []
            for field in body.fields(30):
                blessing = nested(field)
                strategy_id = blessing.get_varint(1)
                name = self.strategies.get(strategy_id, {}).get("name", f"策略 {strategy_id}")
                strategies.append(f"{name}（品质 {blessing.get_varint(2)}）")
            bodies.append({"uid": uid, "character_name": self.characters.get(character_id, {}).get("name", f"角色 {character_id}"), "strategies": strategies})
        return {"path": str(path), "bodies": bodies, "count": len(bodies), "capacity": capacity(pack, self.catalog["rules"])}

    def _current_save(self, path: Path) -> bytes:
        if self.game_running():
            raise ValueError("请完全退出游戏后再保存或恢复，避免游戏覆盖存档")
        if path not in self.loaded_digests:
            raise ValueError("请先载入目标存档")
        raw = path.read_bytes()
        if digest(raw) != self.loaded_digests[path]:
            raise ValueError("存档已发生变化，请重新载入后再操作")
        return raw

    def _validate_selection(self, character_id: int, strategy_ids: Sequence[int], qualities: Sequence[int]) -> dict:
        if character_id not in self.characters:
            raise ValueError("请选择有效角色")
        if len(strategy_ids) != 2 or len(qualities) != 2 or len(set(strategy_ids)) != 2:
            raise ValueError("请选择两项不同的策略；重复策略在游戏中不会叠加")
        for strategy_id, quality in zip(strategy_ids, qualities):
            strategy = self.strategies.get(strategy_id)
            if not strategy or quality not in strategy["qualities"]:
                raise ValueError("所选策略或品质不在当前游戏配置中")
        return self.characters[character_id]

    def _score_for_body_color(self, quality: int) -> int:
        for color in self.catalog["rules"]["body_colors"]:
            if color["quality"] == quality:
                return color["score"]
        raise ValueError("请选择有效的数据体颜色")

    def add_body(self, path: str | Path, character_id: int, strategy_ids: list[int], qualities: list[int],
                 *, body_quality: int = 3) -> dict:
        request = BodyRequest(character_id, tuple(strategy_ids), tuple(qualities), body_quality)
        result = self.add_bodies(path, [request])
        return {"uid": result["uids"][0], "backup_path": result["backup_path"], "count": result["count"]}

    def add_bodies(self, path: str | Path, requests: list[BodyRequest]) -> dict:
        """整批校验后一次保存；任一请求失败时不会写入部分数据体。"""
        path = Path(path).resolve()
        if not requests:
            raise ValueError("请至少选择一个要添加的数据体")
        scores = []
        for request in requests:
            self._validate_selection(request.character_id, request.strategy_ids, request.qualities)
            scores.append(self._score_for_body_color(request.body_quality))
        original = self._current_save(path)
        document = SaveDocument.from_compressed(original)
        self._validate_batch_limits(document, len(requests))
        uids = []
        for request, score in zip(requests, scores):
            character = self.characters[request.character_id]
            uid = append_body(document, character, request.strategy_ids, request.qualities,
                              self.catalog["rules"], score=score)
            uids.append(uid)
        updated = document.to_compressed()
        count = self._verify_created_bodies(updated, requests, uids, scores)
        backup = self._commit(path, original, updated)
        return {"uids": uids, "backup_path": str(backup), "count": count}

    def _validate_batch_limits(self, document: SaveDocument, count: int) -> None:
        _, pack = pack_from_save(document)
        entries = body_entries(pack)
        available = capacity(pack, self.catalog["rules"]) - len(entries)
        # 新增评分可能解锁后续仓库页；整批仍以操作前已解锁的容量为准。
        if available < count:
            raise ValueError(f"当前已解锁的数据体仓库剩余 {max(0, available)} 个位置，本次需要 {count} 个，请先在游戏中清理仓库")
        last_uid = max([pack.get_varint(2), *(uid for uid, _ in entries)])
        if last_uid + count >= 1 << 32:
            raise ValueError("数据体编号已达到游戏格式上限")

    def _verify_created_bodies(self, updated: bytes, requests: list[BodyRequest],
                               uids: list[int], scores: list[int]) -> int:
        # 完整编码回读后核对每个数据体，再进入唯一的磁盘提交点。
        verified = SaveDocument.from_compressed(updated)
        _, pack = pack_from_save(verified)
        bodies = dict(body_entries(pack))
        for request, uid, score in zip(requests, uids, scores):
            created = bodies.get(uid)
            if created is None or created.get_varint(2) != request.character_id:
                raise ValueError("生成数据体的回读验证失败，原存档未修改")
            selected = [(nested(field).get_varint(1), nested(field).get_varint(2)) for field in created.fields(30)]
            expected = list(zip(request.strategy_ids, request.qualities))
            if selected != expected or double_value(created, 16) != score:
                raise ValueError("生成数据体的回读验证失败，原存档未修改")
        return len(bodies)

    def _backup(self, path: Path, original: bytes) -> Path:
        directory = path.parent.parent / "DataBodyToolBackups"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = directory / f"slot-{path.name}-{stamp}.bak"
        with backup.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        if backup.read_bytes() != original:
            raise ValueError("备份校验失败，原存档未修改")
        metadata = {"source_path": str(path), "sha256": digest(original), "created": datetime.now().isoformat(timespec="seconds")}
        backup.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return backup

    def _commit(self, path: Path, original: bytes, updated: bytes) -> Path:
        backup = self._backup(path, original)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".databody-", dir=path.parent, delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            if temp_path.read_bytes() != updated:
                raise ValueError("临时存档校验失败，原存档未修改")
            self._current_save(path)
            os.replace(temp_path, path)
            temp_path = None
            if path.read_bytes() != updated:
                raise ValueError(f"写入后校验失败，请从此备份恢复：{backup}")
            self.loaded_digests[path] = digest(updated)
            return backup
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def restore_backup(self, path: str | Path, backup_path: str | Path) -> dict:
        path = Path(path).resolve()
        backup_path = Path(backup_path).resolve()
        metadata = json.loads(backup_path.with_suffix(".json").read_text(encoding="utf-8"))
        if Path(metadata["source_path"]).resolve() != path:
            raise ValueError("该备份不属于当前选择的存档槽，请选择对应存档")
        restored = backup_path.read_bytes()
        if digest(restored) != metadata["sha256"]:
            raise ValueError("备份校验不通过，文件可能已损坏")
        document = SaveDocument.from_compressed(restored)
        _, pack = pack_from_save(document)
        body_entries(pack)
        original = self._current_save(path)
        safety_backup = self._commit(path, original, restored)
        return {"backup_path": str(safety_backup), "count": len(body_entries(pack))}
