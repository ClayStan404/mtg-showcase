# QWEN.md

## Project Overview

静态 **万智牌在售清单** 网站，用于多人展示实体卡牌库存。买家可搜索、筛选、加入意向清单后截图/复制文本站外联系卖家。**不做站内下单/支付。**

- **站点**：https://claystan.cc/
- **仓库**：https://github.com/ClayStan404/mtg-showcase
- **分支**：`master`
- **部署**：GitHub Pages（CNAME → `claystan.cc`）

## Tech Stack

- **前端**：原生 HTML / CSS / JS（无框架），`index.html` + `assets/app.js` + `assets/style.css`
- **数据**：`assets/cards-data.js`（`window.__MTG_DATA__` 内嵌，避免额外 fetch）与 `data/cards.json` 同源
- **后端脚本**：Python 3（`requests` + `openpyxl`），职责是解析 WPS Excel → 拉取 Scryfall 元数据 → 生成站点数据
- **库存来源**：WPS 金山文档在线协作表格 → 导出 xlsx → 脚本解析

## Architecture / Data Flow

```
WPS 云文档 (xlsx)
  ↓  scripts/parse_wps_excel.py  → inventory/*.txt
  ↓  scripts/build_data.py        → Scryfall API enrichment
  ↓                                → data/cards.json + assets/cards-data.js
  ↓  git commit & push
GitHub Pages → claystan.cc
```

1. **WPS Excel**（`templates/WPS库存协作模板.xlsx`）：每卖家一张工作表，含昵称/城市/联系 + 卡牌行
2. **inventory/*.txt**：中间格式，文件头 `# seller: / # city: / # contact:`，卡行 `[Nx] <set> <number> [lang] [foil]`
3. **build_data.py**：读 inventory/*.txt → 调 Scryfall API（带 `.cache/scryfall/` 磁盘缓存 + 限速 0.12s）→ 富化卡名/图/规则文字 → 输出 `data/cards.json`（完整）和 `assets/cards-data.js`（内嵌前端）
4. **前端**：`index.html` 加载 `cards-data.js` + `app.js`，纯客户端渲染

## Key Directories

| 路径 | 用途 |
|------|------|
| `scripts/` | Python 脚本：`parse_wps_excel.py`、`build_data.py`、`inventory_format.py`（共享约定） |
| `inventory/` | 卖家库存 txt 文件（一人一文件，如 `claystan.txt`） |
| `data/` | `cards.json` — 富化后的完整卡牌数据 |
| `assets/` | 前端资源：`app.js`、`cards-data.js`、`style.css` |
| `templates/` | WPS 协作模板 xlsx |
| `docs/` | 卖家使用说明 |
| `.cache/scryfall/` | Scryfall API 响应缓存（git-ignored） |

## Build & Run

```bash
# 环境初始化
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. 解析 WPS 导出的 xlsx（先校验再写入）
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx --dry-run
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx

# 2. 拉取 Scryfall 元数据，生成站点数据
python3 scripts/build_data.py

# 3. 提交上线
git add inventory data/cards.json assets/cards-data.js
git commit -m "Update inventory from WPS"
git push origin master
```

本地预览：直接用浏览器打开 `index.html`，或 `python3 -m http.server` 后访问 `localhost:8000`。

## Conventions

### 库存字段简写

| 字段 | 规则 |
|------|------|
| 语言 | `e`=英文 · `z`=中文 · `j`=日文 · `o`=其他（空默认 `e`） |
| 闪 | 空或 `0`=非闪 · `1`=闪 |
| 数量 | 空=1；多张用 `2x` 前缀 |

- 卖光请**删行**，不写 `0`
- 同卡同印刷同语言同行，用数量合并
- inventory txt 文件头用 `# seller: / # city: / # contact:` 声明元数据

### 前端约定

- 无构建工具/无 npm — 纯静态文件，修改后直接 git push
- 卡牌数据内嵌在 `assets/cards-data.js`（`window.__MTG_DATA__`），`index.html` 通过 `<script>` 加载
- 意向清单存储在 `localStorage`（key: `mtg-wishlist-v1`）
- `app.js` 中所有 DOM 查询用 `$()` 简写，渲染靠 `innerHTML` 模板字符串
- HTML 转义：`escapeHtml()` / `escapeAttr()` 用于所有用户可控内容

### Python 脚本约定

- 共享逻辑在 `scripts/inventory_format.py`（语言/闪/数量归一化、slugify、ParseError）
- Scryfall 请求有限速（`REQUEST_GAP = 0.12s`）和磁盘缓存（`.cache/scryfall/`）
- `build_data.py --validate-only` 可只校验不联网（用于 PR 校验）
- `build_data.py --no-cache` 禁用磁盘缓存

## site_config.json

站点级配置：标题、副标题、WPS 文档链接、联系方式。`build_data.py` 会读取并写入 `cards.json` 的 `site` 字段，前端从中渲染。

## Git & Deploy

- 分支 `master`，push 后 GitHub Pages 自动部署
- 上线需 `git add` 三个产物：`inventory/*.txt` + `data/cards.json` + `assets/cards-data.js`
- `.gitignore`：`.venv/`、`.cache/`、`__pycache__/`、WPS lock files（`**/.~*`）
