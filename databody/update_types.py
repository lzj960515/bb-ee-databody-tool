"""正式更新的版本、下载状态与安装交接契约。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    tag: str
    notes: str = ''
    size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class DownloadStatus:
    phase: str = 'idle'
    received: int = 0
    total: int = 0


@dataclass(frozen=True)
class UpdatePlan:
    target: str
    package: str
    backup: str
    sha256: str
    original_sha256: str
    parent_pid: int
    version: str
