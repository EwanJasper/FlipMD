#!/usr/bin/env bash
# macOS / Linux 启动脚本
# 用法: chmod +x launch.sh && ./launch.sh
set -e
cd "$(dirname "$0")"
uv run python launch.py
