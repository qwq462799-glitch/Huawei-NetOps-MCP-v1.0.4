#!/usr/bin/env bash
# 将 operator 与 approver 两个 MCP stdio 实例原子写入同一个 Harness Profile。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-netops-all}"
OPERATOR_ID="${2:-${NETOPS_OPERATOR_ID:-local-operator}}"
APPROVER_ID="${3:-${NETOPS_APPROVER_ID:-local-approver}}"
DUAL_APPROVAL="${4:-true}"

[[ "$PROFILE" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || { echo "Harness Profile 名称不合法" >&2; exit 1; }
[[ "$OPERATOR_ID" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || { echo "operator ID 格式不合法" >&2; exit 1; }
[[ "$APPROVER_ID" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || { echo "approver ID 格式不合法" >&2; exit 1; }
[[ "$OPERATOR_ID" != "$APPROVER_ID" ]] || { echo "operator 与 approver ID 必须不同" >&2; exit 1; }
[[ "$DUAL_APPROVAL" == "true" ]] || { echo "本发布版本的一键双角色 Profile 强制启用双人审批" >&2; exit 1; }

PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || { echo "请先运行 START-NETOPS-LINUX.sh 完成环境安装" >&2; exit 1; }
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
PROFILE_DIR="$DSH_HOME/profiles/$PROFILE"
PATCH_FILE="$PROFILE_DIR/cordis.patch.yml"
mkdir -p "$PROFILE_DIR"
chmod 700 "$PROFILE_DIR"

BEGIN="# BEGIN HUAWEI NETOPS MCP BOTH ROLES"
END="# END HUAWEI NETOPS MCP BOTH ROLES"
TMP="$(mktemp "$PROFILE_DIR/.cordis.patch.XXXXXX")"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

if [[ -f "$PATCH_FILE" ]]; then
  BEGIN_COUNT="$(grep -Fxc "$BEGIN" "$PATCH_FILE" || true)"
  END_COUNT="$(grep -Fxc "$END" "$PATCH_FILE" || true)"
  [[ "$BEGIN_COUNT" == "$END_COUNT" && "$BEGIN_COUNT" -le 1 ]] || {
    echo "NetOps 双角色托管标记不完整或重复，已停止修改：$PATCH_FILE" >&2; exit 1;
  }
  awk -v b="$BEGIN" -v e="$END" '
    $0 == b {skip=1; next}
    $0 == e {skip=0; next}
    !skip {print}
  ' "$PATCH_FILE" > "$TMP"
  # DSH 新建 Profile 时可能写入一个空数组文档；移除它后写入 Cordis list。
  sed -i -E '/^[[:space:]]*\[\][[:space:]]*(#[^#]*)?$/d' "$TMP"
else
  : > "$TMP"
fi

# YAML 单引号字符串转义：路径中若含单引号，必须按 YAML 规范重复单引号。
yaml_quote() {
  local value="$1"
  value="${value//\'/\'\'}"
  printf "'%s'" "$value"
}
PYTHON_YAML="$(yaml_quote "$PYTHON")"
ROOT_YAML="$(yaml_quote "$ROOT")"

cat >> "$TMP" <<EOF

$BEGIN
- insert:
    - id: mcp-huawei-netops-operator
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: huawei_netops_operator
        transport: stdio
        command: $PYTHON_YAML
        args: ['-m', 'app.main']
        cwd: $ROOT_YAML
        env:
          PYTHONUTF8: '1'
          PYTHONIOENCODING: 'utf-8'
          NETOPS_OPERATOR_ID: '$OPERATOR_ID'
          NETOPS_OPERATOR_ROLE: 'operator'
          NETOPS_REQUIRE_DUAL_APPROVAL: 'true'
        toolCallTimeoutMs: 120000
        failOnStartupError: true
        reconnect:
          enabled: true
          initialDelayMs: 500
          maxDelayMs: 10000
          maxAttempts: 8
    - id: mcp-huawei-netops-approver
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: huawei_netops_approver
        transport: stdio
        command: $PYTHON_YAML
        args: ['-m', 'app.main']
        cwd: $ROOT_YAML
        env:
          PYTHONUTF8: '1'
          PYTHONIOENCODING: 'utf-8'
          NETOPS_OPERATOR_ID: '$APPROVER_ID'
          NETOPS_OPERATOR_ROLE: 'approver'
          NETOPS_REQUIRE_DUAL_APPROVAL: 'true'
        toolCallTimeoutMs: 120000
        failOnStartupError: true
        reconnect:
          enabled: true
          initialDelayMs: 500
          maxDelayMs: 10000
          maxAttempts: 8
$END
EOF

# Validate the entire resulting file before touching the current Profile configuration.
"$PYTHON" - "$TMP" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as stream:
    data = yaml.safe_load(stream) or []
if not isinstance(data, list):
    raise SystemExit("Harness patch YAML 顶层必须是列表")
entries = [entry for item in data if isinstance(item, dict)
           for entry in item.get("insert", []) if isinstance(entry, dict)]
ids = [entry.get("id") for entry in entries]
servers = [entry.get("config", {}).get("serverName") for entry in entries]
for required in ("mcp-huawei-netops-operator", "mcp-huawei-netops-approver"):
    if ids.count(required) != 1:
        raise SystemExit(f"MCP 条目缺失或重复：{required}")
for required in ("huawei_netops_operator", "huawei_netops_approver"):
    if servers.count(required) != 1:
        raise SystemExit(f"MCP serverName 缺失或重复：{required}")
PY

if [[ -f "$PATCH_FILE" ]]; then
  cp -p "$PATCH_FILE" "$PATCH_FILE.$(date +%Y%m%d-%H%M%S).bak"
fi
chmod 600 "$TMP"
mv -f "$TMP" "$PATCH_FILE"
trap - EXIT

echo "已在单个 Harness Profile 注册 operator + approver 两个 MCP 实例：$PATCH_FILE"
echo "operator=$OPERATOR_ID；approver=$APPROVER_ID；双人审批=true"
echo "启动一次 dsh --profile $PROFILE，即可同时加载两个 MCP 连接。"
