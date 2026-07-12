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

### 在售

```
WPS 云文档 (xlsx) 或 手写 txt (Excel 列顺序)
  ↓  scripts/parse_wps_excel.py 或 parse_excel_order_txt.py  → inventory/*.txt
  ↓  scripts/build_data.py  → Scryfall API enrichment
  ↓                          → data/cards.json + assets/cards-data.js
  ↓  git commit & push
GitHub Pages → claystan.cc
```

1. **WPS Excel**（`templates/WPS库存协作模板.xlsx`）：每卖家一张工作表，含昵称/城市/联系 + 卡牌行
2. **手写 txt**（如根目录 `claystan.txt`）：每行 `系列 编号 语言 闪 数量`，文件头 `# seller: / # city: / # contact:` 声明元数据
3. **inventory/*.txt**：中间格式，卡行 `[Nx] <set> <number> [lang] [foil]`
4. **build_data.py**：读 inventory/*.txt → 调 Scryfall API（带 `.cache/scryfall/` 磁盘缓存 + 限速 0.12s）→ 富化卡名/图/规则文字 → 输出 `data/cards.json`（完整）和 `assets/cards-data.js`（内嵌前端）
5. **前端**：`index.html` 加载 `cards-data.js` + `app.js`，纯客户端渲染

### 求购

```
wants/*.txt
  ↓  scripts/build_wants.py  → Scryfall enrichment
  ↓                          → data/wants.json + assets/wants-data.js
```

## Key Directories

| 路径 | 用途 |
|------|------|
| `scripts/` | Python 脚本：`parse_wps_excel.py`、`parse_excel_order_txt.py`、`build_data.py`、`build_wants.py`、`inventory_format.py`（共享约定）、`update.sh`（一键上线） |
| `inventory/` | 卖家库存 txt 文件（一人一文件，如 `claystan.txt`） |
| `wants/` | 求购 txt 文件 |
| `data/` | `cards.json` / `wants.json` — 富化后的完整数据 |
| `assets/` | 前端资源：`app.js`、`cards-data.js`、`wants-data.js`、`style.css` |
| `templates/` | WPS 协作模板 xlsx |
| `.cache/scryfall/` | Scryfall API 响应缓存（git-ignored） |

## Build & Run

```bash
# 环境初始化
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 一键上线（推荐）：解析 → Scryfall 富化 → git commit & push
./scripts/update.sh                     # 默认解析根目录 claystan.txt
./scripts/update.sh claystan.txt        # 指定 txt
./scripts/update.sh ~/下载/库存.xlsx      # 解析 WPS 导出的 xlsx

# 分步执行
# 1a. 解析手写 txt（Excel 列顺序：系列 编号 语言 闪 数量）
python3 scripts/parse_excel_order_txt.py claystan.txt --dry-run  # 先校验
python3 scripts/parse_excel_order_txt.py claystan.txt

# 1b. 或解析 WPS 导出的 xlsx
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx --dry-run
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx

# 2. 拉取 Scryfall 元数据，生成站点数据
python3 scripts/build_data.py

# 3. 生成求购数据（wants/*.txt）
python3 scripts/build_wants.py

# 4. 提交上线
git add inventory wants data assets/cards-data.js assets/wants-data.js
git commit -m "Update inventory/wants"
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
- **`seller`、`city`、`contact` 为必填项**，缺失时所有脚本（`parse_excel_order_txt.py`、`parse_wps_excel.py`、`build_data.py`）会报错退出
- `parse_excel_order_txt.py` 的输入格式为 Excel 列顺序：`系列 编号 语言 闪 数量`（位置固定，与 inventory 格式不同）

### 前端约定

- 无构建工具/无 npm — 纯静态文件，修改后直接 git push
- 卡牌数据内嵌在 `assets/cards-data.js`（`window.__MTG_DATA__`），`index.html` 通过 `<script>` 加载
- 意向清单存储在 `localStorage`（key: `mtg-wishlist-v1`）
- `app.js` 中所有 DOM 查询用 `$()` 简写，渲染靠 `innerHTML` 模板字符串
- HTML 转义：`escapeHtml()` / `escapeAttr()` 用于所有用户可控内容

### Python 脚本约定

- 共享逻辑在 `scripts/inventory_format.py`（语言/闪/数量归一化、slugify、ParseError、`validate_meta()` 必填校验）
- Scryfall 请求有限速（`REQUEST_GAP = 0.12s`）和磁盘缓存（`.cache/scryfall/`）
- `build_data.py` 有两层增量缓存：已有 `cards.json` 的富化数据复用 + Scryfall 磁盘缓存
- `build_data.py --validate-only` 可只校验不联网（用于 PR 校验）
- `build_data.py --no-cache` 禁用磁盘缓存
- `update.sh` 是一键上线脚本，自动判断 `.txt`/`.xlsx` 并完成解析 → 富化 → commit & push

## site_config.json

站点级配置：标题、副标题、WPS 文档链接、联系方式。`build_data.py` 会读取并写入 `cards.json` 的 `site` 字段，前端从中渲染。

## Git & Deploy

- 分支 `master`，push 后 GitHub Pages 自动部署
- 上线产物：`inventory/*.txt` + `data/cards.json` + `assets/cards-data.js`（+ `wants/*.txt` + `assets/wants-data.js`）
- 前端 CSS/JS 有版本号参数（`?v=N`），修改前端文件后需 bump 版本号强制缓存刷新
- `.gitignore`：`.venv/`、`.cache/`、`__pycache__/`、WPS lock files（`**/.~*`）
