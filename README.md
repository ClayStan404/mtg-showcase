# 万智牌 Sales List

静态 **万智牌在售清单** 网站：多人展示实体库存，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/  
- **仓库**：https://github.com/ClayStan404/mtg-showcase  
- **分支**：`master`  
- **卖家填写说明**：[docs/卖家如何更新库存.md](./docs/卖家如何更新库存.md)

**不做站内下单/支付。** 库存以表格为准，网站为展示与沟通辅助。

---

## 给卖家（普通用户）

不需要 GitHub 账号。

1. 打开库存云文档（一人一张表）：  
   **[WPS库存协作模板](https://www.kdocs.cn/l/cgyl3WizNfp7)**（金山文档）  
2. 填：昵称 / 城市 / 联系 + 卡牌行  
3. 保存即可；**每天固定时间**汇总后更新网站  

### 表格简写

| 字段 | 规则 |
|------|------|
| 语言 | 空=英文 · `z`=中文 · `j`=日文 · `o`=其他 |
| 闪 | 空或 `0`=非闪 · `1`=闪 |
| 数量 | 空=1 |

卖光请 **删行**。同卡合并一行用数量。

本地备份模板：[`templates/WPS库存协作模板.xlsx`](./templates/WPS库存协作模板.xlsx)

---

## 给访客（买家）

- 搜索、筛选：出售人 / 城市 / 语言 / 闪卡  
- **意向清单**：加入卡牌 → 复制文本或截图模式 → 发给对应卖家  
- 卖家联系方式见 **卡牌详情** 与 **清单分组**

---

## 给维护者（你）

### 推荐发布节奏

```text
白天：卖家在 WPS 改自己的 sheet
定点（或手动）：导出 xlsx → 解析 → build → push → Pages 更新
```

不必每次改表都跑 CI，一天一次即可。

### 从 WPS 导出到上线

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 校验 WPS 导出的表格（不写文件）
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx --dry-run

# 写入 inventory/*.txt
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx

# 拉取 Scryfall 元数据，生成站点数据
python3 scripts/build_data.py

git add inventory data/cards.json assets/cards-data.js
git commit -m "Update inventory from WPS"
git push origin master
```

### 仅校验 / 本地预览

```bash
python3 scripts/build_data.py --validate-only
python3 -m http.server 8080   # http://127.0.0.1:8080/
```

---

## 目录结构

```text
mtg/
├── templates/
│   └── WPS库存协作模板.xlsx   # 导入金山 WPS 用
├── docs/
│   └── 卖家如何更新库存.md
├── inventory/                 # 解析后的内部清单（每人一个 .txt）
│   └── _template.txt
├── scripts/
│   ├── inventory_format.py    # 语言/闪/数量统一约定
│   ├── parse_wps_excel.py     # WPS xlsx → inventory/*.txt
│   └── build_data.py          # inventory → cards.json + cards-data.js
├── data/cards.json            # 生成物
├── assets/
│   ├── cards-data.js          # 生成物（内嵌数据，减少额外请求）
│   ├── app.js
│   └── style.css
├── index.html
├── site_config.json           # 站点标题等
├── CNAME                      # claystan.cc
└── README.md
```

---

## 内部清单格式（inventory/*.txt）

由 `parse_wps_excel.py` 生成，也可手写：

```text
# seller: ClayStan
# city: 武汉
# contact: 微信 xxx
#
msc 211 z 1
2x mh3 224
iko 185 j
```

| 片段 | 含义 |
|------|------|
| `2x` | 数量 2（省略则 1） |
| `z` / `j` / `o` | 中 / 日 / 其他（省略=英文） |
| `1` | 闪卡（省略或 `0`=非闪；兼容旧写法 `f`/`foil`） |

卡图与牌名等展示字段由 **Scryfall**（及 mtgch 中文名）在 `build_data.py` 中补全。

---

## 站点功能摘要

| 功能 | 说明 |
|------|------|
| 静态托管 | GitHub Pages + 自定义域 `claystan.cc` |
| 筛选 | 出售人、城市、语言、闪卡 |
| 意向清单 | localStorage；复制文本 / 截图模式 |
| 手机 | 筛选默认折叠；下滑隐藏搜索栏 |

---

## 规划中（可选）

- 金山 WPS 定时拉表（代替手动导出）  
- QQ 机器人收表 / 通知「今日已发布」  
- GitHub Actions 仅作每日一次或手动触发 build  

当前以 **WPS 填表 + 维护者定点发布** 为主路径。
