$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 3.11 虚拟环境' }
    & $taskPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；请检查网络后手动安装' }
}
& $taskPython -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --server.maxUploadSize 20 --browser.gatherUsageStats false
