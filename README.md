# 万智牌 Sales List

静态 **万智牌在售 + 求购清单** 网站：多人展示实体库存与求购，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/
- **管理后台**：https://claystan.cc/admin/（邀请制登录）
- **仓库**：https://github.com/ClayStan404/mtg-showcase
- **分支**：`master`（只存源码；构建产物不入库）

**不做站内下单/支付。** 库存/求购在 admin 写入 **Supabase**；公开展示读的是 **构建后的 JSON 快照**（不是访客直查数据库）。

卖家/买家使用说明见网站首页「使用说明」折叠面板。

---

## 架构一览

```
卖家/买家 ──admin SPA──► Supabase（profiles / inventory / wants）
                              │
          保存后约 45s 自动同步 / 「立即同步」 / 每小时 cron / push 代码
                              │  Edge Function publish → GitHub Actions
                              ▼
                    export → Scryfall(+mtgch) 富化 → cards.json / wants.json
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
   Supabase Storage（site-data/）      GitHub Pages（HTML/CSS/JS 壳）
   主站优先读这份快照                  push 或 mode=full 时才整站部署
```

| 角色 | 数据怎么走 |
|------|------------|
| 卖家改库存 | 实时写 Supabase |
| 主站访客看列表 | 读 Storage 上的 `cards.json`（热链卡图 CDN）；失败才回退内联数据 |
| 立即同步 / 自动同步 | 全量 export + 重建快照并上传 Storage（**不是**只更新一张卡；Scryfall 磁盘缓存会加速） |
| 改前端代码 | `push master` → 整站 Pages 部署 |

监控：`heartbeat.yml` 约每 **2 小时**检查同步新鲜度（仅 schedule，不在每次 auto-update 后触发）；超过约 2 小时无成功构建会开 issue，恢复后关 issue 最多延迟约 2 小时。

---

## 本地开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 从 Supabase 导出并构建（需 service_role）
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/export_inventory_to_txt.py
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/export_wants_to_txt.py
python3 scripts/build_data.py
python3 scripts/build_wants.py
SUPABASE_SERVICE_ROLE_KEY=<key> python3 scripts/upload_site_data.py

# 测试 / lint
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
ruff check scripts/ tests/
```

手动触发 Actions：

```bash
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase -f mode=data   # 只刷 Storage 快照
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase -f mode=full   # 快照 + Pages
```

个人库存手记（可选）：根目录 `claystan.txt`（卖家自用记录，非运行时必读）。

---

## 配置要点（`site_config.json`）

| 字段 | 含义 |
|------|------|
| `supabase_url` / `supabase_anon_key` | 公开；写入前端 `site` 字段 |
| `image_cdn` | `"scryfall"`（当前生产）或 `"mtgch"`：快照里卡图热链优先哪个 CDN；改完需重新 build |

中文库存（`lang=zhs`）会优先中文卡面；若数据源无该印刷中文图，保留英文图并显示 **「无中文印刷图」** 角标。

---

## 致谢

### Scryfall

本项目使用 [Scryfall](https://scryfall.com/) API 获取卡牌元数据（名称、规则文字、印刷信息等），并常热链其图片 CDN。

**使用遵循 Scryfall API 规则**：

- 仅 HTTPS，准确 `User-Agent`（`MTGShowcase/1.0`）
- 遵守速率限制（请求间隔 ≥ 0.12s）
- 不设付费墙；站内无支付
- 不重新发布/代理原始 dump；在库存与展示上叠加自有功能
- **图片热链 CDN URL**（`cards.scryfall.io` 等），不下载、不存图、不裁剪水印
  - [官方允许热链说明](https://scryfall.com/blog/upcoming-api-changes-to-scryfall-image-uris-and-download-uris-224)
- 非 Scryfall 认可关联方

相关文档：[API](https://scryfall.com/docs/api) · [图片](https://scryfall.com/docs/api/images) · [条款](https://scryfall.com/terms) · [WotC Fan Content Policy](https://company.wizards.com/en/legal/fan-content-policy)

MTG 卡牌图像及相关信息版权归 Wizards of the Coast, LLC 所有。

### mtgch

本项目使用 [mtgch](https://mtgch.com/) API（`https://mtgch.com/api/v1/card/{set}/{number}/`，文档：https://mtgch.com/api/v1/docs）：

- **中文名**（含非中文印刷的译名）
- **可选中文卡面 / 图链**（`zhs_image_uris`、`images.mtgch.com`）
- admin 即时补图：mtgch 优先，Scryfall 兜底
- build 快照：元数据以 Scryfall 为主；图 CDN 由 `image_cdn` 配置；`lang=zhs` 优先中文卡面
- 结果磁盘缓存（`.cache/`）；**访客浏览不打卡牌 API**，只热链快照里的图片 URL

---

## License

[MIT License](LICENSE)
