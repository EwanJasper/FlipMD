#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
flipmd_uv="$(command -v uv || true)"
if [[ -z "$flipmd_uv" && -x "$HOME/.local/bin/uv" ]]; then
  flipmd_uv="$HOME/.local/bin/uv"
fi
if [[ -z "$flipmd_uv" ]]; then
  print '未找到 uv。请先安装 uv，再重新打开 FlipMD。'
  read -k 1 '?按任意键关闭。'
  exit 1
fi
exec "$flipmd_uv" run --python 3.12 --frozen --extra desktop flipmd
