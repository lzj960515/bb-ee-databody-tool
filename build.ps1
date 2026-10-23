param([string]$Name = '数据体工具')

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onefile --windowed --name $Name --add-data 'data/catalog.json;data' --add-data 'data/planner_rules.json;data' --add-data 'data/builds.json;data' --add-data 'frontend;frontend' launch.py
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
Copy-Item -LiteralPath '.\README.md' -Destination '.\dist\使用说明.md' -Force
New-Item -ItemType Directory -Path '.\dist\docs\images' -Force | Out-Null
Copy-Item -LiteralPath '.\docs\images\build-planner.png' -Destination '.\dist\docs\images\build-planner.png' -Force
