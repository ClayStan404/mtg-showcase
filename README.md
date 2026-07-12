# MTG 库存展示站

基于 **GitHub Pages** 的静态万智牌实体库存展示：本地用与 [MTGImgDownloader](https://github.com/ClayStan404/MTGImgDownloader) 相同的清单格式记录卡牌，构建脚本从 Scryfall（及 mtgch 中文名）拉取信息，生成可检索的网页。

- 仓库：https://github.com/ClayStan404/mtg-showcase  
- 站点：https://claystan404.github.io/mtg-showcase/  
- 默认分支：`master`

**只做展示 + 联系方式，不做站内交易。** 当前 `inventory.txt` 为约 100 种演示卡，可替换为真实库存后重新 build。

## 你需要维护的只有两份东西

1. **`inventory.txt`** — 库存清单  
2. **`site_config.json`** — 站点标题与联系方式  

其余 `data/cards.json` 由脚本生成。

## 清单格式

与 MTGImgDownloader 的 `MTGCardList` 兼容，并支持可选数量前缀：

```text
# [Nx] set number [lang] [foil]
iko 185
2x mh3 224
rna 245 z
2x2 361 z f
spg 105 foil
```

| 字段 | 说明 |
|------|------|
| `Nx` | 可选数量，如 `2x` / `x3`，默认 1；相同卡会合并数量 |
| `set` | 系列缩写 |
| `number` | 收集编号（支持 `105a` 等） |
| `lang` | 可选：`z` 简中 · `j` 日文 · 省略=英文（其余短码同 downloader） |
| `foil` | 可选：`f` / `foil` / `1` / `闪` |

> 注意：`f` 一律表示 **闪卡**（与 downloader 一致），不是法文。

## 网站上展示的字段

| 字段 | 来源 |
|------|------|
| 中/英牌名 | Scryfall + mtgch |
| 牌面文字 | Scryfall 印刷文本（对应语言） |
| 是否闪卡 | 清单 |
| 系列名 / 缩写 / 编号 | Scryfall |
| 数量 | 清单 |
| 卡图 | Scryfall CDN（每种一条记录一张图） |

品相固定 NM、稀有度、价格、售卖流程等均不展示。

## 本地构建

```bash
cd /home/claystan/wks/mtg
python3 -m venv .venv && source .venv/bin/activate   # 可选
pip install -r requirements.txt

# 编辑 inventory.txt / site_config.json 后：
python3 scripts/build_data.py

# 预览
python3 -m http.server 8080
# 浏览器打开 http://127.0.0.1:8080
```

## 部署 GitHub Pages

1. 新建公开仓库，把本目录推上去（需包含生成后的 `data/cards.json`）  
2. 仓库 **Settings → Pages → Source**：`Deploy from a branch` → `main` / `/ (root)`  
3. 访问 `https://<user>.github.io/<repo>/`  

之后改库存的流程：

```text
改 inventory.txt → python3 scripts/build_data.py → git commit & push
```

卡图走 Scryfall 外链，仓库体积很小。

## 目录结构

```text
mtg/
├── inventory.txt          # 你维护
├── site_config.json       # 你维护
├── scripts/build_data.py  # 解析 + 拉取元数据
├── data/cards.json        # 生成物
├── index.html
├── assets/
└── README.md
```
