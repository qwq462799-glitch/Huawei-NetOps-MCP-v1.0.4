# 一键安装与启动

本项目仅通过 DeepSeek Harness stdio 接入，不包含独立 Web Dashboard、HTTP MCP 服务或 Docker 部署。

## Windows 10/11

1. 解压完整发布包。
2. 双击项目根目录 `START-NETOPS-WINDOWS.bat`。
3. 一键脚本会检查 Python 3.11/3.12；找不到时尝试使用 winget 安装 Python 3.12。
4. 自动创建 `.venv`、安装当前项目依赖、全新部署生成 `.env` 中的 Fernet 密钥；已有数据库必须复用原密钥，如果数据库已存在而密钥缺失、无效或与进程环境密钥冲突，初始化会安全停止，不会自动换钥破坏旧凭证。随后初始化 SQLite 并检查依赖和 RBAC。
5. 自动创建/更新一个 `netops-all` Harness Profile，其中包含 operator 与 approver 两个独立 stdio MCP 实例。
6. 最后只启动一次 `dsh --profile netops-all`。

## Ubuntu 24.04

```bash
# 进入项目目录
cd /opt/huawei-netops-mcp

# 执行唯一的一键启动入口
bash START-NETOPS-LINUX.sh
```

若本机未安装 DeepSeek Harness CLI，脚本仅安装 MCP 核心、初始化密钥/数据库并自检，然后退出；不会将 stdio MCP 错误地作为无客户端后台服务运行。

## Windows Harness 连接 Ubuntu MCP

先在 Ubuntu 端执行一次 `bash START-NETOPS-LINUX.sh`，完成核心环境安装。然后编辑 Windows 根目录 `START-NETOPS-WINDOWS.bat`，设置：

```bat
set "NETOPS_REMOTE_SSH_TARGET=ubuntuuser@192.168.1.20"
set "NETOPS_REMOTE_PROJECT_ROOT=/opt/huawei-netops-mcp"
```

确保 Windows OpenSSH Client 可用、SSH 公钥登录已配置且 Ubuntu SSH host key 已核验。再次双击 Windows 启动入口。Windows Harness 将在同一个 Profile 中建立两条远程 `ssh.exe -T` stdio 连接。

## 身份说明

| MCP serverName | 身份 ID 默认值 | 角色 |
|---|---|---|
| `huawei_netops_operator` | 当前账户名 + `-operator` | operator |
| `huawei_netops_approver` | 当前账户名 + `-approver` | approver |

可通过 `NETOPS_OPERATOR_ID`、`NETOPS_APPROVER_ID`、`NETOPS_PROFILE` 覆盖默认值。两个身份 ID 必须不同，双人审批由一键启动 Profile 强制开启。

同一个 Harness 会话同时加载两个角色，方便日常运维，但不能证明由两个不同自然人分别操作。生产级双人控制必须使用不同 OS 账户、独立 Harness 会话或外部审批服务。

## 不建议手工运行的内部脚本

`START-NETOPS-WINDOWS.bat` 和 `START-NETOPS-LINUX.sh` 是用户入口。`scripts/` 中的安装器、Profile 写入器和 bootstrap 脚本由启动器内部调用；日常使用不需要逐个执行。

## 开发/测试依赖（普通使用者不需要）

若要运行项目自动化测试，在项目虚拟环境中执行：

```bash
# 安装 pytest、pytest-asyncio 和 ruff 等开发工具
python -m pip install -e ".[dev]"

# 执行全量自动化回归
python -m pytest -q -p no:cacheprovider
```
