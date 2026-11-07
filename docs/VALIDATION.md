# v1.0.4 代码审查与验证范围

## 交付包清洁性

- 发布 ZIP 不包含真实 `.env`、`data/`、SQLite 数据库、Fernet 密钥、日志、备份、`.venv`、`__pycache__`、`.pyc`、egg-info 或构建目录。
- 删除旧的单角色配置辅助脚本、重复 Windows 安装/doctor 入口、手工 Harness YAML 样例、旧启动/停止脚本和未使用备份脚本。
- 只保留根目录两个用户启动入口及其实际调用的当前脚本。
- 所有发布文件均列入 `MANIFEST.json`，含 SHA256。

## 审查时修复

- `pyproject.toml` 项目版本更新为 1.0.4，移除项目未直接使用的 `paramiko`、`httpx`、`rich` 和未实现的 Netconf/SNMP 可选依赖（相关传递依赖由 FastMCP/Netmiko 自行声明）。
- 无身份环境变量时 RBAC 默认降为 viewer，双人审批默认开启；身份 ID 增加字符白名单校验。
- 只读 CLI 允许的管道过滤器改为 allowlist，拒绝 redirect/tee/save/execute、重定向符号和多级管道。
- 修正 Cisco `no shutdown` 被高危规则误拒绝的问题；裸 `shutdown` 仍禁止。
- 密钥占位符在审批阶段以引用形式保存并加密；下发前才在 MCP 进程内解析。新事务把当次解析出的最终回滚命令和实际密钥值分别 Fernet 加密冻结到事务记录，明文不写入审批/事务字段或审计。
- 设备登记模型增加 ID、主机地址、端口、用户名、凭证来源和控制字符校验。
- Huawei/H3C 静态路由模板改为网络地址 + 前缀长度格式，偏好值/管理距离必须是整数，拒绝浮点截断。
- 诊断命令从统一厂商命令目录派生，避免目录重复维护。
- 持久终端会话增加总量和单设备并发上限；中断变更恢复等待窗口与回滚 worker 的 30 分钟安全阈值保持一致。
- Harness Profile YAML 写入先在临时文件生成并校验，再备份和替换，避免校验失败破坏原配置。
- Bootstrap 在 POSIX 系统限制 `.env`、SQLite 文件及默认数据目录权限；现有数据库缺失原 Fernet 密钥时 fail-closed，不会生成新密钥覆盖数据；检查进程环境优先级与 `.env` 一致性。
- 传统 eNSP 未显式指定连接方式时默认 Telnet，eNSP Pro 和真实设备默认 SSH。
- Windows winget 安装后即使当前 PowerShell PATH 未刷新，也会尝试 Python 官方标准安装路径；Windows→Ubuntu 模式增加远程 `netops doctor` 检查。
- Ubuntu 首次安装会先安装 Python 3.12/venv 系统包，再创建虚拟环境，支持最小化 Server 镜像。
- 删除无调用方的 `consume_approval`、`get_transaction_by_id`、`mark_interrupted_rollbacks_failed` 和 SSH 驱动旧归一化别名。

## 自动化验证

发布前执行：

- Python 源码编译检查。
- pytest 全套回归测试。
- 当前 Linux Bash 入口和 Profile 写入器 `bash -n`。
- Harness YAML 生成器的模拟 CLI 集成测试和幂等测试。
- 设备模型/命令策略/密钥占位符/审批和回滚/批量编排的单元回归。
- 发布 ZIP CRC 与 MANIFEST SHA256 对照。

本次清洁工作区全套回归结果：`137 passed`。测试应使用 `python -m pytest -q -p no:cacheprovider`；项目 pytest 配置同时加入根目录 Python 路径，直接 `pytest` 也能从项目根目录导入 `app`。最终 ZIP 解压复测结果以交付时实际输出为准。

本次清洁版回归测试包含 bootstrap 密钥保护、数据库 URL 环境变量覆盖、模拟器默认传输、双角色 Profile 幂等配置等新增场景。测试数量及最终命令结果以本次发布报告和实际最终 ZIP 解压复测输出为准。

## 真机验证证据与边界

用户在本对话中提供的《华为 NetOps MCP 真机功能测试报告》（2026-11-06）记录了 v0.5.0-fixed 在 eNSP Pro CloudEngine CE6800 / YunShan OS 上的 SSH 连接、只读命令、持久终端、审批变更、加密快照、确认和自动/手动回滚结果。该原始报告不随 v1.0.4 代码 ZIP 重复分发，也不证明后续新增 RBAC、模板、多设备编排及本次安全策略修改已经在真实设备上复测。

当前构建容器是 Python 3.13，项目运行支持范围为 Python 3.11/3.12，且没有 Windows PowerShell、DeepSeek Harness CLI、Netmiko/FastMCP 运行时和真实网络设备。因此自动化测试不等同于 Windows 本机启动、Harness 实际加载、eNSP/eNSP Pro 网络联通或真实设备回归。发布后应先在 Python 3.12 环境执行 `netops doctor` 和 pytest，再按以下顺序在隔离实验设备复测：

1. 注册设备并验证 SSH/Telnet 连接；确认传统 eNSP 默认 Telnet，eNSP Pro/真实设备默认 SSH。
2. 执行版本、接口、VLAN、路由只读命令及管道过滤，确认 CLI 错误能与传输错误区分。
3. 验证 operator 无法审批、approver 无法发起变更；同一身份不能自批。
4. 在实验 VLAN 上执行申请、审批、下发、输出断言、确认以及手动/定时回滚。
5. 验证 `${NETOPS_SECRET_*}` 的加密存储、回显脱敏，以及密钥轮换时历史事务使用冻结值回滚。
6. 执行两台及以上实验设备的批量预检、首台失败、后续设备失败和逆序补偿回滚。
7. 在观察窗口和配置下发阶段分别模拟 MCP 重启、设备离线和回滚失败，核对事务状态及人工恢复提示。
