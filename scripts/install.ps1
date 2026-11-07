[CmdletBinding()]
param([switch]$InstallPython)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root

function Get-SupportedPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($Minor in @('3.12', '3.11')) {
            & py "-$Minor" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)' *> $null
            if ($LASTEXITCODE -eq 0) { return @{ Command = 'py'; Args = @("-$Minor") } }
        }
    }
    foreach ($Name in @('python', 'python3')) {
        $Candidate = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Candidate) {
            & $Candidate.Source -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)' *> $null
            if ($LASTEXITCODE -eq 0) { return @{ Command = $Candidate.Source; Args = @() } }
        }
    }
    return $null
}

$Python = Get-SupportedPython
if (-not $Python -and $InstallPython) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw '未找到 Python 3.11/3.12，且系统没有 winget。请先安装 Python 3.12。'
    }
    Write-Host '正在通过 winget 安装 Python 3.12……' -ForegroundColor Cyan
    winget install --exact --id Python.Python.3.12 --source winget --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget 安装 Python 3.12 失败：$LASTEXITCODE" }
    $Python = Get-SupportedPython
    if (-not $Python) {
        # The current PowerShell process may not inherit PATH updates made by winget.
        $KnownPythonPaths = @(
            (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe'),
            (Join-Path $env:ProgramFiles 'Python312\python.exe'),
            (Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'),
            (Join-Path $env:ProgramFiles 'Python311\python.exe')
        )
        foreach ($CandidatePath in $KnownPythonPaths) {
            if (Test-Path $CandidatePath) {
                & $CandidatePath -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)' *> $null
                if ($LASTEXITCODE -eq 0) {
                    $Python = @{ Command = $CandidatePath; Args = @() }
                    break
                }
            }
        }
    }
}
if (-not $Python) { throw '需要 Python 3.11 或 3.12。安装后未能在 PATH 或标准安装目录中找到解释器，请检查 Python 安装状态。' }

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    $VenvArgs = @($Python.Args) + @('-m', 'venv', '.venv')
    & $Python.Command @VenvArgs
    if ($LASTEXITCODE -ne 0) { throw "创建 Python 虚拟环境失败：$LASTEXITCODE" }
}

Write-Host '[1/4] 安装项目运行依赖……' -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "升级 pip/setuptools 失败：$LASTEXITCODE" }
& $VenvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "安装项目依赖失败：$LASTEXITCODE" }

Write-Host '[2/4] 生成或复用加密密钥并初始化数据库……' -ForegroundColor Cyan
& $VenvPython scripts\bootstrap.py
if ($LASTEXITCODE -ne 0) { throw "数据库初始化失败：$LASTEXITCODE" }

Write-Host '[3/4] 检查项目 Python 包……' -ForegroundColor Cyan
& $VenvPython -c 'import fastmcp, netmiko, cryptography, yaml, filelock, pydantic_settings'
if ($LASTEXITCODE -ne 0) { throw '项目依赖导入检查失败。' }

Write-Host '[4/4] 检查运行身份与数据库……' -ForegroundColor Cyan
& $VenvPython -m app.cli doctor
if ($LASTEXITCODE -ne 0) { throw 'netops doctor 检查失败。' }

Write-Host 'MCP 核心环境安装和自检完成。Harness Profile 由根目录一键启动程序统一创建。' -ForegroundColor Green
