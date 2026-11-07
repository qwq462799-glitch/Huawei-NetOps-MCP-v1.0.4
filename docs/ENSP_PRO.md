# eNSP Pro 接入说明

## 结论

**可条件式接入 eNSP Pro：如果当前版本/模拟设备向 MCP 主机暴露了可达的设备管理 IP 和 SSH/Telnet 端口，就可以接入；并非所有镜像/部署网络都保证可达。它不是直接连接 eNSP Pro 的 Web 管理页面或沙箱 API。** 本项目把 eNSP Pro 内启动的华为模拟路由器/交换机当作普通 Huawei VRP CLI 设备，通过设备管理面 SSH 或 Telnet 连接。

华为公开资料说明，eNSP Pro 是虚机镜像形式部署的模拟器，设备启动后可登录并配置；产品文档还列出模拟设备管理端口的远程管理方式（Telnet/SSH/HTTP(S)）。因此本项目复用现有 SSH/Telnet 驱动，而不是依赖未经确认的内部接口。

## 接入前提

1. eNSP Pro 单机版已部署并启动，沙箱已创建，目标模拟设备已启动。
2. 确认目标模拟设备确实暴露可从 MCP 主机访问的管理 IP/端口；若镜像允许，配置管理 IP、路由和 SSH（推荐）或 Telnet 服务。
3. Windows/Ubuntu MCP 主机能够三层访问该管理 IP；虚拟交换网络、桥接/NAT、宿主机防火墙和 ACL 均需允许对应端口。
4. 设备账号具有所需的只读权限；配置写操作还必须满足现有审批、验证和回滚流程。
5. 先从运行 MCP 的 Windows 或 Ubuntu 主机验证端口可达，再添加设备。

注意：eNSP Pro 的登录 Web 地址（例如管理平台的 HTTPS 端口）不是模拟设备 CLI 地址。不要把 eNSP Pro 平台的 8443 或 Linux 物理管理端口误填成设备 SSH 端口。应填写模拟设备自己的管理 IP 和 CLI 端口。

## 设备配置示例

在 Harness 中调用 `device_add` 添加设备；下面的 YAML 仅展示字段结构，不会由程序自动读取。按实验环境修改 IP、账号和密码环境变量：

```yaml
devices:
  - id: ensppro-r1
    name: eNSP Pro Router R1
    vendor: huawei
    platform: huawei_vrp
    connection: ssh
    host: 192.168.100.11       # 模拟设备的管理 IP，不是 eNSP Pro Web 地址
    port: 22                   # 模拟设备 SSH 端口
    username: netops
    password_env: ENSPPRO_R1_PASSWORD
    enabled: true
    environment: lab
```

在 `.env` 中设置凭证：

```bash
# 设置 eNSP Pro 模拟设备登录密码环境变量
ENSPPRO_R1_PASSWORD='替换为实验设备密码'
```

## 从 MCP 主机测试管理面连通性

```bash
# 测试模拟设备 SSH 端口是否可达
nc -vz 192.168.100.11 22

# 如果实验设备仅启用 Telnet，测试对应 Telnet 端口
nc -vz 192.168.100.11 23

# 手工测试 SSH 登录；首次连接先核对设备主机密钥指纹
ssh -p 22 netops@192.168.100.11
```

## 功能范围

| 功能 | eNSP Pro 模拟设备 | 说明 |
|---|---|---|
| 设备登记 | 支持 | 作为 Huawei VRP 设备登记 |
| SSH 只读 CLI | 支持 | 需设备管理 IP/SSH 服务可达 |
| Telnet 只读 CLI | 有条件支持 | 需要设备启用 Telnet；当前 Telnet 实现使用 Python 3.12 的 `telnetlib` |
| 配置快照 | 有条件支持 | 取决于设备镜像支持的 `display current-configuration` |
| SSH 配置变更 | 有条件支持 | 经过审批、验证和自动回滚；先在同镜像实验环境验证回滚命令 |
| eNSP Pro 沙箱/拓扑自动发现 | 不支持 | 当前没有调用 eNSP Pro 私有/平台 API |
| 通过 eNSP Pro Web UI 代理 CLI | 不支持 | 需要独立适配器，当前不是该架构 |

## 排错顺序

1. 确认设备已启动且管理 IP 正确。
2. 从 MCP 主机执行 `ping -c 4 <管理IP>`（设备或网络可能禁 ping，ping 失败不等于 TCP 不通）。
3. 执行 `nc -vz <管理IP> 22` 检查 SSH 端口。
4. 从运行 MCP 的主机手工 SSH 登录，确认账号、密码、密钥算法和 VRP 提示符正常。
5. 登录后手工执行 `display version` 和 `display current-configuration`，确认镜像命令兼容。
6. 再将设备加入 MCP，并先做只读测试，最后才在实验设备上验证写配置和回滚。

## 安全提示

- eNSP Pro 是实验环境，也可能连通真实网络；不要把实验管理网无条件桥接到生产管理网。
- 优先 SSH，限制来源 IP，使用专用低权限账号；Telnet 明文传输，不建议跨不可信网络。
- 不要将 设备 CLI 管理端口直接暴露公网。
