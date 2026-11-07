# 模拟器适配器：传统 eNSP 与 eNSP Pro

本项目将模拟器平台识别与 CLI 传输分开：

- `simulator: ensp`：传统 eNSP 适配器。默认连接方式为 Telnet，但必须填写拓扑中该节点真实映射的 Console host/port；若设备已启用 SSH，也可显式设置 `connection: ssh`。
- `simulator: ensp_pro`：eNSP Pro 适配器。默认连接方式为 SSH；必须填写运行 MCP 的 Windows/Ubuntu 主机可达的**模拟设备 CLI 管理 IP/端口**。不得填写 eNSP Pro 平台 Web/API 管理地址。
- 真实设备不填写 `simulator`，继续使用通用 SSH 驱动。

## 统一设备模型

以下 YAML 是设备字段参考；设备需通过 Harness 的 `device_add` MCP 工具登记，或由部署者自行实现导入。

```yaml
- id: lab-r1
  name: Lab Router
  simulator: ensp_pro       # ensp 或 ensp_pro；真实设备省略
  vendor: huawei
  platform: huawei_vrp
  connection: ssh           # ssh 或 telnet
  host: 192.168.100.11      # 模拟设备 CLI 可达地址
  port: 22
  username: netops
  password_env: LAB_R1_PASSWORD
  enabled: true
  environment: lab
```

## 连通性验证

```bash
# 检查 MCP 主机到模拟设备 SSH 端口的 TCP 连通性
nc -vz 192.168.100.11 22

# 使用设备账号手动验证 SSH 登录
ssh -p 22 netops@192.168.100.11

# 登录设备后查看 VRP 版本
display version

# 查看设备当前配置
display current-configuration
```

## 当前能力边界

1. 适配器负责平台识别、连接默认值和必要字段校验；实际 CLI 由 SSH/Telnet 驱动执行。
2. 传统 eNSP 的 Console 端口映射依拓扑和运行环境而异，项目不会猜测端口。
3. eNSP Pro 的设备可达地址、NAT/桥接/管理网络路由需由部署者确认。
4. 设备镜像可能在 SSH/Telnet 登录提示符、分页、命令语法上存在差异，必须逐镜像实验验证。
5. 当前配置写入仍受审批和回滚机制约束；Telnet 仅只读。
6. 本适配器并不调用 eNSP/eNSP Pro 平台私有 API，也不自动发现拓扑或启动虚拟设备。
