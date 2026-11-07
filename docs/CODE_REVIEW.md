# v1.0.4 全项目代码审查记录

## 审查目标

以 v1.0.3 双角色一键版为唯一源代码基线，清理已废弃启动路径和运行时遗留物，并对当前保留的 Python 应用、设备驱动、MCP 工具、存储、安全策略、回滚流程和跨平台启动器进行静态审查与自动化回归。

## 当前保留结构

- `app/`：唯一运行代码；包括 MCP 注册、设备模型、SSH/Telnet 驱动、eNSP/eNSP Pro 适配、安全/RBAC、SQLite 存储和业务服务。
- `scripts/`：仅保留两个根入口实际依赖的安装、bootstrap、Harness 双角色配置和一键启动脚本。
- `docs/`：当前版本部署、安全、工具、设备接入、回滚、验证和代码审查文档；旧版测试报告副本和设备输出不随代码发布。
- `tests/`：当前版本自动化回归测试。

## 删除的历史/冗余文件

- 旧版单角色 Harness 配置器及手工 `.yml` 示例。
- 旧 `install.sh`、`start.sh`、`stop.sh`、PowerShell 启停入口和重复 Windows 安装/doctor BAT。
- 未被启动器、源码或文档调用的 `backup.sh`。
- 未被当前实现调用的设备 YAML 样例目录。
- 为已删除 Harness 配置器服务的旧专用测试。
- 未被任何调用方使用的 storage API 旧别名。

## 保留而不删除的兼容代码

SQLite schema migration、旧审批/事务字段读取兼容和加密标记迁移仍保留。这些代码不是旧启动器，而是升级已有用户数据库所必需。删除会使历史数据无法安全迁移。发布 ZIP 不携带用户 `.env`、SQLite 数据库、设备凭证、真实配置快照、旧版测试报告副本、设备输出、日志、缓存或虚拟环境。

## 修复的问题

1. 未配置身份默认降级为 `viewer`，不默认获得 `admin`。
2. `.env` 路径锚定项目根目录；进程环境变量优先；已有数据库缺失 Fernet 密钥时 fail-closed。
3. 新变更事务加密冻结解析后的回滚命令与密钥值，避免观察窗口中密钥轮换使回滚引用新密码；回显和审计执行脱敏。
4. 设备列表字段白名单，避免输出凭证及内部存储标志。
5. SQLite WAL 只在 schema 锁内初始化，不在每次工具调用重复切换。
6. 只读命令管道改为过滤器 allowlist；拒绝多命令分隔、重定向和不安全管道尾部。
7. 限制只读批量、单笔配置计划和回滚计划长度；验证正则过滤高风险回溯结构。
8. 修复 Huawei/H3C/Cisco 命令模板参数校验与 Cisco `no shutdown` 判定。
9. 传统 eNSP 未显式指定连接类型时选择 Telnet；eNSP Pro/真实设备默认 SSH；配置写入仍只允许 SSH。
10. 变更申请提前验证归一化后的命令；审批消费和 `applying` 事务原子提交；回滚状态通过 SQLite 条件更新抢占。
11. 一键 Profile 中同时注册 operator/approver 两个 stdio MCP 子进程；共用数据库/密钥但身份、工具命名空间和终端会话隔离。
12. Bootstrap 通过原子写入 `.env`、POSIX 最小权限和 Fernet key/database consistency 检查降低初始化风险。

## 检查覆盖

- Python 源码：全部 AST 解析、compileall；全 `app/` Python 文件未发现未使用 import。
- 依赖声明：直接依赖列表与源码引用核对；已移除依赖无残余直接引用。
- Shell：根 Linux 入口和所有保留 `.sh` 执行 `bash -n`。
- 测试：全套 pytest 回归，当前工作区 `137 passed`。
- 发布文件：打包前剔除 `.env`、`data/`、数据库、缓存、`.pyc`、`.venv`、构建目录；`MANIFEST.json` 列出发布文件 SHA256。

## 未能在本构建环境执行的验证

- 当前容器为 Python 3.13.5，项目声明运行范围为 Python 3.11/3.12；测试在 3.13.5 上执行，不等于目标运行时验证。
- 容器没有 PowerShell，因此 Windows `.ps1` 经过源码审查和配置逻辑测试，但未用 Windows PowerShell 实际解释执行。
- 本次没有可用 DeepSeek Harness CLI、FastMCP/Netmiko 真实运行栈、eNSP/eNSP Pro 或网络设备，因此未完成 MCP 客户端启动、设备 SSH/Telnet 和新功能真机联调。
- 用户提供的 CE6800 真机报告只证明 v0.5.0-fixed 的原始功能基线，不证明 v1.0.4 的 RBAC、模板、批量编排和新增事务加密功能已经实机验收。

## 部署建议

先在 Python 3.12 的 Windows 或 Ubuntu 环境完成一键启动、Harness Profile 加载和 `netops doctor`；再在隔离实验设备验证 SSH/Telnet、双角色、密钥占位符、配置差异、批量变更与逆序补偿回滚；完成这些验证前，不应直接对生产网络批量下发。
