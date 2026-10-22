#!/usr/bin/env bash
# 评分以 root 运行（task.toml 的 [verifier] user = "root"），候选程序以 runner 运行。
set -u

PY=/usr/local/bin/python3
V=/logs/verifier

mkdir -p "$V"
# 解题阶段可能已在这里放了 reward.json（Harbor 优先读它）或把 reward.txt 换成软链接。
rm -rf "$V/reward.json" "$V/reward.txt"
echo 0 > "$V/reward.txt"

on_signal() {
    rm -rf "$V/reward.json"
    echo 0 > "$V/reward.txt"
    exit 0
}
trap on_signal INT TERM HUP
trap 'rm -rf "$V/reward.json"' EXIT

cd /tests || exit 0

# 结束候选残留进程，清空评分目录。失败时 reward 保持 0。
"$PY" -I score.py prepare || exit 0

# -I：忽略 PYTHON* 环境变量、用户 site-packages 和当前目录，防 sitecustomize 注入。
"$PY" -I test_outputs.py

# reward 只由检查记录按权重汇总；测试脚本退出码不参与判定。
"$PY" -I score.py finalize || { rm -rf "$V/reward.json" "$V/reward.txt"; echo 0 > "$V/reward.txt"; }

exit 0
