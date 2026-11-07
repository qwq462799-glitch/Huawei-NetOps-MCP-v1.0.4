# Huawei NetOps MCP v1.0.4

## Clean release

- 清理旧单角色安装/启动辅助脚本、重复入口和手工 Harness 配置样例。
- 统一版本元数据、配置模板、安装说明与 SHA256 文件清单。
- 默认 RBAC 降为 viewer，双人审批默认开启。
- 收紧只读 CLI 管道策略，修正 Cisco `no shutdown` 误拦截。
- 确保 `${NETOPS_SECRET_*}` 在执行前才解析，明文不进入审批/事务存储。
- 加强设备输入模型校验、持久终端会话上限和 POSIX 文件权限。
- 修正 Huawei/H3C 静态路由命令生成及数字参数校验。
- 将诊断命令统一到厂商命令目录，修复 Harness Profile YAML 原子写入。
- 删除无调用方的旧 storage API 和兼容别名；保留现有 SQLite 非破坏性 schema 迁移。

- 清洁发布继续移除未被代码/文档引用的设备 YAML 样例目录，设备统一通过 `device_add` 管理。
- 修复 `DATABASE_URL` / `CREDENTIAL_ENCRYPTION_KEY` 空值解析跨行问题；检查进程环境变量优先级，已有数据库缺少密钥时禁止自动生成新密钥。
- 新事务加密冻结当次解析的回滚命令和密钥值，环境变量轮换不会改变待回滚命令；扩展旧数据库的非破坏性字段迁移。
- 传统 eNSP 未显式指定连接方式时默认 Telnet；eNSP Pro / 物理设备默认 SSH。
- 限制单笔配置/回滚计划各 100 条、单次只读命令批量 50 条；Ubuntu 安装流程可在最小化系统中先安装 Python 3.12，Windows winget 安装后增加标准路径探测。
- Windows 远程 Ubuntu 模式增加 SSH 后的远程 doctor 检查。
- 一键生产安装仅安装运行依赖，不再默认安装 pytest/ruff 开发工具；开发测试依赖改为可选 extras。
- 最终清洁包剔除历史真机测试报告副本和现场设备输出；测试证据仍由用户原始报告保留，避免混入旧版测试数据。
