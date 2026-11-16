"""只从本工具的 GitHub 正式发布发现和下载更新，安装前校验完整文件。"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .custom_builds import user_data_directory
from .update_installer import WindowsUpdateInstaller
from .update_types import DownloadStatus, UpdateRelease

REPOSITORY_URL = 'https://github.com/lzj960515/bb-ee-databody-tool'
RELEASE_API_URL = 'https://api.github.com/repos/lzj960515/bb-ee-databody-tool/releases/latest'
EXECUTABLE_NAME = 'bb-ee-databody-tool.exe'
MAX_UPDATE_BYTES = 128 * 1024 * 1024


def version_numbers(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('发布版本格式不正确，已停止更新')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


def clean_staging(directory: Path) -> None:
    # 此目录由本次下载独占，只创建普通文件；不递归操作其他目录。
    for path in directory.iterdir():
        path.unlink()
    directory.rmdir()


class UpdateService:
    def __init__(self, current_version: str = __version__, *, installer=None,
                 directory: Path | None = None, opener=None):
        self.current_version = current_version
        self.installer = installer if installer is not None else WindowsUpdateInstaller()
        self._directory = directory if directory is not None else user_data_directory() / 'updates'
        self._open = opener or urllib.request.urlopen
        self._work_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status = DownloadStatus()
        self._cancelled = threading.Event()
        self._release: UpdateRelease | None = None
        self._prepared: Path | None = None

    @property
    def can_install(self) -> bool:
        return self.installer.can_install

    def _request(self, url: str, *, method='GET', timeout=12):
        request = urllib.request.Request(url, method=method,
            headers={'User-Agent': f'bb-ee-databody-tool/{self.current_version}', 'Accept': 'application/vnd.github+json'})
        return self._open(request, timeout=timeout)

    def _read(self, url: str, limit: int) -> bytes:
        with self._request(url) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('更新信息超出预期大小，已停止更新')
        return data

    def _api_release(self) -> UpdateRelease:
        document = json.loads(self._read(RELEASE_API_URL, 1024 * 1024))
        if not isinstance(document, dict) or document.get('draft') or document.get('prerelease'):
            raise ValueError('更新不是正式发布版本')
        tag = document.get('tag_name')
        version_numbers(tag)
        assets = {row['name']: row for row in document.get('assets', [])}
        if not {EXECUTABLE_NAME, 'SHA256SUMS.txt'}.issubset(assets):
            raise ValueError('正式更新附件尚未齐全，请稍后重试')
        executable = assets[EXECUTABLE_NAME]
        size = executable.get('size')
        if type(size) is not int or not 2 <= size <= MAX_UPDATE_BYTES:
            raise ValueError('更新文件大小不符合预期')
        digest = executable.get('digest')
        checksum = digest.removeprefix('sha256:') if isinstance(digest, str) else None
        if checksum is not None and not re.fullmatch('[a-f0-9]{64}', checksum):
            raise ValueError('发布文件校验信息无效')
        return UpdateRelease(tag.removeprefix('v'), tag, (document.get('body') or '')[:12000], size, checksum)

    def _redirect_release(self) -> UpdateRelease:
        with self._request(REPOSITORY_URL + '/releases/latest', method='HEAD') as response:
            match = re.fullmatch(re.escape(REPOSITORY_URL) + r'/releases/tag/(v\d+\.\d+\.\d+)', response.geturl())
        if not match:
            raise ValueError('官方发布页未返回有效的正式版本')
        tag = match.group(1)
        return UpdateRelease(tag[1:], tag)

    def check(self) -> dict:
        with self._work_lock:
            try:
                release = self._api_release()
            except OSError:
                self._ensure_running()
                try:
                    release = self._redirect_release()
                except OSError as error:
                    raise ValueError('暂时无法连接 GitHub，请检查网络后点击版本号重试；工具仍可正常使用') from error
            self._ensure_running()
            self._release = release
            return {'current_version': self.current_version, 'latest_version': release.version,
                    'available': version_numbers(release.version) > version_numbers(self.current_version),
                    'notes': release.notes, 'release_url': REPOSITORY_URL + '/releases/tag/' + release.tag,
                    'can_install': self.can_install}

    def status(self) -> dict:
        with self._status_lock:
            return asdict(self._status)

    def _set_status(self, phase: str, received=0, total=0) -> None:
        with self._status_lock:
            self._status = DownloadStatus(phase, received, total)

    def _ensure_running(self) -> None:
        if self._cancelled.is_set():
            raise ValueError('更新已取消，当前程序未修改')

    def _download(self, release: UpdateRelease, directory: Path) -> tuple[Path, str]:
        base = REPOSITORY_URL + '/releases/download/' + release.tag + '/'
        checksums = self._read(base + 'SHA256SUMS.txt', 65536).decode('utf-8-sig')
        matches = re.findall(r'^([a-fA-F0-9]{64})  ' + re.escape(EXECUTABLE_NAME) + r'\r?$', checksums, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError('更新缺少有效的文件校验值')
        expected = matches[0].lower()
        if release.sha256 and release.sha256 != expected:
            raise ValueError('发布附件与校验清单不一致，已停止更新')
        destination = directory / 'download.exe'
        digest = hashlib.sha256()
        received = 0
        deadline = time.monotonic() + 180
        with self._request(base + EXECUTABLE_NAME) as response, destination.open('xb') as output:
            content_size = int(response.headers.get('Content-Length', 0))
            total = release.size or content_size
            if total > MAX_UPDATE_BYTES or (release.size and content_size and release.size != content_size):
                raise ValueError('更新文件大小不符合发布信息')
            while True:
                self._ensure_running()
                if time.monotonic() > deadline:
                    raise TimeoutError('更新下载超时，请稍后重试')
                chunk = response.read(65536)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_UPDATE_BYTES or (total and received > total):
                    raise ValueError('更新文件大小超过预期')
                output.write(chunk)
                digest.update(chunk)
                self._set_status('downloading', received, total)
        if (total and received != total) or digest.hexdigest() != expected:
            raise ValueError('更新文件未完整下载或校验失败，当前程序未修改，请重试')
        with destination.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('下载内容不是有效的 Windows 程序')
        return destination, expected

    def prepare(self) -> dict:
        with self._work_lock:
            self._ensure_running()
            if not self.can_install:
                raise ValueError('自动安装仅适用于打包后的 EXE')
            release = self._release
            if release is None or version_numbers(release.version) <= version_numbers(self.current_version):
                raise ValueError('请先检查并选择可用的新版本')
            if self._prepared is not None:
                return self.status()
            self._directory.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix='update-', dir=self._directory))
            self._set_status('downloading')
            try:
                package, checksum = self._download(release, directory)
                self._ensure_running()
                self._prepared = self.installer.prepare(package, checksum, release.version)
                self._ensure_running()
            except Exception:
                if self._prepared is not None:
                    self.installer.discard(self._prepared)
                    self._prepared = None
                clean_staging(directory)
                self._set_status('error')
                raise
            status = self.status()
            self._set_status('ready', status['received'], status['total'])
            return self.status()

    def install(self) -> dict:
        with self._work_lock:
            self._ensure_running()
            if self._prepared is None:
                raise ValueError('请先完整下载并校验更新')
            self.installer.launch(self._prepared)
            self._set_status('installing')
            return {'started': True}

    def cancel(self) -> None:
        self._cancelled.set()
        if self._work_lock.acquire(blocking=False):
            try:
                if self._prepared is not None and self.status()['phase'] != 'installing':
                    self.installer.discard(self._prepared)
                    clean_staging(self._prepared.parent)
                    self._prepared = None
            finally:
                self._work_lock.release()
