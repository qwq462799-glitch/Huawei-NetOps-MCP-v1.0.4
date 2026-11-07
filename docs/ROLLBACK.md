# 配置变更与自动回滚

## 工作流程

1. `config_request_approval` 创建变更单，必须包含：
   - `commands`：本次配置命令；
   - `rollback_commands`：经工程师核对的补偿/恢复命令；
   - `verify_command`：只读验证命令；
   - `expected_output_contains`：兼容旧版的单条包含断言（可选）；
   - `expected_output_contains_all`：所有指定文本都必须出现；
   - `expected_output_not_contains`：所有指定文本都必须不存在，用于验证删除动作；
   - `expected_output_regex`：所有正则表达式都必须匹配；至少提供上述一类断言。
   - `rollback_after_seconds`：确认窗口，30 秒至 24 小时，默认 300 秒。
2. `config_approve` 批准变更。
3. `config_apply_approved` 或 `config_apply_start`：
   - 读取设备 running-config 并加密存储快照；
   - 在任何配置写命令下发前，将审批消费和 SQLite `applying` 事务创建原子提交，并持久化加密快照和已批准的回滚命令；
   - 通过 SSH 单会话执行配置；本次解析出的 `${NETOPS_SECRET_*}` 值及最终回滚命令在事务中用 Fernet 加密冻结，后续环境变量轮换不会改变本次回滚计划；
   - 执行验证命令；
   - 检查配置下发回显是否含已知设备 CLI 错误；
   - 验证不匹配、设备端返回 CLI 错误或执行异常时立即运行回滚命令；
   - 验证成功时建立持久化回滚期限。
   - 若使用异步 `config_apply_start`，可重复调用 `config_apply_progress(approval_id)` 查看阶段事件；任务进程异常退出后标记为 `interrupted`，不会自动重放变更。
4. 工程师完成业务验证后调用 `config_confirm_change`。
5. 若观察窗口到期仍未确认，后台 worker 执行回滚。
6. `config_rollback_now` 可在观察窗口内提前回滚。

## 视图命令与两阶段提交（VRP8）

Netmiko 的 `send_config_set()` 自己负责进入配置视图，所以审批单里**不要**写 `system-view`。驱动层会剥离命令列表最外层的视图封装：

- 剥离开头的 `system-view` / `sys` / `configure terminal` / `conf t`；
- 剥离结尾的 `return` / `end` / `exit` / `quit`；
- 保留中间的 `quit`，用于"接口视图 → 系统视图"的正常切换。

在 CloudEngine / YunShan OS（VRP8）上，设备默认两阶段生效，配置写入候选配置库后必须 `commit` 才生效：

```text
commands          = ["vlan 100", "description NETOPS-TEST", "commit"]
rollback_commands = ["undo vlan 100", "commit"]
```

- `commit` 必须由调用方显式放入 `commands` 和 `rollback_commands` 的最后一条，驱动不会自动追加。
- 未 `commit` 时工具可能"执行成功"，但设备运行配置没有变化，后续 `display` 验证会失败。
- VRP8 提示符 `[*HUAWEI]` 表示存在未提交配置，`[~HUAWEI]` 表示已提交。
- 已在 CE6800（YunShan OS V300R025C10SPC500）上验证：剥离视图命令后回滚输出不再出现重复 `system-view` 导致的 `Unrecognized command`。

## 重要设计限制

- 目前配置变更和回滚仅允许 SSH；eNSP Telnet 仍为只读。
- 设备配置快照是加密留存的审计/人工恢复材料，不会被盲目整份覆盖回设备。
- 回滚依赖审批时明确提供的 `rollback_commands`。工具不会猜测“反向命令”。
- 回滚命令必须先在相同厂商、型号、软件版本的实验设备上验证。
- 自动回滚失败会标记 `rollback_failed` 并记录审计；需要人工介入。
- 当前回滚观察窗口由运行 MCP 的 Windows 或 Ubuntu 进程后台线程执行。进程重启后会从 SQLite 恢复待到期任务；若设备变更执行中进程退出，启动时识别 `applying` 事务并尝试执行已批准回滚。若进程在回滚执行中退出，事务标记为 `rollback_failed`，不会盲目重放，必须人工检查设备状态。若主机断电且设备网络中断，回滚只能在服务恢复并重新可达设备后执行。
- 多个 Harness stdio MCP 子进程可以共用同一 SQLite 数据库；rollback worker 使用 filelock 选举单一调度主节点。各 MCP 进程的设备 CLI 会话仍彼此隔离，不能跨进程共用 session_id。
- 生产网络需要双路管理通道/OOB、AAA 最小权限、变更窗口、设备侧配置回退能力和人工值守。
- 不应把“命令已发送”当成“业务恢复”。必须使用真实设备状态和业务探测验证。

## 示例：Huawei VRP VLAN 变更

以下命令仅作实验示例，接口、VLAN 和验证输出需按现场设备确认：

变更命令：
```text
vlan 100
quit
interface GigabitEthernet0/0/1
port link-type access
port default vlan 100
quit
commit
```

回滚命令：
```text
interface GigabitEthernet0/0/1
undo port default vlan
undo port link-type
quit
undo vlan 100
commit
```

验证命令：
```text
display port vlan
```

文本匹配会先移除 ANSI 颜色码并折叠多余空白。`expected_output_not_contains` 可验证删除结果；`expected_output_regex` 默认忽略大小写并启用多行匹配。所有提供的断言均需通过。设备 CLI 输出若存在 `...`/`…` 且断言失败，工具会提示可能被截断，但不会自动放宽条件。请优先使用设备实际回显中短且唯一的片段，或将验证命令改为针对具体对象的查询。不要在未验证回滚命令语义前提交生产变更。

## 历史事务的密钥兼容注意事项

v1.0.4 以前创建的未完成事务仍按旧格式保存命令占位符。升级后在这些事务全部确认或回滚之前，不要变更其引用的 `NETOPS_SECRET_*` 环境变量。v1.0.4 新建的事务会冻结当次解析结果并加密保存。

## 多设备批量变更

`config_batch_apply_approved` 只接受已批准的审批单，并在第一条设备写命令前对整批做本地预检。预检包括设备存在/启用、SSH、双人审批身份、命令归一化与策略、验证断言、密钥占位符和设备驱动构建。全部通过后逐台执行；首个失败后停止后续设备，并按逆序补偿此前成功事务。

批量状态 `failed_compensation_incomplete` 表示逆序补偿至少有一台失败或状态不确定，必须人工核查设备运行配置。批量处理不是跨设备原子事务，不能把成功的单台回滚等同于全网一致性。

## 数据库状态

- `applying`：变更事务已在写入前持久化，配置命令正在下发/验证；进程重启时会尝试执行预先批准的回滚。
- `pending_confirmation`：变更已验证，等待人工确认；到期会自动回滚。
- `confirmed`：已确认，定时回滚取消。确认后不能再 `config_rollback_now`，需要新建审批单。
- `rolling_back`：回滚执行中；手动和到期回滚通过数据库条件更新抢占该状态，避免并发重复执行。
- `rolled_back`：回滚命令执行完成（仍需后续业务验证）。
- `rollback_failed`：回滚失败或 MCP 在回滚期间退出，必须人工核查设备真实配置后处理。
