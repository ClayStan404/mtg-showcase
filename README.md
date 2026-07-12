# 万智牌 Sales List

静态 **万智牌在售清单** 网站：多人展示实体库存，买家可检索、加意向清单并截图/复制后站外联系卖家。

- **站点**：https://claystan.cc/
- **仓库**：https://github.com/ClayStan404/mtg-showcase
- **分支**：`master`

**不做站内下单/支付。** 库存以 WPS 协作文档为准，网站为展示与沟通辅助。

卖家/买家使用说明已内嵌在网站上（首页「使用说明」折叠面板）。

---

## 数据流

```
WPS 在售协作文档 ──→ fetch_wps_share.py ──→ parse_wps_excel.py ──→ inventory/*.txt
WPS 求购协作文档 ──→ fetch_wps_share.py ──→ parse_wps_wants_excel.py ──→ wants/*.txt
                                                                              │
                                    build_data.py / build_wants.py ←──────────┘
                                          (Scryfall 元数据富化)
                                              │
                                    data/*.json + assets/*-data.js
                                              │
                                    git commit & push → GitHub Pages
```

**GitHub Actions 每小时自动同步**：self-hosted runner 从 WPS 分享链接下载最新 xlsx → 解析 → Scryfall 富化 → 部署到 claystan.cc。

详见 [QWEN.md](QWEN.md)。

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 本地预览
python3 -m http.server  # → http://localhost:8000

# 手动触发 GitHub Actions
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase
```

---

## 致谢

### Scryfall

本项目使用 [Scryfall](https://scryfall.com/) API 获取卡牌元数据（名称、图片、规则文字等）。

**我们的使用遵循 Scryfall API 规则**：

- ✅ 仅通过 HTTPS 请求，设置准确的 `User-Agent`（`MTGShowcase/1.0`）
- ✅ 遵守 API 速率限制（请求间隔 ≥ 0.12s）
- ✅ 不设付费墙 — 网站完全免费，无账户系统
- ✅ 不重新发布或代理 Scryfall 原始数据 — 本项目在卡牌数据上叠加库存管理、搜索、多卖家展示等额外功能
- ✅ 不修改卡牌图片 — 原样展示，无裁剪、水印或变形
- ✅ 非 Scryfall 认可的关联方

Scryfall 的卡牌数据和图片数据库在 [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fan-content-policy) 下免费提供。

相关文档：

- [Scryfall API 文档与使用规则](https://scryfall.com/docs/api)
- [Scryfall 服务条款](https://scryfall.com/terms)
- [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fan-content-policy)

MTG 卡牌图像和相关信息版权归 Wizards of the Coast, LLC 所有。

### 金山文档 (WPS)

本项目使用 [金山文档](https://www.kdocs.cn/) 在线协作表格作为多人库存协作的数据源。

---

## License

[MIT License](LICENSE)
