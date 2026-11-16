param([string]$PlanPath)
$ErrorActionPreference = 'Stop'

function Get-ToolFileHash($Path) {
    $toolHasher = [Security.Cryptography.SHA256]::Create()
    $toolStream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($toolHasher.ComputeHash($toolStream)).Replace('-', '').ToLowerInvariant() }
    finally { $toolStream.Dispose(); $toolHasher.Dispose() }
}

function Wait-ToolExit($ProcessId) {
    if ($ProcessId -le 0) { return }
    try { $toolProcess = [Diagnostics.Process]::GetProcessById($ProcessId) }
    catch [ArgumentException] { return }
    try {
        if (-not $toolProcess.WaitForExit(90000)) { throw '等待程序退出超时，请关闭工具后重新更新' }
    } finally { $toolProcess.Dispose() }
}

function Test-ToolRunning($ProcessId) {
    if ($ProcessId -le 0) { return $false }
    try {
        $toolProcess = [Diagnostics.Process]::GetProcessById($ProcessId)
        try { return -not $toolProcess.HasExited } finally { $toolProcess.Dispose() }
    } catch [ArgumentException] { return $false }
}

function Start-ToolApplication($Target) {
    # 更新后恢复用户需要操作的主窗口。
    # onefile 重启必须重新解包，旧进程的临时资源随后会被清理。
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath $Target -WorkingDirectory ([IO.Path]::GetDirectoryName($Target)) | Out-Null
}

function Install-ToolUpdate($Plan) {
    Wait-ToolExit $Plan.parent_pid
    if ((Get-ToolFileHash $Plan.package) -ne $Plan.sha256) {
        throw '更新文件校验失败，旧版已保留'
    }
    if ((Get-ToolFileHash $Plan.target) -ne $Plan.original_sha256) {
        throw '当前程序已被其他操作更新，请重新打开后检查版本'
    }
    $toolReplaced = $false
    try {
        # onefile 的外层进程可能稍后才释放 EXE，文件锁只作有限等待。
        for ($toolAttempt = 0; $toolAttempt -lt 40; $toolAttempt++) {
            try {
                [IO.File]::Replace($Plan.package, $Plan.target, $Plan.backup)
                $toolReplaced = $true
                break
            } catch [IO.IOException], [UnauthorizedAccessException] {
                if ($toolAttempt -eq 39) { throw '程序文件仍被占用，请关闭其他同路径的工具窗口后重试' }
                Start-Sleep -Milliseconds 250
            }
        }
        Start-ToolApplication $Plan.target
    } catch {
        if ($toolReplaced -and [IO.File]::Exists($Plan.backup)) {
            [IO.File]::Replace($Plan.backup, $Plan.target, $Plan.package)
        }
        throw
    }
    if ([IO.File]::Exists($Plan.backup)) { Remove-Item -LiteralPath $Plan.backup -Force }
}

if ($PlanPath) {
    $toolPlan = $null
    try {
        $toolPlan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
        [IO.File]::WriteAllText((Join-Path ([IO.Path]::GetDirectoryName($PlanPath)) 'ready.flag'), [string]$PID)
        Install-ToolUpdate $toolPlan
    } catch {
        $toolError = $_.Exception.Message
        if ($toolPlan -and -not (Test-ToolRunning $toolPlan.parent_pid) -and [IO.File]::Exists($toolPlan.target)) {
            try { Start-ToolApplication $toolPlan.target } catch { }
        }
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show("更新未完成，旧版已保留。`n$toolError", '数据体工具更新') | Out-Null
    } finally {
        if ($toolPlan -and [IO.File]::Exists($toolPlan.package)) { Remove-Item -LiteralPath $toolPlan.package -Force }
        $toolStaging = [IO.Path]::GetDirectoryName($PlanPath)
        foreach ($toolName in @('download.exe', 'plan.json', 'install.ps1', 'ready.flag')) {
            $toolFile = Join-Path $toolStaging $toolName
            if ([IO.File]::Exists($toolFile)) { Remove-Item -LiteralPath $toolFile -Force }
        }
        if ([IO.Directory]::Exists($toolStaging) -and [IO.Directory]::GetFileSystemEntries($toolStaging).Length -eq 0) {
            [IO.Directory]::Delete($toolStaging)
        }
    }
}
