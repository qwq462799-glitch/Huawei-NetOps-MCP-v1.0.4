# DeepSeek Harness 一键接入（v1.0.4）

## 1. 一次启动，同时加载两个角色

Windows 双击 `START-NETOPS-WINDOWS.bat`；Ubuntu 本机执行 `bash START-NETOPS-LINUX.sh`。

脚本会检查 Python 与依赖；仅全新空部署自动生成密钥，已有数据库缺少原密钥、密钥无效或环境变量与项目 `.env` 冲突时会安全停止，然后初始化/升级数据库，并在同一个 `netops-all` Harness Profile 中写入两个 MCP 客户端实例：

- `huawei_netops_operator`：身份固定为 operator。
- `huawei_netops_approver`：身份固定为 approver。

最后只运行一次：

```bash
dsh --profile netops-all
```

Harness 读取同一个 Profile 后，会分别启动两个 stdio MCP 子进程。用户在同一个 Harness 会话里即可使用两组工具；工具名称分别以 `mcp__huawei_netops_operator__` 和 `mcp__huawei_netops_approver__` 为前缀，无需退出当前会话、重新运行脚本或切换 Profile。

## 2. Windows 本机模式

默认在 Windows 本机运行 MCP，适用于 eNSP / eNSP Pro 管理地址可被 Windows 访问的环境：

```bat
START-NETOPS-WINDOWS.bat
```

同一 Harness Profile 会同时加载 operator 与 approver 两个 MCP 实例。

## 3. Windows Harness 连接 Ubuntu MCP

先在 Ubuntu 安装核心：

```bash
bash START-NETOPS-LINUX.sh
```

然后在 Windows `START-NETOPS-WINDOWS.bat` 配置：

```bat
set "NETOPS_REMOTE_SSH_TARGET=ubuntuuser@192.168.1.20"
set "NETOPS_REMOTE_PROJECT_ROOT=/opt/huawei-netops-mcp"
```

再次双击同一个入口。脚本在同一个 `netops-all` Profile 中创建两条 SSH stdio MCP 连接，分别带入 operator 与 approver 身份环境变量。一次启动 Harness 即可拉起两个远程 MCP 进程。

## 4. 身份和安全说明

两个 MCP 子进程共享数据库和加密密钥，但使用独立身份 ID、角色权限和终端会话。SQLite 回滚调度通过共享文件锁选举 leader，避免重复调度。

**同一 Harness 会话同时加载两种身份不等同于真正的双人审批。** 它解决的是不必重启、不必切换 Profile 的易用性。若必须由不同自然人分别操作和审批，应在不同 OS 账户/受控会话中分别启动单角色 Profile，并使用企业 SSO/MFA、文件权限和审计系统保证身份独立。

## 5. 常见问题

- **是不是会启动两个 MCP？** 是。同一个 Harness Profile 包含两个 stdio MCP client 条目，因此 Harness 启动时会拉起两个 MCP 子进程；这是在同一个会话中绑定两种固定进程身份的必要方式。它们共用同一个项目数据库和配置密钥。
- **修改角色 ID 或远程地址后怎么办？** 重新运行同一个一键入口会幂等更新 `netops-all` Profile；已经运行的 Harness 进程不会热加载配置，需要退出当前 Harness 会话后再启动一次。正常使用时不需要为了切换 operator/approver 重跑脚本，因为两个工具实例会在同一次启动中同时加载。
- **没有单独后台 MCP 服务？** stdio MCP 由 Harness 建立 stdin/stdout 管道后拉起，不应脱离客户端运行成无管道的后台守护进程。
- **MCP 子进程为什么有两个？** 每个 MCP 子进程在启动时绑定固定角色；一个进程无法在同一时刻既是 operator 又是 approver。Harness UI 只启动一次，底层分别管理两个子进程。
- **找不到 dsh？** 需先安装 DeepSeek Harness CLI 并确保 `dsh` 位于 PATH。安装脚本不会未经确认自动下载 Harness。
