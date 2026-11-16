"""在可写程序目录准备安装，交给独立的 Windows 进程完成替换。"""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .update_types import UpdatePlan


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class WindowsUpdateInstaller:
    def __init__(self, target: Path | None = None):
        self.target = target or (Path(sys.executable) if getattr(sys, 'frozen', False) else None)

    @property
    def can_install(self) -> bool:
        return self.target is not None

    def prepare(self, package: Path, checksum: str, version: str) -> Path:
        if self.target is None:
            raise ValueError('自动安装仅适用于打包后的 EXE')
        target = self.target.resolve()
        if target.suffix.lower() != '.exe' or not target.is_file():
            raise ValueError('找不到当前运行的 EXE，已停止更新')
        descriptor, name = tempfile.mkstemp(prefix=f'.{target.stem}.update-', suffix='.exe', dir=target.parent)
        os.close(descriptor)
        incoming = Path(name)
        try:
            shutil.copyfile(package, incoming)
            if file_digest(incoming) != checksum:
                raise ValueError('安装文件校验失败，当前程序未修改')
            # onefile 外层进程拥有 EXE 和解包资源，等它退出后再替换。
            application_pid = os.getppid() if getattr(sys, 'frozen', False) else os.getpid()
            plan = UpdatePlan(str(target), str(incoming), str(incoming.with_suffix('.bak')),
                              checksum, file_digest(target), application_pid, version)
            plan_path = package.parent / 'plan.json'
            plan_path.write_text(json.dumps(asdict(plan), ensure_ascii=False), encoding='utf-8')
            # Windows PowerShell 5.1 需要 BOM 才能正确读取脚本中的中文。
            script = Path(__file__).with_name('update_install.ps1').read_text(encoding='utf-8')
            (package.parent / 'install.ps1').write_text(script, encoding='utf-8-sig')
            return plan_path
        except Exception:
            incoming.unlink(missing_ok=True)
            raise

    def launch(self, plan_path: Path) -> None:
        if os.name != 'nt' or self.target is None:
            raise ValueError('自动安装仅适用于 Windows EXE')
        ready = plan_path.parent / 'ready.flag'
        ready.unlink(missing_ok=True)
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        process = subprocess.Popen([
            str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
            '-ExecutionPolicy', 'Bypass', '-File', str(plan_path.parent / 'install.ps1'),
            '-PlanPath', str(plan_path),
        ], creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        # 辅助脚本确认已经运行后，主窗口才可以关闭。
        deadline = time.monotonic() + 12
        while not ready.is_file():
            if process.poll() is not None:
                raise OSError('更新安装程序未能启动，当前工具仍可继续使用，请重试')
            if time.monotonic() >= deadline:
                process.terminate()
                process.wait(timeout=5)
                raise OSError('更新安装程序启动超时，当前工具仍可继续使用，请重试')
            time.sleep(0.1)

    def discard(self, plan_path: Path) -> None:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        Path(plan['package']).unlink(missing_ok=True)
