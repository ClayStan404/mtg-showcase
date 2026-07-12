# 万智牌 Sales List

静态 **万智牌在售清单** 网站：多人展示实体库存，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/  
- **仓库**：https://github.com/ClayStan404/mtg-showcase  
- **分支**：`master`  
- **卖家填写说明**：[docs/卖家如何更新库存.md](./docs/卖家如何更新库存.md)

**不做站内下单/支付。** 库存以表格为准，网站为展示与沟通辅助。

---

## 卖家必读

1. 打开库存云文档（一人一张表）：  
   **[WPS库存协作模板](https://www.kdocs.cn/l/cgyl3WizNfp7)**（金山文档）  
2. 填：昵称 / 城市 / 联系 + 卡牌行  
3. 保存即可；**每天固定时间**汇总后更新网站  

### 表格简写

| 字段 | 规则 |
|------|------|
| 语言 | `e`=英文 · `z`=中文 · `j`=日文 · `o`=其他（空默认 `e`） |
| 闪 | 空或 `0`=非闪 · `1`=闪 |
| 数量 | 空=1 |

卖光请 **删行**。

---

## 买家

- 搜索、筛选：出售人 / 城市 / 语言 / 闪卡  
- **意向清单**：加入卡牌 → 复制文本或截图模式 → 发给对应卖家  
- 卖家联系方式见 **卡牌详情** 与 **清单分组**

---

## Dev

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

