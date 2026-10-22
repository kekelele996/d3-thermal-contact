#!/usr/bin/env bash
set -euo pipefail

# 参考解：把快速估算替换成"集总铝块 + 一维样品 + 界面热阻 + 背面换热"的
# 瞬态模型，再用多起点最小二乘同时反演热扩散率和界面热阻。
#
# 留一法：
#   HTB_SKIP=difficulty_1  界面按理想接触处理，只反演热扩散率
#   HTB_SKIP=difficulty_2  背面按绝热处理
#   HTB_SKIP=difficulty_3  功率按理想阶跃处理
# 正式 Oracle 不设这个变量。
cd /app
SKIP="${HTB_SKIP:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fix_difficulty_1() { :; }
fix_difficulty_2() { :; }
fix_difficulty_3() { :; }

for d in difficulty_1 difficulty_2 difficulty_3; do
  if [ "$SKIP" = "$d" ]; then
    echo "留一法：跳过 $d" >&2
    continue
  fi
  "fix_$d"
done

install -m 0644 "$HERE/analyze.py" /app/analyze.py
sed -i "s/__SKIP__/${SKIP}/" /app/analyze.py
chmod 0755 /app/analyze.py
python3 -c "import ast; ast.parse(open('/app/analyze.py', encoding='utf-8').read())"
