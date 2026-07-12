# 万智牌 Sales List

静态 **万智牌在售清单** 网站：多人展示实体库存，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/  
- **仓库**：https://github.com/ClayStan404/mtg-showcase  
- **分支**：`master`  
- **卖家填写说明**：[docs/卖家如何更新库存.md](./docs/卖家如何更新库存.md)  
- **求购说明**：[docs/求购如何发布.md](./docs/求购如何发布.md)

**不做站内下单/支付。** 库存以表格为准，网站为展示与沟通辅助。

---

## 卖家必读

1. 打开 **[WPS库存](https://www.kdocs.cn/l/cgyl3WizNfp7)**（金山文档）  
2. 在 **「模板」** 工作表上 **右键 → 创建副本**，再 **重命名为自己的名字**  
3. 若没有编辑权限，联系 QQ **417592443** 申请  
4. 在自己的表里填：昵称 / 城市 / 联系 + 卡牌行，保存即可  
5. **每天固定时间**汇总后更新网站  

### 表格简写

| 字段 | 规则 |
|------|------|
| 语言 | `e`=英文 · `z`=中文 · `j`=日文 · `o`=其他（空默认 `e`） |
| 闪 | 空或 `0`=非闪 · `1`=闪 |
| 数量 | 空=1 |

卖光请 **删行**。

---

## 买家

### 在售
- 搜索、筛选：出售人 / 城市 / 语言 / 闪卡  
- **意向清单**：加入卡牌 → 复制文本或截图模式 → 发给对应卖家  

### 求购
1. 打开 **[WPS求购](https://www.kdocs.cn/l/cvvaN21e3gm8)**  
2. 在 **「模板」** 上 **右键 → 创建副本**，**重命名为自己的名字**  
3. 无权限时联系 QQ **417592443** 申请编辑  
4. 填写后保存；格式：`系列 编号 [语言] [闪] [必须]`  
   - 必须 `1` = 只要此印刷  
   - 必须 `0`/空 = 其他版本也可以（以该印刷为参考）  

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

# 在售数据
python3 scripts/build_data.py
# 求购数据（wants/*.txt）
python3 scripts/build_wants.py

git add inventory wants data assets/cards-data.js assets/wants-data.js
git commit -m "Update inventory/wants"
git push origin master
```
