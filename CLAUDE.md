# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 同项目的 Qwen Code 指引见 `QWEN.md`,两者事实应保持一致;改架构时同步更新。`QWEN.md` 额外含 self-hosted runner 机器配置细节。

## 项目概览

静态 **万智牌在售 + 求购清单** 网站(GitHub Pages,域名 `claystan.cc`)。多位卖家 / 买家在 WPS 协作文档里维护实体卡库存与求购,网站做检索 / 筛选 / 意向清单,买家截图或复制后**站外联系成交**。不做站内下单或支付。

库存与求购的真实数据源是 **WPS 云文档(金山文档 KDocs)**,在售 / 求购各一个分享文档。`master` 只放源码与构建脚本,**生成产物不入库**。部署走 GitHub Actions(workflow 模式):`push master` / 每小时 cron / 手动触发 -> 现场从 WPS 拉取生成产物 -> 打包成 Pages artifact 直接发布。

## 架构:两条业务线 + 自动化

数据有**库存(inventory)**和**求购(wants)**两条平行流水线,结构对称;外加 WPS 自动拉取与 GitHub Actions 部署。

### 自动化流程(GitHub Actions 每小时,`.github/workflows/auto-update.yml`)

```
WPS 在售文档 (share cgyl3WizNfp7) -> fetch_wps_share.py -> wps_inventory.xlsx
WPS 求购文档 (share cvvaN21e3gm8) -> fetch_wps_share.py -> wps_wants.xlsx
   ↓
parse_wps_excel.py        -> inventory/*.txt
parse_wps_wants_excel.py  -> wants/*.txt
   ↓
build_data.py   -> data/cards.json + assets/cards-data.js
build_wants.py  -> data/wants.json + assets/wants-data.js
   ↓
assemble site/（源码 + 产物 + CNAME）-> upload-pages-artifact -> deploy-pages
```

产物不入 git,每条 workflow run 现场生成并打包发布;`master` 历史只有源码提交。

- self-hosted runner(Debian),cron `0 * * * *`,也支持 `workflow_dispatch` 手动触发;`push` 到 master 也触发部署(代码改动立即上线,纯文档改动除外)。
- `fetch_wps_share.py` 靠 WPS session Cookie 认证;Cookie 文件查找顺序:项目根 `wps_cookies.txt` -> `~/.config/wps_cookies.txt` -> 环境变量 `WPS_COOKIES`。runner 上放在 `~/.config/wps_cookies.txt`,过期需从浏览器复制新值覆盖(无需重启 runner)。
- **产物不入 git**:Actions 不再 commit 到 master,而是现场生成产物后组装 `site/` 目录(源码 + 产物 + `CNAME`),用 `actions/upload-pages-artifact` + `actions/deploy-pages` 直接发布到 Pages。解析前先 `rm -f inventory/*.txt wants/*.txt` 清残留;有 `concurrency` 防重叠,失败时创建/评论 GitHub issue 通知。
- `checkout` 用 `clean: false`,保留 runner 工作区的 `.cache/scryfall` 与上一份 `data/*.json`(供 `load_previous_enrichment` 复用 + Scryfall 磁盘缓存加速重建)。
- **`inventory/*.txt` 与 `wants/*.txt` 都是中间产物,不入库**。

### ClayStan 个人本地流程(数据只从 WPS 取)

```
claystan.txt(手写,Excel 列顺序:系列 编号 语言 闪 数量)
  ↓ txt_to_wps_xlsx.py -> claystan.xlsx(WPS 模板格式,手动上传到 WPS 在售文档)
  ↓ 下次 workflow 运行自动拉取上线(或 gh workflow run auto-update.yml 立即触发)
```

`claystan.txt` 是个人编辑源,不参与 Actions 自动化。**数据上线统一走 WPS + Actions**,无本地直连路径。代码改动 push `master` 自动触发部署。其他卖家 / 买家直接在 WPS 协作文档里编辑自己的工作表,无需本地操作。

### 数据流水线(两段,库存与求购对称)

1. **xlsx -> `*.txt`**:`parse_wps_excel.py`(在售)/ `parse_wps_wants_excel.py`(求购,多一列「必须」)解析 WPS 导出的 `.xlsx`(每个卖家 / 买家一个工作表),写成 `inventory/<seller>.txt` / `wants/<buyer>.txt`。文件头用 `# seller: / # city: / # contact:`(求购用 `# buyer:`)。卡行格式 `[Nx] set number [lang] [foil]`(求购再追加 `[must]`)。
2. **`*.txt` -> 站点数据**:`build_data.py` / `build_wants.py` 解析 txt,按 `seller_id|set|number|lang|foil`(`build_wants` 再加 `must`)合并重复行,调 Scryfall 取卡图 / 英文名 / 规则面,非中文卡再调 mtgch 取中文名。**各写两份产物**:缩进 JSON(`data/cards.json` / `data/wants.json`)+ 内嵌 JS(`assets/cards-data.js` = `window.__MTG_DATA__` / `assets/wants-data.js` = `window.__MTG_WANTS__`)。`build_wants.py` 复用 `build_data.py` 的 `ScryfallClient` 与富化函数。

`scripts/inventory_format.py` 是两段共用的字段约定库(语言 / 闪 / 数量 / `must` 归一化、`slugify`、`ParseError`、`validate_meta`、`card_line_to_fields`、`want_line_to_fields`)。改字段语义时所有脚本都要兼顾。

### 前端如何取数据

`assets/app.js` 的 `loadData()` 优先读 `window.__MTG_DATA__`(内嵌的 `cards-data.js`);只有在未生成时才回退 `fetch data/cards.json`。求购数据同理走 `window.__MTG_WANTS__`(`wants-data.js`)。这是刻意设计--代理 / DNS 环境下 `fetch` 本地 json 会失败,内嵌更稳。`cards.json` / `cards-data.js` 不在 git,由 workflow 部署时 `build_data.py` 生成并打包进 artifact;本地改源码后 push `master` 触发部署即可,无需手动跑 build。

前端无构建步骤、无框架:`index.html` + `assets/app.js` + `assets/style.css`,纯 vanilla JS。首页有「在售 / 求购」两个视图 tab。意向清单持久化在 `localStorage`(key `mtg-wishlist-v1`)。`index.html` 里 CSS/JS 用 `?v=N` 做缓存击穿;`?v=` 由 `build_data.py` 的 `bump_cache_buster` 用内容哈希自动 bump,**bump 只发生在部署 artifact 里,不回写 master**。用户可控内容一律走 `escapeHtml()` / `escapeAttr()`。

## 脚本一览

| 脚本 | 用途 |
|------|------|
| `fetch_wps_share.py` | 从 WPS 分享链接下载 xlsx(Cookie 认证) |
| `parse_wps_excel.py` | WPS 在售 xlsx -> `inventory/*.txt` |
| `parse_wps_wants_excel.py` | WPS 求购 xlsx -> `wants/*.txt`(多「必须」列) |
| `parse_excel_order_txt.py` | 手写 txt(Excel 列顺序:系列 编号 语言 闪 数量)-> `inventory/*.txt` |
| `txt_to_wps_xlsx.py` | `claystan.txt` -> WPS 模板格式 xlsx(上传用) |
| `build_data.py` | `inventory/*.txt` -> Scryfall 富化 -> `data/cards.json` + `assets/cards-data.js` |
| `build_wants.py` | `wants/*.txt` -> Scryfall 富化 -> `data/wants.json` + `assets/wants-data.js` |
| `inventory_format.py` | 共享字段约定库(归一化 / slugify / ParseError / validate_meta) |
| `build_common.py` | build_data / build_wants 共享:Scryfall 富化、磁盘缓存、payload 工具(解耦) |
| `wps_excel_common.py` | parse_wps_* 共享:工作表跳过 / meta / header 查找 / 写入(含冲突检测) |
| `test_wps_api.py` | WPS 开放平台 API 测试(OAuth,待审核;凭证 `appid_and_key`) |

## 常用命令

```bash
# 初始化(首次或换机)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # requests + openpyxl

# ── 自动化(GitHub Actions 每小时自动跑;手动触发)──
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase

# ── ClayStan 个人更新(数据走 WPS,无本地上线)──
python3 scripts/txt_to_wps_xlsx.py claystan.txt   # 生成 xlsx,手动上传到 WPS 在售文档
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase   # 立即触发部署(不等整点)

# ── 手动分步(调试)──
python3 scripts/fetch_wps_share.py --share-id cgyl3WizNfp7 --output wps_inventory.xlsx
python3 scripts/fetch_wps_share.py --share-id cvvaN21e3gm8 --output wps_wants.xlsx
python3 scripts/parse_wps_excel.py wps_inventory.xlsx --dry-run   # 校验不写
python3 scripts/parse_wps_excel.py wps_inventory.xlsx             # 写 inventory/*.txt
python3 scripts/parse_wps_wants_excel.py wps_wants.xlsx
python3 scripts/build_data.py          # 生成 cards.json + cards-data.js
python3 scripts/build_wants.py         # 生成 wants.json + wants-data.js
python3 scripts/build_data.py --validate-only   # 只校验不联网(PR/CI 友好)
python3 scripts/build_data.py --no-cache        # 忽略 .cache/scryfall 强拉
```

无单元测试、无 lint、无前端构建。验证手段:`--dry-run` / `--validate-only`,以及本地打开 `index.html`(或 `python3 -m http.server`)肉眼检查。

## 字段约定(贯穿表格 / txt / 脚本,勿拆散)

| 字段 | 输入 | 内部码 |
|------|------|--------|
| 语言 | `e`/`z`/`j`/`o`(空默认 `e`) | `en` / `zhs` / `ja` / `other` |
| 闪 | 空 / `0`=否,`1`=是 | bool |
| 数量 | 空=1 | int≥1 |
| 必须(求购) | 空 / `0`=可替其他版,`1`=必须此印刷(空默认 `0`) | bool |

- `o`(other) 展示为「其他」,但拉 Scryfall 图时**回退 `en`**(见 `SCRYFALL_LANG`)。
- 语言 / 闪 / 数量 / `must` 默认走**严格模式**:无法识别的值抛 `ParseError` 而非静默回退。新增可识别别名改 `inventory_format.py` 的 `LANG_INPUT_MAP` / `FOIL_TRUE` / `FOIL_FALSE` / `normalize_strict`。
- `seller`/`buyer`、`city`、`contact` 为**必填项**,缺失时 `validate_meta` 报错退出(库存验 `seller`,求购验 `buyer`)。
- WPS 工作表跳过规则:名为「说明 / 使用说明 / 填写说明 / 对照表(一般不用改)」或以「模板 / template / _」开头。表头需含「系列」「编号」列,前 15 行找「昵称 / 城市 / 联系」。
- 卖光请**删行**,不写 `0`;同卡同印刷同语言同行,用数量合并。
- `parse_excel_order_txt.py` 的输入是 **Excel 列顺序**(`系列 编号 语言 闪 数量`,位置固定),与 `inventory/*.txt` 的 `[Nx] set number [lang] [foil]` 格式不同--别混淆。

## 资源与外部依赖

- **Scryfall API**:`https://api.scryfall.com/cards/{set}/{number}/{lang}`,节流间隔 `REQUEST_GAP=0.12s`,`USER_AGENT="MTGShowcase/1.0 (personal inventory; github pages)"`。响应缓存在 `.cache/scryfall/`(gitignore)。图片直接 hotlink Scryfall CDN(`cards.scryfall.io`,官方允许),不下载 / 不存储 / 不变形。
- **mtgch API**:`https://mtgch.com/api/v1/card/{set}/{number}/`,仅取非中文卡中文名。
- **WPS 分享下载**:`fetch_wps_share.py` 走 `https://www.kdocs.cn/api/v3/office/file/{share_id}/download?format=xlsx`,302 重定向与 JSON 两种响应都处理。分享 ID:在售 `cgyl3WizNfp7`、求购 `cvvaN21e3gm8`(也写在 `site_config.json` 的 `wps_inventory_url` / `wps_wants_url`)。
- **WPS 开放平台 API**(待审核):`test_wps_api.py` 走 OAuth + 读单元格两条路,凭证在 `appid_and_key`(gitignore)。审核通过后可取代 Cookie 方案。
- `build_data.py` 会复用上一份 `cards.json` 里同 `set|number|lang` 的元数据加速重建(两层增量:JSON 复用 + Scryfall 磁盘缓存);`build_wants.py` 暂无此层 JSON 复用,仅有 Scryfall 磁盘缓存。workflow 用 `clean: false` 保留 runner 工作区的这两层缓存;**清缓存或改了卡时首次构建会慢**。
- `site_config.json`:站点标题 / 副标题 / 两个 WPS 文档 URL / 联系方式,会被 `build_data.py` / `build_wants.py` 内嵌进 JSON 的 `site` 字段供前端渲染。
- `templates/WPS库存协作模板.xlsx`、`templates/WPS求购模板.xlsx`:卖家 / 买家协作模板本地副本,线上主入口见 `site_config.json`。

## Git / 部署注意

- **单一部署路径**:GitHub Actions(workflow 模式)。`push master` / 每小时 cron / `workflow_dispatch` 触发 -> 现场从 WPS 拉取生成产物 -> 打包 Pages artifact 发布。**产物不入 git**,master 只放源码。
- 日常提交:只提交源码(`index.html`、`assets/app.js`、`assets/style.css`、`scripts/`、`site_config.json`、`claystan.txt`、文档等)。数据产物由 workflow 现场生成。
- `.gitignore`:`.venv/`、`.cache/`、`__pycache__/`、`appid_and_key`、`wps_cookies.txt`、生成的 `*.xlsx`、WPS lock files(`**/.~*`),以及**生成产物** `inventory/`、`data/cards.json`、`data/wants.json`、`assets/cards-data.js`、`assets/wants-data.js`、`wants/`。
- 前端 CSS/JS 用 `?v=N` 缓存击穿:`cards-data.js` / `wants-data.js` / `app.js` / `style.css` 均由 `build_data.py` 的 `bump_cache_buster` 用内容哈希自动 bump,bump 只发生在部署 artifact 里,不回写 master、无需手动。
- Pages 配置:`build_type: workflow`(GitHub Actions 部署),非 legacy 分支发布。自定义域名 `claystan.cc` 靠 artifact 内的 `CNAME` 文件。
- 全局规则:commit message 与 PR 描述用英文;本机不主动 `git commit` / `git push`,需用户明确指示。
