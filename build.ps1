$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onefile --windowed --name '数据体工具' --add-data 'data/catalog.json;data' --add-data 'data/planner_rules.json;data' --add-data 'data/builds.json;data' launch.py
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
Copy-Item -LiteralPath '.\README.md' -Destination '.\dist\使用说明.md' -Force
