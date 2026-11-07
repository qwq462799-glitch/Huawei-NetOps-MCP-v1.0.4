# MCP 工具清单（v1.0.4）

## 角色说明

MCP 工具按当前 MCP 进程的 `NETOPS_OPERATOR_ID` 与 `NETOPS_OPERATOR_ROLE` 鉴权。角色包括 viewer、operator、approver、admin。`NETOPS_REQUIRE_DUAL_APPROVAL=true` 时申请人与审批人必须为不同身份，且 apply 阶段再次校验审批记录。

## 设备管理

- `device_add(device)`：operator/admin 添加或更新设备；密码以 Fernet 加密保存。也可以填 `password_env`，其值优先从 MCP 进程环境读取，其次从项目 `.env` 读取。
- `device_list()`：所有角色可按权限策略查看登记设备；不返回密码和凭证环境变量名称。
- `device_test_connection(device_id)`：执行版本只读命令测试连接。
- `device_discover_capabilities(device_id)`：执行版本只读探测，返回厂商/型号/平台线索与命令目录；不会自动修改登记设备的 vendor/platform。
- `device_command_catalog(vendor="")`：查看 Huawei/H3C/Cisco 常见只读命令参考。

## Harness CLI 终端

- `netops_terminal(command_line)`：统一入口，支持 `help`、`devices`、`connect <device_id>`、`sessions`、`run <session_id> :: <read-only command>`、`disconnect <session_id>`。
- `terminal_connect(device_id)`：创建持久终端会话。
- `terminal_execute(session_id, command)`：执行一条只读命令。
- `terminal_sessions()`：查看当前 MCP 进程的会话。
- `terminal_disconnect(session_id)`：关闭会话。

会话保存在各 MCP 进程内存，不能跨 Harness Profile/进程共用 session_id。它不是 VT100/PTY；一次调用一条 CLI 命令，返回设备响应。敏感文本可能按脱敏规则遮盖。

## 只读命令与诊断

- `huawei_execute_command(device_id, command)`：执行单条只读命令。
- `huawei_execute_batch(device_id, commands)`：先整体策略预检；有写命令时整批拒绝且不执行；执行遇设备 CLI 错误或连接异常时停止，返回 `partial_results`。
- `diagnose_device_basics(device_id)`：采集版本、接口、路由、VLAN 等基线证据；按厂商选取命令。

`success` 表示设备是否接受命令，`tool_success` 表示 MCP/驱动调用链是否成功，`device_error` 指示设备 CLI 返回已识别错误签名。CLI 错误签名检测是 best-effort。

## 配置模板和差异

- `config_template_list(vendor="")`：列出已提供的只读模板目录。
- `config_template_render(device_id, template_id, parameters)`：渲染配置命令、回滚命令、验证断言和前置条件；不会下发设备。
- 当前模板：Huawei/H3C/Cisco VLAN 创建；Huawei/H3C/Cisco IPv4 静态路由添加。
- `config_diff_transaction(transaction_id, max_lines=1200)`：读取事务的变更前加密快照并与设备当前配置做脱敏文本差异；只读。

模板的配置与回滚命令必须按设备型号/版本人工核对，尤其 VRP8/CloudEngine 的 `commit` 位置、现有 VLAN/路由是否存在，以及恢复已有对象时需要的参数。

## 审批、执行和回滚

- `config_request_approval(...)`：operator/admin 创建审批单；必须给配置命令、回滚命令、只读验证命令和至少一条验证断言。审批前执行命令归一化预检。
- `config_approve(approval_id)`：approver/admin 批准。双人审批开启时创建人不能自批。
- `config_apply_approved(approval_id)`：operator/admin 同步执行已批准变更；进度用 MCP progress notification 上报。
- `config_apply_start(approval_id)`：operator/admin 启动后台异步变更任务。
- `config_apply_progress(approval_id)`：查询任务持久化进度、事件时间线和最终执行结果。
- `config_confirm_change(transaction_id)`：approver/admin 确认业务正常，取消观察窗口到期回滚。
- `config_rollback_now(transaction_id)`：approver/admin 对待确认事务执行预先批准的回滚。

写配置当前只支持 SSH；传统 eNSP Telnet 仅只读。

## 多设备变更编排

- `config_batch_apply_approved(approval_ids, rollback_previous_on_failure=true)`：operator/admin 对最多 20 张已批准审批单逐台执行。全量 preflight 会检查审批状态、设备存在/启用、SSH、双人审批记录、命令策略、验证断言和 `${NETOPS_SECRET_*}` 占位符；全部通过才开始第一台设备。
- 运行时首个失败即停止；若启用补偿，则逆序回滚此前成功事务。
- `config_batch_confirm(transaction_ids)`：approver/admin 逐笔确认；单笔异常会保留在该笔结果中，并继续处理后续事务；不是跨设备原子确认。

结果状态：
- `pending_confirmation`：全部设备执行及验证流程正常，需逐笔业务确认。
- `failed_no_prior_changes`：首台失败，无此前成功设备。
- `failed_compensated`：此前成功设备均已成功补偿回滚。
- `failed_compensation_incomplete`：至少一笔补偿未成功或状态不明确，必须人工核查。
- `failed_partial`：调用时关闭了失败补偿，后续设备停止，可能存在部分配置，需要人工处置。

## 审计和身份

- `audit_recent(after_id=0, limit=100)`：approver/admin 查看增量审计事件。
- `netops_identity()`：查看当前 MCP 进程身份和角色。

身份取自每个 MCP 子进程环境，不由模型传参。默认 `netops-all` Profile 会加载两个独立 MCP 子进程：`huawei_netops_operator` 和 `huawei_netops_approver`。同一个 Harness 会话同时可访问两类工具，属于逻辑身份隔离，不等于两个自然人的强制双人审批；强双人审批需不同 OS 用户/独立会话或外部审批服务。

## 参数兼容

命令数组使用 `StrList` 类型。正常数组按原样接收；个别客户端将数组序列化为 JSON 字符串时尝试还原；空串转成空列表。对外 MCP schema 保持 `array<string>`。
