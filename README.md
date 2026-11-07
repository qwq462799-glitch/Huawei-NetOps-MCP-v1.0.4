# Huawei NetOps MCP v1.0.4 — Clean Cross-Platform Release

一个面向网络工程师的跨平台 MCP 网络设备运维工具。DeepSeek Harness 是唯一交互入口，MCP 使用 stdio；不部署独立 Web Dashboard，不需要 Docker，也不开放独立 HTTP MCP 端口。

> **测试边界：** 用户提供的 2026-11-06 真机报告证明 v0.5.0-fixed 在 eNSP Pro CE6800 上完成了报告列明的 SSH、只读 CLI、持久终端、审批配置、快照、确认和回滚测试。该证据不等于 v1.0.4 新增功能已重新通过真机验收。项目发布包不再携带旧版测试报告副本；请阅读 [docs/VALIDATION.md](docs/VALIDATION.md) 中的本机和设备回归要求。

## 能力概览

- Windows 10/11 和 Ubuntu 24.04 原生运行，Python 3.11/3.12。
- DeepSeek Harness 同一个 `netops-all` Profile 同时加载 operator 与 approver 两个 stdio MCP 子进程。
- 支持传统 eNSP、eNSP Pro 和真实 Huawei/H3C/Cisco 设备的 SSH/Telnet CLI 接入；写配置仅允许 SSH。
- 持久 CLI 会话、只读命令、诊断基线、设备能力识别和厂商命令目录。
- 配置模板仅生成计划，不自动下发；审批后执行、验证、观察窗口确认和预先批准的回滚。
- 配置快照、审批命令和回滚命令加密存储；审计输出脱敏。
- 最多 20 台设备的顺序批量配置预检及失败后的逆序补偿回滚。
- SQLite 事务持久化、单一回滚调度主节点、异常恢复和配置差异分析。

## 一键启动

### Windows 10/11

1. 解压项目到普通本地目录（建议路径不要包含特殊字符）。
2. 双击 `START-NETOPS-WINDOWS.bat`。
3. 脚本会检查/安装 Python 3.12、创建虚拟环境、安装依赖、初始化数据库并创建同一个 `netops-all` Harness Profile，写入 operator/approver 两种身份。全新部署会生成 Fernet 密钥；已有数据库必须沿用原密钥，若密钥丢失或环境变量与 `.env` 冲突，安装器会停止而不是生成新密钥破坏旧凭证。
4. Harness 启动一次即可同时加载 operator 和 approver 工具。

### Ubuntu 24.04

```bash
# 进入项目目录
cd /opt/huawei-netops-mcp

# 一键安装、配置两个角色、检查数据库并启动 Harness（如本机有 dsh）
bash START-NETOPS-LINUX.sh
```

如果 Ubuntu 只运行 MCP、DeepSeek Harness 在 Windows，请先在 Ubuntu 执行上述脚本完成核心安装；随后在 Windows 的 `START-NETOPS-WINDOWS.bat` 中设置：

```bat
set "NETOPS_REMOTE_SSH_TARGET=ubuntuuser@192.168.1.20"
set "NETOPS_REMOTE_PROJECT_ROOT=/opt/huawei-netops-mcp"
```

再双击 Windows 入口即可生成两条远程 SSH stdio 连接。SSH 公钥登录和 host key 验证应先独立配置。

## 核心工具

| 功能 | MCP 工具 |
|---|---|
| 设备管理 | `device_add`、`device_list`、`device_test_connection` |
| 终端 | `netops_terminal`、`terminal_connect`、`terminal_execute`、`terminal_disconnect`、`terminal_sessions` |
| 只读命令 | `huawei_execute_command`、`huawei_execute_batch` |
| 诊断与识别 | `diagnose_device_basics`、`device_discover_capabilities`、`device_command_catalog` |
| 配置计划 | `config_template_list`、`config_template_render` |
| 审批与变更 | `config_request_approval`、`config_approve`、`config_apply_approved`、`config_apply_start` |
| 进度和确认 | `config_apply_progress`、`config_confirm_change`、`config_rollback_now` |
| 多设备编排 | `config_batch_apply_approved`、`config_batch_confirm` |
| 差异与审计 | `config_diff_transaction`、`audit_recent`、`netops_identity` |

完整工具权限和参数说明见 [docs/TOOLS.md](docs/TOOLS.md)。

运行安装只安装 MCP 必需依赖，不额外安装 pytest/ruff 等开发工具；需要在源码目录运行测试时，开发者再执行 `python -m pip install -e ".[dev]"`。

## 安全边界

- 未配置身份时默认 viewer；一键 Harness Profile 为 operator + approver 两个独立 MCP 子进程；双人审批默认开启。
- 同一 Harness 会话同时拥有两个角色工具，是逻辑角色隔离，不等于两个自然人的强制双人审批。
- 只读工具拒绝配置写命令和命令分隔/重定向；配置变更必须经审批、回滚计划和验证断言。
- 不要把明文密码直接写入审批命令；使用 `${NETOPS_SECRET_NAME}` 密钥引用。
- 不要将 `.env`、`data/`、数据库、Fernet 密钥、备份或日志加入发布包或 Git 仓库。
- 保留原有 `.env` 和 `data/netops.db` 时，升级不会主动清空用户设备、审批及审计数据；升级前必须备份数据库与其对应密钥。已有 SQLite 数据库但缺少密钥时，一键初始化会停止；不要生成新密钥覆盖旧密钥。进程环境中的 `CREDENTIAL_ENCRYPTION_KEY` 可用来恢复密钥，但与 `.env` 中已有密钥不一致时会拒绝启动。

安全设计见 [docs/SECURITY.md](docs/SECURITY.md)，变更和回滚说明见 [docs/ROLLBACK.md](docs/ROLLBACK.md)。

## 项目结构

```text
huawei-netops-mcp-v1.0.4/
├── START-NETOPS-WINDOWS.bat      # Windows 唯一启动入口
├── START-NETOPS-LINUX.sh         # Linux 唯一启动入口
├── app/                          # MCP、驱动、安全、业务和 SQLite 存储
├── docs/                         # 当前版本部署、安全、工具和设备接入说明
├── scripts/                      # 一键启动器内部调用的安装/配置脚本
├── tests/                        # 自动化回归测试
├── .env.example                  # 不含密钥的配置模板
└── pyproject.toml                # Python 项目元数据及依赖
```

## 升级原则

发布 ZIP 不包含实际数据库和密钥。升级时应在停止旧 MCP 子进程后备份 `.env` 和 `data/netops.db`，将新代码部署到新目录，沿用原数据库与原 Fernet 密钥，再运行一键启动脚本。不要将历史数据库与新生成密钥混用。
