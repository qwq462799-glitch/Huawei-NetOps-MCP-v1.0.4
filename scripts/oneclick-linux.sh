#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

OPERATOR_ID="${NETOPS_OPERATOR_ID:-$(id -un | tr -c 'A-Za-z0-9_.@-' '-' | sed 's/-$//')-operator}"
APPROVER_ID="${NETOPS_APPROVER_ID:-$(id -un | tr -c 'A-Za-z0-9_.@-' '-' | sed 's/-$//')-approver}"
COMBINED_PROFILE="${NETOPS_PROFILE:-netops-all}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
export DSH_HOME

[[ "$OPERATOR_ID" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || die "NETOPS_OPERATOR_ID 格式不合法。"
[[ "$APPROVER_ID" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || die "NETOPS_APPROVER_ID 格式不合法。"
[[ "$OPERATOR_ID" != "$APPROVER_ID" ]] || die "operator 与 approver 必须使用不同身份 ID。"
[[ "$COMBINED_PROFILE" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "Harness Profile 名称不合法。"

VENV_PY="$ROOT/.venv/bin/python"
NEED_INSTALL=0
if [[ ! -x "$VENV_PY" || ! -f "$ROOT/.env" ]]; then
  NEED_INSTALL=1
elif ! "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)' >/dev/null 2>&1; then
  NEED_INSTALL=1
elif ! "$VENV_PY" -c 'import fastmcp, netmiko, cryptography, yaml, filelock, pydantic_settings' >/dev/null 2>&1; then
  NEED_INSTALL=1
fi

if (( NEED_INSTALL )) && [[ -d "$ROOT/.venv" ]]; then
  OLD_VENV="$ROOT/.venv.incompatible.$(date +%Y%m%d-%H%M%S)"
  mv "$ROOT/.venv" "$OLD_VENV"
  echo "旧虚拟环境已备份：$OLD_VENV"
fi

if (( NEED_INSTALL )); then
  say "首次安装/修复 MCP 环境（Python 3.11/3.12、依赖、密钥、数据库）"
  bash "$ROOT/scripts/install-core.sh"
else
  say "复用已有虚拟环境，自动检查密钥和数据库"
  "$VENV_PY" "$ROOT/scripts/bootstrap.py"
fi

VENV_PY="$ROOT/.venv/bin/python"
"$VENV_PY" -m app.cli doctor

if ! command -v dsh >/dev/null 2>&1; then
  cat <<'ENDMSG'

[完成] Ubuntu MCP 核心已安装并通过 doctor 检查。
当前系统未检测到 DeepSeek Harness 的 dsh CLI，因此本机 Harness Profile 未创建，也没有启动一个脱离客户端的 stdio MCP 进程。

如果 Harness 就运行在这台 Ubuntu：安装/配置 dsh CLI 后再次执行：
  bash START-NETOPS-LINUX.sh

如果 Harness 运行在 Windows：在 Windows 项目目录运行 START-NETOPS-WINDOWS.bat，设置 NETOPS_REMOTE_SSH_TARGET=user@UBUNTU_IP 和 NETOPS_REMOTE_PROJECT_ROOT=/opt/huawei-netops-mcp，即可自动生成远程双角色 Profile。

注意：stdio MCP 进程应由 Harness 客户端按需拉起，不应作为无客户端的后台守护进程运行。
ENDMSG
  if [[ "${NETOPS_REQUIRE_DSH:-0}" == "1" ]]; then exit 2; fi
  exit 0
fi

PROFILE_ROOT="$DSH_HOME/profiles"
mkdir -p "$PROFILE_ROOT"

ensure_dsh_profile() {
  local name="$1"
  local dir="$PROFILE_ROOT/$name"
  if [[ -f "$dir/package.json" && -f "$dir/dsh.profile" ]]; then
    echo "[OK] Harness Profile 已存在：$name"
    return
  fi

  say "初始化 Harness Profile：$name"
  local old_patch=""
  local backup_dir=""
  if [[ -d "$dir" ]]; then
    if [[ -f "$dir/cordis.patch.yml" ]]; then
      old_patch="$(mktemp)"
      cp "$dir/cordis.patch.yml" "$old_patch"
    fi
    backup_dir="${dir}.pre-oneclick.$(date +%Y%m%d-%H%M%S)"
    mv "$dir" "$backup_dir"
    echo "旧 Profile 目录已备份：$backup_dir"
  fi

  if ! dsh --profile "$name" --from-default-profile web --dump-config >/dev/null 2>&1; then
    if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
      [[ ! -e "$dir" ]] || mv "$dir" "${dir}.failed-init.$(date +%Y%m%d-%H%M%S)"
      mv "$backup_dir" "$dir"
    fi
    [[ -z "$old_patch" ]] || rm -f "$old_patch"
    die "dsh 初始化 Profile '$name' 失败。请检查 DeepSeek Harness CLI 版本和配置。"
  fi
  [[ -f "$dir/package.json" && -f "$dir/dsh.profile" ]] || die "dsh 返回成功但没有生成 Profile 清单：$dir"
  if [[ -n "$old_patch" ]]; then
    cp "$old_patch" "$dir/cordis.patch.yml"
    rm -f "$old_patch"
  fi
}

say "创建一个同时包含 operator / approver 的 Harness Profile"
ensure_dsh_profile "$COMBINED_PROFILE"

bash "$ROOT/scripts/configure-harness-dual.sh" "$COMBINED_PROFILE" "$OPERATOR_ID" "$APPROVER_ID" true
dsh --profile "$COMBINED_PROFILE" --dump-config >/dev/null

export NETOPS_OPERATOR_ID="$OPERATOR_ID"
export NETOPS_OPERATOR_ROLE=operator
export NETOPS_REQUIRE_DUAL_APPROVAL=true
"$VENV_PY" -m app.cli doctor

cat <<ENDMSG

==============================================
 Huawei NetOps MCP 一键配置完成
 operator : $OPERATOR_ID  (MCP: huawei_netops_operator)
 approver : $APPROVER_ID  (MCP: huawei_netops_approver)
 Harness Profile : $COMBINED_PROFILE（两个角色同时加载）
 申请/审批身份差异检查 : 已启用
 MCP 位置  : 本机 Ubuntu
==============================================
ENDMSG

if [[ "${NETOPS_NO_LAUNCH:-0}" == "1" ]]; then
  echo "未启动 Harness（NETOPS_NO_LAUNCH=1）。执行 dsh --profile $COMBINED_PROFILE 即可同时加载两个角色。"
  exit 0
fi

say "启动一次 DeepSeek Harness；operator 与 approver 两个 MCP 连接将同时加载"
echo "operator MCP：$OPERATOR_ID（配置申请/执行）"
echo "approver MCP：$APPROVER_ID（审批/确认/回滚）"
echo "注意：同一 Harness 会话同时持有两种工具身份，不等同于两个独立人员的强制双人控制。"
exec dsh --profile "$COMBINED_PROFILE"
