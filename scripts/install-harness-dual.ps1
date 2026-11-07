[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_-]{1,64}$')][string]$Profile = 'netops-all',
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$ProfileRoot = $(if ($env:DSH_HOME) { Join-Path $env:DSH_HOME 'profiles' } else { Join-Path $HOME '.dsh\profiles' }),
    [string]$RemoteSshTarget = '',
    [string]$RemoteProjectRoot = '/opt/huawei-netops-mcp',
    [string]$OperatorId = 'local-operator',
    [string]$ApproverId = 'local-approver'
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
foreach ($Actor in @($OperatorId, $ApproverId)) {
    if ($Actor -notmatch '^[A-Za-z0-9_.@-]{1,128}$') { throw '身份 ID 格式不合法。' }
}
if ($OperatorId -eq $ApproverId) { throw 'operator 与 approver 必须使用不同身份 ID。' }
if ($RemoteSshTarget -and $RemoteSshTarget -notmatch '^[A-Za-z0-9_.@-]+$') { throw 'RemoteSshTarget 格式不正确，应为 user@host。' }
if ($RemoteSshTarget -and (-not $RemoteProjectRoot.StartsWith('/') -or $RemoteProjectRoot -match "['`r`n]")) { throw 'RemoteProjectRoot 必须是安全的 Ubuntu 绝对路径。' }
$DualValue = 'true'

function Quote-Yaml([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
$ProfileDir = Join-Path $ProfileRoot $Profile
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
$PatchFile = Join-Path $ProfileDir 'cordis.patch.yml'
$Existing = if (Test-Path $PatchFile) { Get-Content -Raw -Encoding UTF8 $PatchFile } else { '' }
$Existing = [regex]::Replace($Existing, '(?m)^\s*\[\]\s*(?:#.*)?(?:\r?\n|$)', '')
$Begin = '# BEGIN HUAWEI NETOPS MCP BOTH ROLES'
$End = '# END HUAWEI NETOPS MCP BOTH ROLES'
$Pattern = '(?ms)^' + [regex]::Escape($Begin) + '\r?\n.*?^' + [regex]::Escape($End) + '\s*'
$BeginCount = ([regex]::Matches($Existing, '(?m)^' + [regex]::Escape($Begin) + '$')).Count
$EndCount = ([regex]::Matches($Existing, '(?m)^' + [regex]::Escape($End) + '$')).Count
if ($BeginCount -ne $EndCount -or $BeginCount -gt 1) { throw "双角色托管标记损坏：$PatchFile" }
if ($BeginCount -eq 1) { $Existing = [regex]::Replace($Existing, $Pattern, '').TrimEnd() }
foreach ($Id in @('mcp-huawei-netops-operator','mcp-huawei-netops-approver')) {
    if ($Existing -match "(?m)^\s*id:\s*$([regex]::Escape($Id))\s*$") { throw "存在非脚本托管的同名 MCP 条目：$Id" }
}
foreach ($Server in @('huawei_netops_operator','huawei_netops_approver')) {
    if ($Existing -match "(?m)^\s*serverName:\s*$([regex]::Escape($Server))\s*$") { throw "存在非脚本托管的同名 MCP serverName：$Server" }
}
$Entries = @()
$Roles = @(
    @{ Suffix='operator'; Id=$OperatorId; Role='operator'; Server='huawei_netops_operator' },
    @{ Suffix='approver'; Id=$ApproverId; Role='approver'; Server='huawei_netops_approver' }
)
foreach ($Item in $Roles) {
    if ([string]::IsNullOrWhiteSpace($RemoteSshTarget)) {
        $PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path $PythonExe)) { throw "未找到本地 Python 虚拟环境：$PythonExe" }
        $Command = Quote-Yaml $PythonExe
        $ArgsLine = "args: ['-m', 'app.main']"
        $CwdLine = "        cwd: $(Quote-Yaml $ProjectRoot)"
        $EnvBlock = @(
            "        env:", "          PYTHONUTF8: '1'", "          PYTHONIOENCODING: 'utf-8'",
            "          NETOPS_OPERATOR_ID: $(Quote-Yaml $Item.Id)",
            "          NETOPS_OPERATOR_ROLE: '$($Item.Role)'",
            "          NETOPS_REQUIRE_DUAL_APPROVAL: '$DualValue'"
        )
    } else {
        $SshCommand = Get-Command ssh.exe -ErrorAction SilentlyContinue
        if (-not $SshCommand) { throw '未找到 OpenSSH ssh.exe。' }
        $Command = Quote-Yaml $SshCommand.Source
        $RemoteCommand = "cd '$RemoteProjectRoot' && exec env PYTHONUTF8=1 PYTHONIOENCODING=utf-8 NETOPS_OPERATOR_ID='$($Item.Id)' NETOPS_OPERATOR_ROLE='$($Item.Role)' NETOPS_REQUIRE_DUAL_APPROVAL='$DualValue' '$RemoteProjectRoot/.venv/bin/python' -m app.main"
        $ArgsLine = "args: ['-T', $(Quote-Yaml $RemoteSshTarget), $(Quote-Yaml $RemoteCommand)]"
        $CwdLine = ''
        $EnvBlock = @()
    }
    $Entries += @(
        "    - id: mcp-huawei-netops-$($Item.Suffix)",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        '      config:',
        "        serverName: $($Item.Server)",
        '        transport: stdio',
        "        command: $Command",
        "        $ArgsLine"
    )
    if ($CwdLine) { $Entries += $CwdLine }
    $Entries += $EnvBlock
    $Entries += @(
        '        toolCallTimeoutMs: 120000',
        '        failOnStartupError: true',
        '        reconnect:',
        '          enabled: true',
        '          initialDelayMs: 500',
        '          maxDelayMs: 10000',
        '          maxAttempts: 8'
    )
}
$Managed = @($Begin, '- insert:') + $Entries + @($End)
$EntryText = $Managed -join "`r`n"
$Final = if ([string]::IsNullOrWhiteSpace($Existing)) { $EntryText } else { $Existing.TrimEnd() + "`r`n`r`n" + $EntryText }
$TempFile = Join-Path $ProfileDir (".cordis.patch.$PID.$([guid]::NewGuid().ToString('N')).tmp")
try {
    [System.IO.File]::WriteAllText($TempFile, $Final.TrimEnd() + "`r`n", [System.Text.UTF8Encoding]::new($false))

    # 本机模式可用项目虚拟环境校验 YAML；远程模式由父级一键脚本调用 dsh --dump-config 做最终校验。
    if ([string]::IsNullOrWhiteSpace($RemoteSshTarget)) {
        $PythonForYaml = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path $PythonForYaml)) { throw "未找到项目 Python，无法验证 Harness YAML：$PythonForYaml" }
        & $PythonForYaml -c "import yaml,sys; d=yaml.safe_load(open(sys.argv[1],encoding='utf-8')); assert isinstance(d,list); items=[x for p in d if isinstance(p,dict) for x in p.get('insert',[]) if isinstance(x,dict)]; ids=[x.get('id') for x in items]; servers=[x.get('config',{}).get('serverName') for x in items]; assert ids.count('mcp-huawei-netops-operator')==1 and ids.count('mcp-huawei-netops-approver')==1; assert servers.count('huawei_netops_operator')==1 and servers.count('huawei_netops_approver')==1" $TempFile
        if ($LASTEXITCODE -ne 0) { throw 'Harness 双角色 YAML 校验失败，现有配置未修改。' }
    }

    if (Test-Path $PatchFile) { Copy-Item $PatchFile "$PatchFile.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak" }
    Move-Item -LiteralPath $TempFile -Destination $PatchFile -Force
} finally {
    if (Test-Path $TempFile) { Remove-Item -LiteralPath $TempFile -Force }
}
Write-Host "已在单个 Profile '$Profile' 中注册 operator + approver 两个 MCP 实例。" -ForegroundColor Green
Write-Host "启动一次 dsh --profile $Profile，即可同时加载两套角色工具。" -ForegroundColor Green
Write-Host "连接方式：$(if ($RemoteSshTarget) { 'Windows -> Ubuntu SSH stdio' } else { 'Windows 本机 stdio' })" -ForegroundColor Cyan
