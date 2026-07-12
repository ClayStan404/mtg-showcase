# 如何通过 PR 提交自己的卡牌

本站接受社区贡献的**实体库存展示**。你只需提交一份清单文件，无需会写前端。

## 步骤

1. **Fork** 本仓库，并 `git clone` 你的 fork  
2. 复制模板：

   ```bash
   cp inventory/_template.txt inventory/你的英文id.txt
   ```

   文件名请用英文/数字（例如 `alice.txt`）。以 `_` 开头的文件是模板，不会被收录。

3. 编辑文件头部与卡表：

   ```text
   # seller: 小明
   # city: 杭州
   # contact: 微信 example_wx
   #
   # Sol Ring
   cmm 703
   2x mh3 224 z f
   ```

4. 本地可选校验：

   ```bash
   python3 scripts/build_data.py --validate-only
   ```

5. 提交 PR 到 `master`  
   - **只需包含** `inventory/你的文件.txt`  
   - 不必运行完整 build，也不必改 `data/cards.json`（维护者合并后会重新生成）

6. 合并后站点更新：维护者执行 `python3 scripts/build_data.py` 并推送，或由 CI 自动构建。

## 字段说明

| 头部字段 | 必填 | 说明 |
|----------|------|------|
| `seller` | 是 | 出售人昵称（网页展示与筛选） |
| `city` | 是 | 城市（网页展示与筛选） |
| `contact` | 否 | 联系方式，显示在卡牌详情 |

| 卡表字段 | 说明 |
|----------|------|
| `Nx` | 可选数量，如 `2x` |
| `set` | 系列缩写 |
| `number` | 收集编号 |
| `lang` | 可选：`z` 简中 · `j` 日文 · 省略=英文 |
| `foil` | 可选：`f` / `foil` / `闪` |

> `f` 表示闪卡，不是法文。

## 规范

- 品相默认 NM，本站不展示品相/价格  
- 只展示与站外联系，不在站内完成交易  
- 请勿提交与他人重复占用的虚假库存；维护者有权拒绝或删除  
- 卡图由 Scryfall 自动匹配，请保证系列缩写 + 编号正确  

## 更新自己的库存

直接改自己的 `inventory/xxx.txt` 再提 PR 即可（增删行、改数量）。
