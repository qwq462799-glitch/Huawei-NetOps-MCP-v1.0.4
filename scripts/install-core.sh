#!/usr/bin/env bash
set -euo pipefail

# Ubuntu 24.04 原生一键安装；不使用 Docker，也不启动 Web 服务。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/5] 检查并安装系统依赖（包含 Python 3.12，适用于最小化 Ubuntu Server）……"
sudo apt-get update
sudo apt-get install -y python3 python3.12 python3.12-venv python3-pip python3-dev build-essential openssh-client

PYTHON=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    VERSION="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$VERSION" == "3.11" || "$VERSION" == "3.12" ]]; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "错误：系统依赖安装后仍未找到 Python 3.11/3.12。" >&2
  exit 1
fi

echo "[2/5] 创建 Python 虚拟环境……"
"$PYTHON" -m venv .venv
source .venv/bin/activate


echo "[3/5] 安装 MCP、SSH/Telnet 与设备驱动依赖……"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .

echo "[4/5] 自动生成加密密钥并初始化数据库……"
python scripts/bootstrap.py

echo "[5/5] 环境自检……"
netops doctor

cat <<EOF

安装成功。
项目目录：$ROOT
MCP 传输：stdio（由 DeepSeek Harness 自动拉起）
启动：不需要手动启动 HTTP 服务；配置 Harness 后重启 Harness 即可。
设备登记：在 Harness 中调用 device_add。
EOF
