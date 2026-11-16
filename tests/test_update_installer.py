"""使用隔离文件核验 Windows 原子替换和启动失败回滚。"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from databody.update_installer import WindowsUpdateInstaller, file_digest


RUNNER = r'''
param($InstallScript, $PlanFile, $Scenario)
$ErrorActionPreference = 'Stop'
. $InstallScript
$plan = Get-Content -LiteralPath $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-ToolRunning $PID) -or (Test-ToolRunning 0)) { throw 'process liveness check failed' }
function Start-ToolApplication($Target) {
    if ($Scenario -eq 'launch-failure') { throw 'simulated launch failure' }
    [IO.File]::WriteAllText(($Target + '.started'), 'started')
}
$held = $null
if ($Scenario -eq 'locked') {
    $held = [IO.File]::Open($plan.target, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
}
try {
    try {
        Install-ToolUpdate $plan
        if ($Scenario -ne 'success') { throw 'expected rejection was missing' }
        'installed'
    } catch {
        if ($Scenario -eq 'success' -or $_.Exception.Message -eq 'expected rejection was missing') { throw }
        $expected = switch ($Scenario) {
            'launch-failure' { 'simulated launch failure' }
            'tampered-package' { '校验失败' }
            'changed-target' { '其他操作更新' }
            'locked' { '仍被占用' }
        }
        if (-not $_.Exception.Message.Contains($expected)) { throw }
        'rejected'
    }
} finally { if ($held) { $held.Dispose() } }
'''


class UpdateInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "工具's update folder"
        self.root.mkdir()
        self.target = self.root / '数据体工具.exe'
        self.target.write_bytes(b'MZoriginal program')
        self.staging = self.root / 'cache/update-test'
        self.staging.mkdir(parents=True)
        self.package = self.staging / 'download.exe'
        self.package.write_bytes(b'MZnew program')
        self.installer = WindowsUpdateInstaller(self.target)

    def prepare(self):
        return self.installer.prepare(self.package, file_digest(self.package), '1.10.0')

    def test_preparation_preserves_original_and_places_verified_file_on_same_volume(self):
        plan_path = self.prepare()
        plan = json.loads(plan_path.read_text('utf8'))
        self.assertEqual(self.target.read_bytes(), b'MZoriginal program')
        self.assertTrue(Path(plan['package']).parent.samefile(self.target.parent))
        self.assertEqual(Path(plan['package']).read_bytes(), b'MZnew program')
        self.assertEqual(plan['original_sha256'], file_digest(self.target))
        self.assertEqual(plan['parent_pid'], os.getpid())
        self.assertTrue((self.staging / 'install.ps1').read_bytes().startswith(b'\xef\xbb\xbf'))
        self.installer.discard(plan_path)
        self.assertFalse(Path(plan['package']).exists())

    def test_bad_download_never_changes_original_or_leaves_adjacent_file(self):
        with self.assertRaisesRegex(ValueError, '校验'):
            self.installer.prepare(self.package, '0' * 64, '1.10.0')
        self.assertEqual(self.target.read_bytes(), b'MZoriginal program')
        self.assertEqual(list(self.root.glob('.*.update-*')), [])

    def test_onefile_handoff_waits_for_the_outer_resource_owner(self):
        with patch('databody.update_installer.sys.frozen', True, create=True), \
             patch('databody.update_installer.os.getppid', return_value=9876):
            plan_path = self.prepare()
        plan = json.loads(plan_path.read_text('utf8'))
        self.assertEqual(plan['parent_pid'], 9876)

    @unittest.skipUnless(os.name == 'nt', '安装交接使用 Windows PowerShell')
    def test_installer_process_receives_literal_paths_and_is_hidden(self):
        plan_path = self.prepare()
        with patch('databody.update_installer.subprocess.Popen') as launch:
            launch.side_effect = lambda *args, **kwargs: (self.staging / 'ready.flag').write_text('ready')
            self.installer.launch(plan_path)
        command = launch.call_args.args[0]
        self.assertEqual(command[-2:], ['-PlanPath', str(plan_path)])
        self.assertEqual(command[command.index('-File') + 1], str(self.staging / 'install.ps1'))
        self.assertEqual(launch.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    @unittest.skipUnless(os.name == 'nt', '安装交接使用 Windows PowerShell')
    def test_helper_exit_before_ready_leaves_current_application_available(self):
        plan_path = self.prepare()
        with patch('databody.update_installer.subprocess.Popen') as launch:
            launch.return_value.poll.return_value = 1
            with self.assertRaisesRegex(OSError, '未能启动'):
                self.installer.launch(plan_path)
        self.assertEqual(self.target.read_bytes(), b'MZoriginal program')

    @unittest.skipUnless(os.name == 'nt', '安装交接使用 Windows PowerShell')
    def test_helper_start_timeout_is_stopped_without_changing_program(self):
        plan_path = self.prepare()
        with patch('databody.update_installer.subprocess.Popen') as launch, \
             patch('databody.update_installer.time.monotonic', side_effect=[0, 13]):
            launch.return_value.poll.return_value = None
            with self.assertRaisesRegex(OSError, '启动超时'):
                self.installer.launch(plan_path)
            launch.return_value.terminate.assert_called_once()
            launch.return_value.wait.assert_called_once_with(timeout=5)
        self.assertEqual(self.target.read_bytes(), b'MZoriginal program')

    @unittest.skipUnless(os.name == 'nt', '原子替换使用 Windows 文件语义')
    def test_real_windows_replacement_rolls_back_failed_start_and_rejects_changed_files(self):
        for scenario in ('success', 'launch-failure', 'tampered-package', 'changed-target', 'locked'):
            with self.subTest(scenario=scenario):
                self.target.write_bytes(b'MZoriginal program')
                self.package.write_bytes(b'MZnew program')
                plan_path = self.prepare()
                plan = json.loads(plan_path.read_text('utf8'))
                plan['parent_pid'] = 0
                plan_path.write_text(json.dumps(plan), encoding='utf8')
                if scenario == 'tampered-package':
                    Path(plan['package']).write_bytes(b'MZchanged after download')
                if scenario == 'changed-target':
                    self.target.write_bytes(b'MZexternal update')
                sentinel = self.root / 'custom-builds.json'
                sentinel.write_bytes(b'personal builds remain intact')
                runner = self.root / 'run-test.ps1'
                runner.write_text(RUNNER, encoding='utf-8-sig')
                process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                    '-ExecutionPolicy', 'Bypass', '-File', str(runner), '-InstallScript',
                    str(self.staging / 'install.ps1'), '-PlanFile', str(plan_path), '-Scenario', scenario],
                    capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
                expected = b'MZnew program' if scenario == 'success' else (
                    b'MZexternal update' if scenario == 'changed-target' else b'MZoriginal program')
                self.assertEqual(self.target.read_bytes(), expected)
                self.assertEqual(sentinel.read_bytes(), b'personal builds remain intact')
                self.assertFalse(Path(plan['backup']).exists())
                if Path(plan['package']).exists():
                    Path(plan['package']).unlink()


if __name__ == '__main__':
    unittest.main()
