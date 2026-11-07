[CmdletBinding()]
param(
    [string]$OperatorId = "",
    [string]$ApproverId = "",
    [ValidatePattern("^[A-Za-z0-9_-]{1,64}$")][string]$CombinedProfile = $(if ($env:NETOPS_PROFILE) { $env:NETOPS_PROFILE } else { "netops-all" }),
    [string]$RemoteSshTarget = $env:NETOPS_REMOTE_SSH_TARGET,
    [string]$RemoteProjectRoot = $(if ($env:NETOPS_REMOTE_PROJECT_ROOT) { $env:NETOPS_REMOTE_PROJECT_ROOT } else { "/opt/huawei-netops-mcp" }),
    [switch]$NoLaunch
)
$ErrorActionPreference = "Stop"
trap {
    Write-Host "`n[ERROR] 一键启动失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

# Generate ASCII-safe default actor IDs even when the Windows account name contains non-ASCII characters.
$ActorBase = ($env:USERNAME -replace '[^A-Za-z0-9_.@-]', '-').Trim('-')
if ([string]::IsNullOrWhiteSpace($ActorBase)) {
    $ActorBase = ($env:COMPUTERNAME -replace '[^A-Za-z0-9_.@-]', '-').Trim('-')
}
if ([string]::IsNullOrWhiteSpace($ActorBase)) { $ActorBase = "netops" }
if ([string]::IsNullOrWhiteSpace($OperatorId)) {
    $OperatorId = if ($env:NETOPS_OPERATOR_ID) { $env:NETOPS_OPERATOR_ID } else { "$ActorBase-operator" }
}
if ([string]::IsNullOrWhiteSpace($ApproverId)) {
    $ApproverId = if ($env:NETOPS_APPROVER_ID) { $env:NETOPS_APPROVER_ID } else { "$ActorBase-approver" }
}

function Write-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Assert-ExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) { throw "$Action 失败，退出码：$LASTEXITCODE" }
}
function Assert-ActorId([string]$Value, [string]$Label) {
    if ($Value -notmatch '^[A-Za-z0-9_.@-]{1,128}$') { throw "$Label 只允许字母、数字、点、下划线、@ 和连字符（1-128 字符）。" }
}

Assert-ActorId $OperatorId "OperatorId"
Assert-ActorId $ApproverId "ApproverId"
if ($OperatorId -eq $ApproverId) { throw "OperatorId 与 ApproverId 必须不同，双人审批不能使用相同身份。" }
if ($CombinedProfile -notmatch "^[A-Za-z0-9_-]{1,64}$") { throw "CombinedProfile 名称不合法。" }

$Dsh = Get-Command dsh -ErrorAction SilentlyContinue
if (-not $Dsh) {
    throw "没有找到 DeepSeek Harness 的 dsh CLI。请先安装/配置 DeepSeek Harness CLI，并确保 dsh 在 PATH 中。官方 profile 创建需要 dsh --profile <name> --from-default-profile web。"
}
$DshCommand = if ($Dsh.Source) { $Dsh.Source } else { "dsh" }
$DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME ".dsh" }
$env:DSH_HOME = $DshHome
$ProfileRoot = Join-Path $DshHome "profiles"

function Ensure-DshProfile([string]$Name) {
    $Dir = Join-Path $ProfileRoot $Name
    $ManifestOk = (Test-Path (Join-Path $Dir "package.json")) -and (Test-Path (Join-Path $Dir "dsh.profile"))
    if ($ManifestOk) {
        Write-Host "[OK] Harness Profile 已存在：$Name" -ForegroundColor Green
        return
    }

    Write-Host "[初始化] 创建 Harness Profile：$Name" -ForegroundColor Yellow
    $OldPatch = $null
    $BackupDir = $null
    if (Test-Path $Dir) {
        $PatchPath = Join-Path $Dir "cordis.patch.yml"
        if (Test-Path $PatchPath) { $OldPatch = Get-Content -Raw -Encoding UTF8 $PatchPath }
        $BackupDir = "$Dir.pre-oneclick-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Move-Item -LiteralPath $Dir -Destination $BackupDir
        Write-Host "旧 Profile 目录已备份：$BackupDir" -ForegroundColor DarkYellow
    }

    try {
        # --dump-config 会输出并退出；--from-default-profile 先从官方 web 模板初始化自定义 Profile。
        & $DshCommand --profile $Name --from-default-profile web --dump-config *> $null
        Assert-ExitCode "Harness Profile 初始化（$Name）"
        $NewDir = Join-Path $ProfileRoot $Name
        if (-not ((Test-Path (Join-Path $NewDir "package.json")) -and (Test-Path (Join-Path $NewDir "dsh.profile")))) {
            throw "dsh 命令返回成功，但 Profile 清单未生成：$NewDir"
        }
        if ($null -ne $OldPatch) {
            Set-Content -LiteralPath (Join-Path $NewDir "cordis.patch.yml") -Value $OldPatch -Encoding UTF8
        }
    } catch {
        if ($BackupDir -and (Test-Path $BackupDir)) {
            if (Test-Path $Dir) {
                $FailedDir = "$Dir.failed-init-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
                Move-Item -LiteralPath $Dir -Destination $FailedDir
            }
            Move-Item -LiteralPath $BackupDir -Destination $Dir
        }
        throw
    }
}

function Write-HarnessEntries([string]$Profile) {
    $Installer = Join-Path $PSScriptRoot "install-harness-dual.ps1"
    $InstallerArgs = @("-Profile", $Profile, "-ProjectRoot", $Root, "-OperatorId", $OperatorId, "-ApproverId", $ApproverId)
    if (-not [string]::IsNullOrWhiteSpace($RemoteSshTarget)) {
        $InstallerArgs += @("-RemoteSshTarget", $RemoteSshTarget, "-RemoteProjectRoot", $RemoteProjectRoot)
    }
    & $Installer @InstallerArgs
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "写入 Harness 双角色配置失败：$Profile" }
}

if ([string]::IsNullOrWhiteSpace($RemoteSshTarget)) {
    Write-Step "检查/安装本机 MCP 运行环境"
    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $NeedInstall = -not (Test-Path $VenvPython) -or -not (Test-Path (Join-Path $Root ".env"))
    if (-not $NeedInstall) {
        & $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" *> $null
        $NeedInstall = ($LASTEXITCODE -ne 0)
    }
    if (-not $NeedInstall) {
        & $VenvPython -c "import fastmcp, netmiko, cryptography, yaml, filelock, pydantic_settings" *> $null
        $NeedInstall = ($LASTEXITCODE -ne 0)
    }
    if ($NeedInstall -and (Test-Path (Join-Path $Root ".venv"))) {
        $OldVenv = Join-Path $Root (".venv.incompatible-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Move-Item -LiteralPath (Join-Path $Root ".venv") -Destination $OldVenv
        Write-Host "旧虚拟环境已备份：$OldVenv" -ForegroundColor Yellow
    }
    if ($NeedInstall) {
        & (Join-Path $PSScriptRoot "install.ps1") -InstallPython
        Assert-ExitCode "Windows 环境安装"
    } else {
        Write-Host "[OK] Python 虚拟环境和项目依赖已存在，跳过重复 pip 安装。" -ForegroundColor Green
        & $VenvPython (Join-Path $PSScriptRoot "bootstrap.py")
        Assert-ExitCode "环境/数据库初始化"
    }

    Write-Step "执行本机环境自检"
    $env:NETOPS_OPERATOR_ID = $OperatorId
    $env:NETOPS_OPERATOR_ROLE = "operator"
    $env:NETOPS_REQUIRE_DUAL_APPROVAL = "true"
    & $VenvPython -m app.cli doctor
    Assert-ExitCode "本机 doctor 检查"
} else {
    Write-Step "检查 Ubuntu 远程 MCP 和 SSH 密钥登录"
    $Ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
    if (-not $Ssh) { $Ssh = Get-Command ssh -ErrorAction SilentlyContinue }
    if (-not $Ssh) { throw "没有找到 OpenSSH Client（ssh.exe）。请在 Windows 可选功能中安装 OpenSSH Client。" }
    if ($RemoteSshTarget -notmatch '^[A-Za-z0-9_.@-]+$') { throw "RemoteSshTarget 格式不正确，示例：ubuntuuser@192.168.1.20" }
    if (-not $RemoteProjectRoot.StartsWith("/") -or $RemoteProjectRoot -match "['`r`n]") { throw "RemoteProjectRoot 必须是安全的 Ubuntu 绝对路径。" }
    $RemoteCheck = "test -x '$RemoteProjectRoot/.venv/bin/python' -a -f '$RemoteProjectRoot/.env' -a -f '$RemoteProjectRoot/app/main.py'"
    & $Ssh.Source -T -o BatchMode=yes -o ConnectTimeout=10 $RemoteSshTarget $RemoteCheck
    Assert-ExitCode "Ubuntu SSH / MCP 路径检查。请先在 Ubuntu 项目根目录执行 bash START-NETOPS-LINUX.sh，并配置 SSH 公钥登录。"
    $RemoteDoctor = "cd '$RemoteProjectRoot' && export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 NETOPS_OPERATOR_ID='$OperatorId' NETOPS_OPERATOR_ROLE=operator NETOPS_REQUIRE_DUAL_APPROVAL=true && '$RemoteProjectRoot/.venv/bin/python' -m app.cli doctor"
    & $Ssh.Source -T -o BatchMode=yes -o ConnectTimeout=10 $RemoteSshTarget $RemoteDoctor
    Assert-ExitCode "Ubuntu 远程 MCP 依赖、密钥、身份及数据库检查"
}

Write-Step "创建一个同时包含 operator / approver 的 Harness Profile"
Ensure-DshProfile $CombinedProfile
Write-HarnessEntries $CombinedProfile
& $DshCommand --profile $CombinedProfile --dump-config *> $null
Assert-ExitCode "双角色 Profile YAML / Harness 配置校验"

Write-Host "`n==============================================" -ForegroundColor Green
Write-Host " Huawei NetOps MCP 一键配置完成" -ForegroundColor Green
Write-Host " operator : $OperatorId  (MCP: huawei_netops_operator)" -ForegroundColor Green
Write-Host " approver : $ApproverId  (MCP: huawei_netops_approver)" -ForegroundColor Green
Write-Host " Harness Profile : $CombinedProfile（两个角色同时加载）" -ForegroundColor Green
Write-Host " 申请/审批身份差异检查 : 已启用" -ForegroundColor Green
if ($RemoteSshTarget) { Write-Host " MCP 位置  : Ubuntu ${RemoteSshTarget}:$RemoteProjectRoot" -ForegroundColor Green }
else { Write-Host " MCP 位置  : 本机 Windows" -ForegroundColor Green }
Write-Host "==============================================" -ForegroundColor Green

if ($NoLaunch -or $env:NETOPS_NO_LAUNCH -eq "1") {
    Write-Host "未启动 Harness（NETOPS_NO_LAUNCH=1）。运行 dsh --profile $CombinedProfile 即可同时启动两个角色。" -ForegroundColor Yellow
    exit 0
}

Write-Step "启动一次 DeepSeek Harness；operator 与 approver 两个 MCP 连接将同时加载"
Write-Host "operator MCP：$OperatorId（配置申请/执行）" -ForegroundColor Green
Write-Host "approver MCP：$ApproverId（审批/确认/回滚）" -ForegroundColor Green
Write-Host "注意：同一 Harness 会话同时持有两种工具身份，不等同于两个独立人员的强制双人控制。" -ForegroundColor Yellow
& $DshCommand --profile $CombinedProfile
exit $LASTEXITCODE
