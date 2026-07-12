#!/usr/bin/env bash
# 更新库存并上线：解析 → Scryfall 富化 → git commit & push
#
# 用法:
#   ./scripts/update.sh                    # 默认解析 claystan.txt
#   ./scripts/update.sh claystan.txt       # 指定 txt
#   ./scripts/update.sh ~/下载/库存.xlsx    # 解析 WPS 导出的 xlsx
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

INPUT="${1:-claystan.txt}"
PYTHON="$ROOT/.venv/bin/python3"
[ -f "$PYTHON" ] || PYTHON="python3"

if [ ! -f "$INPUT" ]; then
    echo "❌ 文件不存在: $INPUT" >&2
    exit 1
fi

# 1. 解析库存
echo "▶ 1/3 解析 $INPUT"
case "$INPUT" in
    *.txt)  "$PYTHON" scripts/parse_excel_order_txt.py "$INPUT" ;;
    *.xlsx) "$PYTHON" scripts/parse_wps_excel.py "$INPUT" ;;
    *) echo "❌ 不支持的文件类型（仅 .txt 或 .xlsx）" >&2; exit 1 ;;
esac

# 2. 拉取 Scryfall 元数据
echo "▶ 2/3 拉取 Scryfall 元数据"
"$PYTHON" scripts/build_data.py

# 3. 提交上线
echo "▶ 3/3 提交上线"
git add inventory/*.txt data/cards.json assets/cards-data.js index.html

# 源文件在仓库内则一并提交
INPUT_ABS="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"
if [[ "$INPUT_ABS" == "$ROOT"/* ]]; then
    git add "$INPUT"
fi

if git diff --staged --quiet; then
    echo "ℹ 无变更需要提交"
    exit 0
fi

COUNT=$("$PYTHON" -c "import json;print(json.load(open('data/cards.json'))['count'])")
TOTAL=$("$PYTHON" -c "import json;print(json.load(open('data/cards.json'))['total_quantity'])")

git commit -m "Update inventory: ${COUNT} cards / ${TOTAL} total (from $(basename "$INPUT"))"
git push origin master

echo "✅ 上线完成：${COUNT} 种 / ${TOTAL} 张"
