# MTG 库存展示站

基于 **GitHub Pages** 的静态万智牌实体库存展示。支持**多人通过 PR 提交自己的卡牌**，可按出售人昵称、城市、系列、语言、闪卡筛选。

- 仓库：https://github.com/ClayStan404/mtg-showcase  
- 站点：https://claystan404.github.io/mtg-showcase/  
- 默认分支：`master`  
- 贡献指南：[CONTRIBUTING.md](./CONTRIBUTING.md)

**只做展示 + 联系方式，不做站内交易。**

## 目录结构

```text
mtg/
├── inventory/                 # 每人一个清单文件（PR 主要改这里）
│   ├── _template.txt          # 模板（不会被收录）
│   ├── demo-host.txt
│   └── demo-guest.txt
├── site_config.json           # 站点标题 / 页脚联系
├── scripts/build_data.py      # 解析 + 拉取元数据
├── data/cards.json            # 生成物（站点读取）
├── index.html
├── assets/
├── CONTRIBUTING.md
└── README.md
```

## 库存文件格式

```text
# seller: 小明
# city: 杭州
# contact: 微信 example_wx
#
# [Nx] set number [lang] [foil]
iko 185
2x mh3 224 z f
```

| 字段 | 说明 |
|------|------|
| `seller` / `city` | 出售人昵称、城市（展示 + 筛选） |
| `contact` | 可选，详情页联系方式 |
| 卡表 | 与 [MTGImgDownloader](https://github.com/ClayStan404/MTGImgDownloader) 兼容 |

> `f` = 闪卡（不是法文）。

## 网站字段

| 字段 | 来源 |
|------|------|
| 中/英牌名、牌面文字、系列、卡图 | Scryfall (+ mtgch 中文名) |
| 是否闪、数量 | 清单 |
| 出售人、城市、联系 | 清单文件头 |

## 本地构建

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 只校验清单（适合 PR）
python3 scripts/build_data.py --validate-only

# 生成 data/cards.json（会复用已有 JSON / .cache 加速）
python3 scripts/build_data.py

python3 -m http.server 8080
```

维护者更新站点：

```text
合并 PR → python3 scripts/build_data.py → commit data/cards.json → push master
```

## PR 提交流程（贡献者）

见 [CONTRIBUTING.md](./CONTRIBUTING.md)。贡献者只需新增/修改 `inventory/你的id.txt`，不必提交 `data/cards.json`。
