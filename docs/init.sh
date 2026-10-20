#!/usr/bin/env bash

# 为每日金句项目准备本地环境并执行不写入 Notion 的基础验证。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 沙箱无法访问用户目录下的 uv 缓存时，使用当前可写的临时目录。
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/qotd-uv-cache}"

echo "==> 当前目录: $PWD"
if [[ -x .venv/bin/python ]]; then
  echo "==> 复用现有 .venv；未重新安装依赖"
else
  echo "==> 按 uv.lock 安装依赖"
  uv sync --locked
fi

echo "==> 运行离线测试"
uv run --no-sync pytest -q
echo "==> 运行 Ruff 检查"
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .

echo "==> 手动发布命令（会写入真实 Notion，不会由本脚本执行）"
echo "    uv run qotd daily"
