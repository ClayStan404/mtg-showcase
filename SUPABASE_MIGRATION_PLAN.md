# MTG Showcase 迁移 Supabase 方案(全面抛弃 WPS)

> 卖家在网页(admin)管理**库存**、买家管理**求购**,完全替换 WPS;买家继续看静态站。本文档记录完整方案、关键决策和我踩过的坑,供接手实现参考。

## 1. 现状(必读)

两条对称的 pipeline,都从 WPS 读:

**库存(inventory,卖家出售):**
`WPS xlsx -> fetch_wps_share.py -> parse_wps_excel.py -> inventory/*.txt -> build_data.py -> data/cards.json`

**求购(wants,买家求购):**
`WPS xlsx -> fetch_wps_share.py -> parse_wps_wants_excel.py -> wants/*.txt -> build_wants.py -> data/wants.json`

- **关键接口**:`inventory/*.txt` 和 `wants/*.txt` 是 parse 层和 build 层之间的文本接口。迁移后**只换数据源(WPS -> Supabase)+ 扩展格式(加 price/note)**,build 脚本仍读 txt,但解析函数按新格式重写(见第 5 节)。
- 字段约定(迁移后,见第 5 节格式):
  - lang:`e`/`z`/`j`/`o`(内部 `en`/`zhs`/`ja`/`other`)
  - foil:`0`/`1`;qty:空=1;**price:空=0(市价)**;**must(wants):空=0(可替)**
  - **note**:`#` 后到行尾(inventory 新增,wants 已有)
- meta 头(`# seller:`/`# city:`/`# contact:`):**录入侧不写**(seller=登录用户,city/contact 在 profiles 管);export 脚本自动从 profiles 补进 txt 头给 build(见第 5 节 meta 分工)
- 主站 `assets/app.js` 的 `loadData()` 读 `window.__MTG_DATA__`(inlined cards-data.js)或 `fetch data/cards.json`;wants 同理
- 主站卡片渲染:`app.js` 的 `cardHtml(c)`,图片用 `c.image.normal`(Scryfall CDN);**新增展示 price/note**
- 买家不登录看静态展示;卖家/买家在 admin 管理(登录入口在主站,见第 7 节)

## 2. 架构:读写分离(inventory + wants 都迁)

```
卖家/买家(写,慢可忍)  admin SPA ──> Supabase(Tokyo)
                                   │   ├─ profiles(卖家/买家共用,账号绑定)
                                   │   ├─ inventory(seller_id) + price + note
                                   │   └─ wants(buyer_id) + price + note
                       hourly cron / "立即发布"按钮(Edge Function -> workflow_dispatch)
                                   ▼
                   export 脚本: Supabase -> inventory/*.txt + wants/*.txt(自动补 meta 头)
                                   ▼
                   build_data.py / build_wants.py(行解析按新格式重写) -> cards.json / wants.json
                                   ▼
买家(读,快)        静态站读 cards.json + wants.json(GitHub Pages)
```

核心:**txt 接口复用,build 脚本仍读 txt**(但行解析函数重写以支持 price/note)。WPS 彻底退役。

主站登录态:未登录买家看静态展示(零变化);登录后显"管理"按钮跳 `/admin/`(见第 7 节)。

## 3. Supabase 项目

- 区域:**Tokyo**(`ap-northeast-1`)
- Auth:邮箱+密码,**邀请制**(Dashboard 关闭 "Allow new users to sign up")
- 已建项目(可复用):URL `https://rkvtizboyikrjowfogoc.supabase.co`,anon key 见附录 A
- `service_role` key:**保密**,只进 GitHub Actions secret + 本地 env,**绝不进前端**
- 一个用户可同时是卖家和买家(profiles 共用:有 inventory 行就是卖家,有 wants 行就是买家)
- Supabase MCP 工具:`apply_migration`、`execute_sql`、`deploy_edge_function`、`get_advisors`、`get_publishable_keys`

## 4. 数据库 schema + RLS

> **接手注意**:已建项目 schema 现状见附录 A(profiles + inventory + wants + publish_log 都已建,wants 数据空)。本节是**目标 schema**:加 price/note、改 unique、删 publish_log、加 seller_name partial unique。用 `apply_migration` 增量改。

```sql
-- profiles: 扩展 auth.users,卖家/买家共用。seller_name 唯一(partial,允许空未填)
create table public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  seller_name text not null default '',   -- 卖家昵称(也作买家昵称);唯一约束见下方 partial index
  city        text not null default '',
  contact     text not null default '',
  created_at  timestamptz not null default now()
);
-- seller_name 唯一:只约束非空值,空字符串(未填)不参与,允许多个未填 profile 共存
-- (handle_new_user 触发器建用户时插空 profile,seller_name='')
create unique index profiles_seller_name_uniq
  on public.profiles (seller_name) where seller_name <> '';

-- inventory: 卖家库存。set_code(NOT "set",SQL 保留词);lang 存内部码;+price +note
create table public.inventory (
  id         uuid primary key default gen_random_uuid(),
  seller_id  uuid not null references public.profiles(id) on delete cascade,
  set_code   text not null,
  number     text not null,
  lang       text not null default 'en',
  foil       boolean not null default false,
  quantity   integer not null default 1 check (quantity >= 1),
  price      numeric(10,2) not null default 0,  -- 0=按市价/私聊;>0=固定每张价
  note       text not null default '',          -- 备注(卡牌特殊情况,对应 txt # note)
  updated_at timestamptz not null default now()
);
-- 同卡不同价/不同备注算独立条目(上架两次):命名 unique index(drop 语法统一 drop index)
create unique index inventory_uniq on public.inventory (seller_id, set_code, number, lang, foil, price, note);
create index inventory_seller_id_idx on public.inventory(seller_id);

-- wants: 买家求购。比 inventory 多 must;+price +note
create table public.wants (
  id         uuid primary key default gen_random_uuid(),
  buyer_id   uuid not null references public.profiles(id) on delete cascade,
  set_code   text not null,
  number     text not null,
  lang       text not null default 'en',
  foil       boolean not null default false,
  quantity   integer not null default 1 check (quantity >= 1),
  must       boolean not null default false,  -- false=可替其他版,true=必须此印刷
  price      numeric(10,2) not null default 0,  -- 0=面议/私聊;>0=出价
  note       text not null default '',          -- 备注
  updated_at timestamptz not null default now()
);
create unique index wants_uniq on public.wants (buyer_id, set_code, number, lang, foil, must, price, note);
create index wants_buyer_id_idx on public.wants(buyer_id);

-- updated_at 触发器(两个表)
create or replace function public.touch_updated_at()
returns trigger language plpgsql set search_path = public as $$
begin new.updated_at = now(); return new; end; $$;
drop trigger if exists inventory_touch_updated_at on public.inventory;
create trigger inventory_touch_updated_at
  before update on public.inventory for each row execute function public.touch_updated_at();
drop trigger if exists wants_touch_updated_at on public.wants;
create trigger wants_touch_updated_at
  before update on public.wants for each row execute function public.touch_updated_at();

-- auth.users 新用户自动建 profiles 行
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end; $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users for each row execute function public.handle_new_user();
-- 关键:revoke execute from public,否则 handle_new_user 暴露为可公开调用 RPC
revoke execute on function public.handle_new_user() from public;

-- RLS
alter table public.profiles   enable row level security;
alter table public.inventory  enable row level security;
alter table public.wants      enable row level security;

create policy "profiles select own" on public.profiles for select using (auth.uid() = id);
create policy "profiles update own" on public.profiles for update using (auth.uid() = id) with check (auth.uid() = id);

create policy "inventory select own" on public.inventory for select using (auth.uid() = seller_id);
create policy "inventory insert own" on public.inventory for insert with check (auth.uid() = seller_id);
create policy "inventory update own" on public.inventory for update using (auth.uid() = seller_id) with check (auth.uid() = seller_id);
create policy "inventory delete own" on public.inventory for delete using (auth.uid() = seller_id);

create policy "wants select own" on public.wants for select using (auth.uid() = buyer_id);
create policy "wants insert own" on public.wants for insert with check (auth.uid() = buyer_id);
create policy "wants update own" on public.wants for update using (auth.uid() = buyer_id) with check (auth.uid() = buyer_id);
create policy "wants delete own" on public.wants for delete using (auth.uid() = buyer_id);
```

**关键决策**:
- `publish_log` 表**砍掉**(原防抖需求取消,见第 8 节)。已建项目里若有,`drop table public.publish_log;`。
- `seller_name` 用 **partial unique index**(`where seller_name <> ''`)而非列级 unique -- 否则两个未填昵称的新用户(空字符串)会撞约束导致注册失败。改昵称撞名时数据库报冲突,admin 前端友好提示。
- inventory/wants 的 unique 含 `price + note`:同卡不同价/不同品相算独立条目(上架两次)。**已建项目有旧 unique 约束(`inventory_seller_id_set_code_number_lang_foil_key` / `wants_buyer_id_set_code_number_lang_foil_must_key`,不含 price/note),必须先 drop 再建新的,否则同卡不同价第二行撞旧约束失败**(语句见步骤 1)。合并按 price+note 分组(见第 5 节全链路清单)。note 写入前 `strip()` 归一化,避免尾空格导致同 note 算两条。
- price 用 `numeric(10,2) not null default 0`,不用 nullable -- 0=市价,排序时 0 自然排最前,无需处理 null。展示层把 0 渲染成"市价/私聊"文案。

## 5. txt 格式约定(空格 + # note)

> 替代旧的 `[Nx] set number lang foil` 和 CSV 方案。**统一空格分隔 + `#` note**,录入快、无歧义、兼容现有 `claystan.txt`。

### 行格式

```
inventory: set number lang foil [qty] [price] [# note]
wants:     set number lang foil [qty] [must] [price] [# note]
```

- **空格分隔**,字段按位置依次填,**尾部可省略**(省略=默认值)
- **`#` 后到行尾 = note**(可含空格,不含 `#`);无 `#` 则无 note
- **行首 `#`** 仍是 meta/注释(export 补的 `# seller:` 等),不冲突(note 的 `#` 总在字段后)

### 默认值

| 字段 | 默认 | 说明 |
|---|---|---|
| lang | `e`(en) | 中间字段,总要写 |
| foil | `0`(非闪) | 中间字段,总要写 |
| qty | `1` | 尾部可省略 |
| price | `0`(市价/私聊) | 尾部可省略;0=按市价 |
| must(wants) | `0`(可替) | 尾部可省略 |

**中间字段不能跳过**:lang/foil 总要写;wants 填 price 时 must 也要显式写(must 在 price 前);若 qty 用默认但 price 有值,qty 要显式写 `1`。

### 例子

```
inventory:
  sta 124 j 0              1张 市价
  sta 124 j 0 2            2张 市价
  sta 124 j 0 2 50         2张 50元/张
  sta 124 j 0 # 右下角破损  1张 市价 备注"右下角破损"
  sta 124 j 0 2 50 # 签名   2张 50元 签名

wants(must 在 qty 和 price 之间):
  sta 124 j 0 2            2张 市价 可替
  sta 124 j 0 2 1          2张 市价 必须此版
  sta 124 j 0 2 1 50       2张 50元 必须此版
  sta 124 j 0 2 0 50       2张 50元 可替(must 显式写 0,因 price 在后)
  sta 124 j 0 2 1 50 # 急收  2张 50元 必须此版 备注"急收"
```

### meta 分工(关键)

- **录入侧(admin 批量/导入/手写)**:**不写 meta 头**。seller=登录用户,city/contact 在 profiles 表管(账号绑定)。
- **内部 txt(export 生成 -> build 读)**:export 脚本从 profiles 自动补 `# seller:`/`# city:`/`# contact:` 头。`build_data.py`/`build_wants.py` 照旧读 meta 头,**meta 读取逻辑不改**。
- profiles 是唯一权威源;txt 的 meta 是 export 抄的派生物(不入 git、不手维护、每次 deploy 重新抄)。
- 现有 `claystan.txt` 的 `# seller: claystan` 头,迁移时被 `migrate_wps_to_supabase.py` 读进 profiles,之后录入不再写 meta。
- **`claystan.txt` 迁移后定位**:迁移后 ClayStan 改走 admin 录入,`claystan.txt` 不再进 build(不落 `inventory/`)。**过渡期坑**:步骤 5 重写解析器(位置格式)后、步骤 6 切 workflow 前,本地跑 `build_data` 若读旧 `inventory/*.txt`(WPS 生成的 Nx 前置格式)会全行报错 -- 这段过渡期用新格式手写测试数据,或等 workflow 切换后测。

### 解析函数重写

`card_line_to_fields` / `want_line_to_fields`(Python,`inventory_format.py`)按新格式重写:
1. 先按第一个 `#` split:前半按空格 split 字段,后半 strip 作 note
2. 字段按位置依次填(set/number/lang/foil/qty/...),尾部缺失用默认值
3. 中间字段缺失报错(位置格式不能跳)

admin 侧 JS 版同步重写,和 Python 交叉测试(同输入同输出)。

### 加 price/note 的全链路改动清单

加 price+note 打破了"build 零改动",以下都要动:
1. schema:加 price/note(第 4 节)
2. txt 格式:本节
3. `cards_to_txt`/`wants_to_txt`:输出新格式(含 price/note)
4. `card_line_to_fields`/`want_line_to_fields`:解析新格式
5. `build_data.py`/`build_wants.py`:card/want 对象加 price/note 字段写进 json
6. **合并逻辑按 price+note 分组**:
   - `merge_cards`(`inventory_format.py:260`)/`merge_wants`(`parse_wps_wants_excel.py:136`)在 **WPS 残留脚本**里(调用点 `parse_wps_excel.py:170`、`parse_excel_order_txt.py:191`、`txt_to_wps_xlsx.py:105`、`parse_wps_wants_excel.py:188`),随第 6 节删除消失,**不用改**
   - 真正要改的是 build 脚本里的 **inline 合并 key**:`build_data.py:96`(单文件内)和 `:149`(跨文件)、`build_wants.py:152`(跨文件) -- 三处 key 都加 price+note
   - 同价同备注才合并数量;否则同卡不同价/不同备注保持独立条目
   - **删 `build_wants.py:158-161` 的 note `;` 拼接**:新分组语义下 note 是分组键、相同才合并,永远不走拼接分支,留着与分组语义矛盾
   - **新架构下合并基本是 no-op**:export 按 seller 一个文件 + DB unique 保证同 seller 同卡同价同 note 在 txt 里只出现一次,build 合并很少触发。真正关键的是第 7 点 id 唯一性(否则同卡不同价后条覆盖前条、`cardIndex` 丢数据)
7. **`card_id`/`wid` 必须加 price+note**(关键,否则同卡不同价 id 冲突):
   - `build_data.py:157` `card_id = {seller_id}-{set}-{number}-{lang}-{foil/nf}-{price}-{note}`
   - `build_wants.py:184` `wid = {buyer_id}-{set}-{number}-{lang}-{foil/nf}-{must}-{price}-{note}`
   - 前端 `app.js` 的 `cardIndex`(id->card Map)、购物车、模态框都按 id 查 -- id 不唯一会让同卡不同价的后条覆盖前条、数据丢失
   - note 进 id 含中文/空格/特殊字符,作 Map key 没问题;`app.js:130-134` 的 `refreshCardButton` 已用 `CSS.escape` 处理 `data-id` 选择器,加 note 后**回归测试含中文/空格/`"`/`]` 的卡**,确认所有 `data-id` 查询点都被 `CSS.escape` 覆盖。更稳的替代:note 不放原文,放短 hash/slugify,id 保持 ASCII 稳定,note 作独立字段
   - price 进 id 要统一格式化:**export 写 txt 时 price 一律 `f"{price:.2f}"`(始终 2 位,如 `50.00`),build 读回同样 `f"{:.2f}"` 进 id** -- 避免 `Decimal('50.00')`/`float 50.0`/`int 50` 的 str 表示往返不一致导致同卡 id 漂移、前端缓存失效
8. `app.js` cardHtml:展示 price(0->"市价/私聊")+ note
9. admin:CRUD 表单加 price/note,批量/导入 JS 解析

> price 字段为后续前端价格排序预留:`build_data.py:275` 的 sort 可选加 price,或前端加 sort UI;0(市价)排最前。

## 6. 脚本

### `scripts/export_inventory_to_txt.py`(替代 fetch_wps + parse_wps_excel)
- `service_role` key 调 Supabase REST bypass RLS,读 profiles + inventory(含 price/note)
- 按 seller 写 `inventory/{profile_uid}.txt`:
  - **文件名用 UID**(唯一,不冲突);build 脚本从 `# seller:` 头读昵称生成 seller_id,**不依赖文件名**(`profile_uid` ≠ build 里的 `seller_id`,后者是 `slugify(昵称)`)
  - export 自动补 meta 头:`# seller: {seller_name}` / `# city:` / `# contact:`(从 profiles)
  - 行格式按第 5 节:`set number lang foil qty price # note`。**price 一律写 `f"{price:.2f}"`(2 位小数,如 `50.00`)**,与 build 端 id 格式化对齐(见第 5 节清单 7)
- 先 `rm -f inventory/*.txt`
- **跳过 profile 不全的卖家**(seller_name/city/contact 任一空)-- 否则 `build_data.py` 的 `validate_meta` 会 `SystemExit(1)` 让整轮部署失败
- admin 应强制 seller_name/city/contact 填齐才允许发布:发布按钮旁显式提示「profile 缺 city/contact,发布后库存不展示」+ 跳转补全入口(运营保护,否则自己的库存会被 export 整批跳过、站点变空,且卖家不知为何)

### `scripts/export_wants_to_txt.py`(对称)
- 同上,读 profiles + wants(含 must/price/note)
- 按 buyer 写 `wants/{profile_uid}.txt`,行格式 `set number lang foil qty must price # note`

### `scripts/migrate_wps_to_supabase.py`(一次性)
- 读 `wps_inventory.xlsx` + `wps_wants.xlsx`(复用 `parse_wps_excel.parse_workbook` + `parse_wps_wants_excel.parse_workbook`)
- 需 `migration_mapping.json`:`{"昵称": "user-uid", ...}`(inventory 用 seller 昵称,wants 用 buyer 昵称;同一人同 UID)
  - 放项目根,加入 `.gitignore`(含 UID 不敏感但不必入库),一次性用完可删
- upsert profiles(写 seller_name/city/contact)+ delete 旧 + insert inventory + wants
- **原子性**:service_role 调 REST 不支持事务,中途失败会部分删部分插丢数据。按 seller 逐个迁移(每个 seller 内先 upsert 新数据、确认成功再 delete 旧),或依赖 unique 约束让脚本可安全重跑(upsert 幂等)
- WPS 模板若有价格/备注列就读进 price/note,没有则 price=0/note=''
- **注意**:inventory 的 `parse_wps_excel.parse_sheet` 现状**不存 note**(card dict 无 note 字段,只读不存),migrate 要读 WPS inventory 备注列需自己解析或先给 parse_sheet 补 note 字段;wants 的 `parse_wps_wants_excel.parse_sheet` 已存 note(`"note": note`),可直接复用。price 列两边模板都没有,迁移时一律 price=0
- env:`SUPABASE_SERVICE_ROLE_KEY`

### WPS 残留脚本(迁移后可删)
`fetch_wps_share.py`、`txt_to_wps_xlsx.py`、`parse_wps_excel.py`、`parse_wps_wants_excel.py`、`wps_excel_common.py`、`parse_excel_order_txt.py` -- WPS 退役后不再用,保留无害建议清理。

## 7. admin SPA 设计

### 路径 A:抽共享层(已定)

把主站 `app.js` 的展示/筛选/分页抽成 `assets/mtg-ui.js`,主站和 admin 各自入口 JS 引用,只管数据源 + 特有交互。理由:CRUD 越重,A 的"展示共享、交互分离"收益越大(B 模式开关会让 `cardHtml` 里 if 分支爆炸、`state` 里 cart/shotMode 和编辑态互相污染)。

**两个扩展点**:
1. **统一卡片视图模型**:定义 card 视图形状(set/number/lang/foil/qty/price/note/name_en/image/types/seller/city/contact/...)。主站从 cards.json 直接喂;admin 从 Supabase 行 + cards.json/wants.json 富化 join 后组装成同形状喂。共享层的 `cardHtml`/`matches`/`filters` 都基于这个视图模型,不假设数据来自 cards.json。
2. **卡片渲染钩子** `decorateCard(card, el)`:共享层渲染每张卡后调用。主站不注册(纯展示);admin 注册一个往卡片 DOM 塞"编辑/删除"按钮的回调。

**成本**:一次像样的重构(抽 `mtg-ui.js` + 主站回归测试 + 两个扩展点设计)。一次性,换主站干净 + admin 可持续扩展。

### 登录入口(主站)
- `index.html` 加登录按钮(Supabase Auth 邮箱密码,邀请制)
- 未登录:买家看静态展示(零变化),多个登录按钮
- 登录后:显"管理"按钮 -> 跳 `/admin/`(不手动输地址栏)
- 主站读 `site.supabase_url` + `site.supabase_anon_key`(来自 site_config.json,经 cards.json 的 `site` 字段下发,见第 10 节);不嵌 service_role
- 登录态检查:`@supabase/supabase-js` 从 localStorage 读 session,未登录无额外网络请求,不影响买家加载性能

### admin 双 tab(库存 + 求购)
- 复用主站 `view: sell | want` 切换,`activeList()` 据此返回 cards/wants
- 库存 tab:Supabase inventory(seller_id=uid) join `cards.json`
- 求购 tab:Supabase wants(buyer_id=uid) join `wants.json`
- 两个 tab 的 filters 已分两套(库存按 seller/lang/foil/type/cmc,求购按 kind=must/buyer)

### CRUD(库存 + 求购)
- **查**:列表 + 搜索 + 筛选 + 分页 = 共享层职责
- **增**:表单(set/number/lang/foil/qty/price/must/note) -> upsert Supabase。填 set/number 后实时调 Scryfall 拉图预览(确认加对卡)。Scryfall 公开 API 无需 key,注意速率。
- **删/改**:卡片上的编辑/删除按钮(钩子注入) -> 调 Supabase -> 更新本地 state -> 共享层 `renderGrid()` 重渲染
- 数据模型:admin 列表 = Supabase 行 left join cards.json/wants.json 富化(按 set/number/lang/foil)。join 上的显示名/图,join 不上的(刚加、还没 build)显示 set/number 占位 + 实时 Scryfall 预览兜底。
- cards.json/wants.json 路径:admin 在 `/admin/`,fetch `/data/cards.json`、`/data/wants.json`(绝对路径,同域)。

### 批量添加 / 从文件导入
- 批量:多行 `<textarea>`,粘贴第 5 节格式,JS 解析 -> 批量 upsert
- 导入:上传 txt(inventory/wants 格式;含 meta 头则忽略 seller/buyer 头),JS 解析。**仅支持新格式(空格+#)**,旧 `[Nx] set number lang foil` 格式不支持
- **owner 强制登录 UID**:导入/批量时 seller_id/buyer_id 强制为当前登录用户,不取文件里的 `# seller:`/`# buyer:` 头。RLS 兜底(`insert with check auth.uid()=seller_id`),前端主动设置避免无谓 403。
- JS 解析函数和 Python 版交叉测试(同输入同输出)

### 图片缓存复用
admin 列表图 URL 取 cards.json 的 `image.normal`(和主站同一份 URL) -> 浏览器 HTTP 缓存命中,主站加载过的图 admin 不重复下载。admin 新加的卡(cards.json 没有)实时调 Scryfall 拉,URL 和未来 build 一致,缓存可延续。不需要 Service Worker,浏览器默认缓存够用。

### 部署与依赖
- **源码目录**:admin 源码放项目根 `admin/`(`admin.html`/`admin.js`/`mtg-ui.js`),入 git;assemble 时 `cp -r admin site/admin` 进部署产物(`site/` 不入 git)。确认 `.gitignore` 不误伤 `admin/`。
- **Supabase client**:`@supabase/supabase-js`(CDN `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2` 或打包)。**主站懒加载**:点「登录」按钮才 `import()` 动态加载(约 50KB gzip,纯看牌买家首屏零成本,"不影响"是低估);admin 必然加载(CRUD)。session 存 localStorage,同域下主站登录后跳 `/admin/` 自动带 session,无需重登。
- **未登录访问 `/admin/`**:admin JS 检查 session,无则跳回主站登录页。

## 8. Edge Function: `publish`(立即发布)

> 防抖需求**砍掉**(publish_log 表删除)。GitHub workflow 有 `concurrency: group: deploy, cancel-in-progress: false`,多点几次只会排队不会并发污染。按钮节流交前端(点完禁用 60s)。

```ts
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization") ?? "";
  // verify_jwt: true 时 Supabase 网关已验签,到这里的必是有效登录用户
  // 只确认带 Bearer token 即可,不自解 JWT(atob 处理 base64url 会出错且多余)
  if (!auth.startsWith("Bearer ")) {
    return new Response(JSON.stringify({error:"unauthorized"}),{status:401});
  }
  const ghPat = Deno.env.get("GH_PAT");
  if (!ghPat) return new Response(JSON.stringify({error:"GH_PAT not configured"}),{status:500});
  const repo = Deno.env.get("GH_REPO") ?? "ClayStan404/mtg-showcase";
  const workflow = Deno.env.get("GH_WORKFLOW") ?? "auto-update.yml";
  const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,{
    method:"POST",
    headers:{Authorization:`Bearer ${ghPat}`,Accept:"application/vnd.github+json","User-Agent":"mtg-showcase-publish"},
    body: JSON.stringify({ref:"master"}),
  });
  if (!r.ok) return new Response(JSON.stringify({error:`github ${r.status}`}),{status:502});
  return new Response(JSON.stringify({ok:true}));
});
```

- `verify_jwt: true`;env:`GH_PAT`(fine-grained PAT,`actions:write`)、`GH_REPO`、`GH_WORKFLOW`
- **不配 `SUPABASE_SERVICE_ROLE_KEY`**(不写 publish_log,不需要 bypass RLS)
- **CORS**:主站 `claystan.cc`(GitHub Pages)调 `*.supabase.co`,带 Authorization 的 POST 触发 preflight(OPTIONS)。Supabase 网关默认处理 OPTIONS,但**建议函数内显式回 CORS headers**(`Access-Control-Allow-Origin: *`、`Allow-Headers: Authorization, Content-Type`、`Allow-Methods: POST, OPTIONS`,OPTIONS 直接 204 返回)更稳妥。部署后用 `curl -X OPTIONS` 实测 preflight 再下定论

## 9. workflow 改动(`.github/workflows/auto-update.yml`)

**inventory + wants 两侧都换:**
- 删 `Read WPS share IDs from site_config.json`(读已删的 `wps_*_url` 会崩)
- 删 `Fetch inventory/wants xlsx from WPS`
- 删 `Parse inventory`/`Parse wants`(parse_wps_*)
- 加:
  ```yaml
  - name: Export inventory from Supabase
    env:
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
    run: |
      rm -f inventory/*.txt
      python3 scripts/export_inventory_to_txt.py
  - name: Export wants from Supabase
    env:
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
    run: |
      rm -f wants/*.txt
      python3 scripts/export_wants_to_txt.py
  ```
- assemble:加 `cp -r admin site/admin 2>/dev/null || true`(admin/ 在步骤 7 建;切换 workflow 时若尚未建,cp 跳过不影响主站部署,避免 workflow fail)
- repo secrets:`SUPABASE_SERVICE_ROLE_KEY`
- `Notify on failure` 文案改:原"WPS Cookie 过期"-> Supabase/GH_PAT 相关
- `Verify Python deps`(`import requests, openpyxl`)和 requirements.txt **不动** -- openpyxl 给 migrate 脚本用(不在 workflow 跑),装着无害
- **Sanity check**(error 比例 >20% abort)和后续 Assemble/Configure Pages/Deploy/Notify 步骤保留不动
- runner 本机 cron **不变**(仍调 workflow_dispatch),仅 workflow 内容变
- `heartbeat.yml` **不受影响**:它只检查 auto-update workflow 是否按时跑,和 WPS/Supabase 数据源无关,不用改

## 10. `site_config.json`

- 删 `wps_inventory_url` + `wps_wants_url`(WPS 退役)
- 加 `"supabase_url": "https://<project>.supabase.co"` 和 `"supabase_anon_key": "<anon key>"`(都公开,可嵌前端;经 `load_site_config` 进 cards.json 的 `site` 字段下发,主站/admin 读 `site.supabase_url`/`site.supabase_anon_key`)
- 保留 `title`/`subtitle`

## 11. 迁移步骤

1. Supabase schema 增量改(`apply_migration`):
   - **inventory 加 2 列**(无 price 无 note):`alter table public.inventory add column price numeric(10,2) not null default 0, add column note text not null default '';`
   - **wants 只加 1 列**(note 已存在,加 note 会 duplicate column):`alter table public.wants add column price numeric(10,2) not null default 0;`
   - **drop 旧 unique 再建新的**(旧的是表级约束,drop constraint;新的用命名 index,将来 drop index):
     `alter table public.inventory drop constraint inventory_seller_id_set_code_number_lang_foil_key;`
     `alter table public.wants drop constraint wants_buyer_id_set_code_number_lang_foil_must_key;`
     `create unique index inventory_uniq on public.inventory (seller_id, set_code, number, lang, foil, price, note);`
     `create unique index wants_uniq on public.wants (buyer_id, set_code, number, lang, foil, must, price, note);`
   - 现有数据安全:inventory 526 行加 price=0/note='' 后,旧 unique(5 元组)比新(7 元组)更严,drop 旧建新不会因现有数据冲突;wants 0 行无冲突。无需手动核对
   - 加 `profiles_seller_name_uniq` partial index、`drop table public.publish_log`(见第 4 节)
2. 建用户(Dashboard > Authentication > Users > Add user),记 UID;确认 `email_confirmed_at`(否则 `update auth.users set email_confirmed_at=now()`)。admin 里填齐 seller_name/city/contact(partial unique 要求 seller_name 非空时唯一)
3. 配 Edge Function secret `GH_PAT`(不需 service_role)
4. **迁移 WPS 数据**:`migrate_wps_to_supabase.py`(迁 inventory + wants,需 mapping + service_role key)
5. 重写解析函数(`card_line_to_fields`/`want_line_to_fields` 按第 5 节)+ `cards_to_txt`/`wants_to_txt` + build 脚本加 price/note + **合并三处按 price+note 分组** + **`card_id`/`wid` 加 price+note**(见第 5 节清单);同步更新 `tests/test_inventory_format.py`,新增 admin JS 解析的交叉测试
6. export 脚本(inventory + wants)+ workflow 切换 + GitHub secret `SUPABASE_SERVICE_ROLE_KEY`。注意:workflow 的 `cp -r admin site/admin` 依赖步骤 7 的 `admin/` 目录,已用 `|| true` 容错(见第 9 节);建议步骤 7 先于或同步于 workflow 切换,否则切换后首次 deploy 的 site/admin 为空(主站不受影响,但 /admin/ 暂时 404)
7. admin SPA(共享层 `mtg-ui.js` + CRUD + 双 tab + 登录入口,见第 7 节)
8. deploy `publish` Edge Function
9. 主站前端改造:**重写** `index.html` 的 `<details class="guide">` 区块(删 WPS 库存/求购链接 + 更新格式说明为第 5 节新格式 + 加登录按钮);删 `app.js` 的 `guide-wps-inv`/`guide-wps-want` 逻辑,加登录态 + 登录后管理入口;`cardHtml` 展示 price/note。admin 批量/导入 UI 里也放一份新格式说明
10. 验证:**不要文本 diff** -- 新旧 txt 格式根本不同(旧 `{qty}x set number lang foil` / `set number lang foil must | note`,新 `set number lang foil qty price # note`,diff 不可能空)。改为对比解析后的结构化数据:export 后跑 `build_data --validate-only` 比对 card 元组集合(seller,set,number,lang,foil,qty)与 WPS 旧 parse 结果一致(忽略新增 price/note),或写对比脚本比解析后的 dict 列表。再 `build_data --validate-only` + `build_wants`;push 触发 workflow

**回滚策略**:验证通过前不删 WPS 文档、不删 WPS 残留脚本;若验证失败,workflow 可切回 git 历史里的 WPS 版本(commit 还在),WPS 数据仍最新。migrate 脚本可重跑(unique 约束兜底幂等)。

## 附录 A: 已建项目信息(可复用)

- Project URL: `https://rkvtizboyikrjowfogoc.supabase.co`
- schema 现状(2026-07 实测 via Supabase MCP):
  - 表:profiles(1 行,RLS ✅)、inventory(526 行,RLS ✅)、wants(0 行,RLS ✅)、publish_log(1 行,RLS ✅)
  - 触发器已建启用:`on_auth_user_created`(auth.users)、`inventory_touch_updated_at`、`wants_touch_updated_at`;`handle_new_user` 已 `revoke execute from public`(acl 仅 postgres/service_role)✅。第 4 节 DDL 幂等(`drop if exists` + create),重跑安全
  - **待改(见第 4 节)**:inventory 加 price+note 列、wants 加 price 列、drop 旧 unique 建新命名 index(含 price+note)、加 `profiles_seller_name_uniq`、`drop table publish_log`
- ClayStan user 已建:UID `cc2116b4-f7ae-4d19-867c-795c8daa3149`,email `claystan97@gmail.com`,email_confirmed
- 526 条库存已迁移(seller=claystan);wants 表已建数据为空
- `publish` Edge Function 已部署(`verify_jwt=true`,需配 `GH_PAT` secret);但**代码是旧版(含 JWT 自解 + publish_log 逻辑),需按第 8 节重新 deploy 新版**;publish_log 表待 drop
- anon key(公开,可嵌前端):`eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJrdnRpemJveWlrcmpvd2ZvZ29jIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQxNzg1ODAsImV4cCI6MjA5OTc1NDU4MH0.f6N0wAEAlsWj3afD75zcbh1_6gUI2IHtSuAwlrxdGT8`

如果宁可从零开始,重建项目即可(schema 在第 4 节,已含 price/note + wants)。
