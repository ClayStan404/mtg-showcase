# 万智牌 Sales List

静态 **万智牌在售 + 求购清单** 网站：多人展示实体库存与求购，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/
- **管理后台**：https://claystan.cc/admin/（邀请制登录）

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
