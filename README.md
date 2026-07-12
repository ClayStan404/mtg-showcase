# 万智牌 Sales List

静态 **万智牌在售清单** 网站：多人展示实体库存，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/  
- **仓库**：https://github.com/ClayStan404/mtg-showcase  
- **分支**：`master`  

**不做站内下单/支付。** 库存以表格为准，网站为展示与沟通辅助。

卖家/买家使用说明已内嵌在网站上（首页「使用说明」折叠面板）。

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
