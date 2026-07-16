# MTG Showcase 迁移 Supabase 方案(全面抛弃 WPS)

> 卖家在网页(admin)管理**库存**、买家管理**求购**,完全替换 WPS;买家继续看静态站。本文档记录完整方案、关键决策和我踩过的坑,供接手实现参考。

## 1. 现状(必读)

两条对称的 pipeline,都从 WPS 读:

**库存(inventory,卖家出售):**
`WPS xlsx -> fetch_wps_share.py -> parse_wps_excel.py -> inventory/*.txt -> build_data.py -> data/cards.json`

**求购(wants,买家求购):**
`WPS xlsx -> fetch_wps_share.py -> parse_wps_wants_excel.py -> wants/*.txt -> build_wants.py -> data/wants.json`

- **关键接口**:`inventory/*.txt` 和 `wants/*.txt` 是 parse 层和 build 层之间的文本接口。`build_data.py`/`build_wants.py` 及以下完全不动,只换数据源(WPS -> Supabase)。
- 字段约定集中在 `scripts/inventory_format.py`:
  - lang:`e`/`z`/`j`/`o`(内部 `en`/`zhs`/`ja`/`other`)
  - foil:`0`/`1`;qty:空=1,`Nx` 前缀
  - **wants 多 `must`**:`0`=可替其他版,`1`=必须此印刷;**wants 多 `note`**:`| 备注`
- inventory txt 行:`[Nx] set number lang foil`
- wants txt 行:`[Nx] set number lang foil must | note`
- meta 头:inventory 用 `# seller/city/contact`;wants 用 `# buyer/city/contact`
- 主站 `assets/app.js` 的 `loadData()` 读 `window.__MTG_DATA__`(inlined cards-data.js)或 `fetch data/cards.json`;wants 同理(`__MTG_WANTS__` / `wants.json`)
- 主站卡片渲染:`app.js` 的 `cardHtml(c)`,图片用 `c.image.normal`(Scryfall CDN)
- 买家不登录;卖家/买家目前改 WPS

## 2. 架构:读写分离(inventory + wants 都迁)

```
卖家/买家(写,慢可忍)  admin SPA ──> Supabase(Tokyo)
                                   │   ├─ profiles(卖家/买家共用)
                                   │   ├─ inventory(seller_id)
                                   │   └─ wants(buyer_id)
                       hourly cron / "立即发布"按钮
                                   ▼
                   export 脚本: Supabase -> inventory/*.txt + wants/*.txt
                                   ▼
                   build_data.py / build_wants.py(不动) -> cards.json / wants.json
                                   ▼
买家(读,快)        静态站读 cards.json + wants.json(GitHub Pages,零改动)
```

核心:**`inventory/*.txt` 和 `wants/*.txt` 接口复用,build 脚本完全不动**。WPS 彻底退役。

## 3. Supabase 项目

- 区域:**Tokyo**(`ap-northeast-1`)
- Auth:邮箱+密码,**邀请制**(Dashboard 关闭 "Allow new users to sign up")
- 已建项目(可复用):URL `https://rkvtizboyikrjowfogoc.supabase.co`,anon key 在 Dashboard > Project Settings > API
- `service_role` key:**保密**,只进 GitHub Actions secret + 本地 env,**绝不进前端**
- 一个用户可同时是卖家和买家(profiles 共用:有 inventory 行就是卖家,有 wants 行就是买家)
- Supabase MCP 工具:`apply_migration`、`execute_sql`、`deploy_edge_function`、`get_advisors`、`get_publishable_keys`

## 4. 数据库 schema + RLS

```sql
-- profiles: 扩展 auth.users,卖家/买家共用(对应 # seller/city/contact 或 # buyer/...)
create table public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  seller_name text not null default '',   -- 卖家昵称(也作买家昵称)
  city        text not null default '',
  contact     text not null default '',
  created_at  timestamptz not null default now()
);

-- inventory: 卖家库存。set_code(NOT "set",SQL 保留词);lang 存内部码
create table public.inventory (
  id         uuid primary key default gen_random_uuid(),
  seller_id  uuid not null references public.profiles(id) on delete cascade,
  set_code   text not null,
  number     text not null,
  lang       text not null default 'en',
  foil       boolean not null default false,
  quantity   integer not null default 1 check (quantity >= 1),
  updated_at timestamptz not null default now(),
  unique (seller_id, set_code, number, lang, foil)
);
create index inventory_seller_id_idx on public.inventory(seller_id);

-- wants: 买家求购。比 inventory 多 must + note
create table public.wants (
  id         uuid primary key default gen_random_uuid(),
  buyer_id   uuid not null references public.profiles(id) on delete cascade,
  set_code   text not null,
  number     text not null,
  lang       text not null default 'en',
  foil       boolean not null default false,
  quantity   integer not null default 1 check (quantity >= 1),
  must       boolean not null default false,  -- false=可替其他版,true=必须此印刷
  note       text not null default '',         -- 备注(对应 txt 的 | note)
  updated_at timestamptz not null default now(),
  unique (buyer_id, set_code, number, lang, foil, must)
);
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

-- publish_log: "立即发布"防抖(单行表)
create table public.publish_log (
  id           integer primary key default 1 check (id = 1),
  last_trigger timestamptz,
  triggered_by uuid references public.profiles(id)
);
insert into public.publish_log (id) values (1) on conflict (id) do nothing;

-- RLS
alter table public.profiles   enable row level security;
alter table public.inventory  enable row level security;
alter table public.wants      enable row level security;
alter table public.publish_log enable row level security;

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

create policy "publish_log read authed" on public.publish_log for select using (auth.uid() is not null);
```

> 已建项目的 schema 目前**只有 inventory,没有 wants**。接手时需 `apply_migration` 把 wants 表 + 触发器 + RLS 补上。

## 5. 脚本

### `scripts/export_inventory_to_txt.py`(替代 fetch_wps + parse_wps_excel)
- `service_role` key 调 Supabase REST bypass RLS,读 profiles + inventory
- 按 seller 写 `inventory/{seller_id}.txt`,格式同 `parse_wps_excel.cards_to_txt`(复用 `inventory_format.LANG_TOKEN` en->e)
- 先 `rm -f inventory/*.txt`
- 跳过 profile 不全的卖家

### `scripts/export_wants_to_txt.py`(替代 fetch_wps + parse_wps_wants_excel,对称)
- 同上,读 profiles + wants
- 按 buyer 写 `wants/{buyer_id}.txt`,格式同 `parse_wps_wants_excel.wants_to_txt`:
  ```
  # buyer: 昵称
  # city: 城市
  # contact: 联系
  #
  # 由 export_wants_to_txt.py 生成 - 语言 e/z/j/o  闪 0/1  必须 0/1  数量默认1

  [Nx] set number lang foil must | note
  ```
  - `must`:`1`/`0`;`note`:` | 备注`(空则省略;换行清洗为空格,不断行)
- 先 `rm -f wants/*.txt`
- `build_wants.py` 下游零改动(它用 `want_line_to_fields` 解析)

### `scripts/migrate_wps_to_supabase.py`(一次性,迁 inventory + wants)
- 读 `wps_inventory.xlsx` + `wps_wants.xlsx`(复用 `parse_wps_excel.parse_workbook` + `parse_wps_wants_excel.parse_workbook`)
- 需 `migration_mapping.json`:`{"昵称": "user-uid", ...}`(inventory 用 seller 昵称,wants 用 buyer 昵称;同一人同 UID)
- upsert profiles + delete 旧 + insert inventory + wants
- env:`SUPABASE_SERVICE_ROLE_KEY`

## 6. admin 前端(关键设计 + 坑)

纯 JS(无构建、无框架、无 CDN),复用主站样式。功能:登录 + profile + **库存 CRUD + 求购 CRUD** + 添加(单卡 + 批量)+ 筛选 + 搜索。

### 6.1 卡片渲染:共享 `assets/card-render.js`(重要)
- 把主站 `cardHtml` + 纯函数(`displayName`/`cardImageSrc`/`buildHay`/`cmcBucket`/`typeLabelShort`/`escapeHtml` + `TYPE_LABELS` 等常量)抽到 `assets/card-render.js`
- 主站 `app.js` 和 `admin.js` 都引用(在各自 script 前)-- **卡片渲染只维护一份**
- `cardHtml(c, ctx)` 可配置:`ctx.view='sell'|'want'`、`ctx.mode='cart'(主站)/'crud'(admin)`
- admin 的 wants 卡片:`view='want'`,显示 `must` 角标(必须/可替,复用主站 `flag-exact`/`flag-any`)+ note
- 主站 `app.js` 删掉这些函数,`renderGrid`/`loadMore` 调用改 `cardHtml(c, { view: state.view, inCart, mode: "cart" })`
- `card` 对象字段对齐 `cards.json`/`wants.json`:`set, number, lang, lang_label, foil, quantity, name_zh, name_en, image, type_line, mana_cost, cmc, types[], seller/buyer, city, must, note`

### 6.2 图片:优先读 cards.json/wants.json,不实时查 Scryfall(最大的坑)
- **admin 启动时 `fetch('../data/cards.json')` + `fetch('../data/wants.json')`,建索引 `set/number/lang -> card`**
- `toCard(row)` 优先用已富化数据(图片 URL + 名字 + 类型),**不调 Scryfall API**
- 只有 json 没有的新卡才 fallback 查 Scryfall
- **原因**:admin 实时查几百张 Scryfall API -> 触发 429 限流 -> 大量图片不显示。json 已被 `build_data`/`build_wants` 富化好,直接用
- json 的 `image.normal` 和 Scryfall API 的 `image_uris.normal` 同一 CDN URL,浏览器 HTTP 缓存共用(主站和 admin)

### 6.3 Scryfall fallback 的坑
- `type_line` 用 **em dash**(`-`,U+2014)分隔副类型,如 `"Creature - Dragon"`。`extractTypes` 要 `split(/[--]/)`,不是 `split("-")`
- **429/529 不缓存 null**(否则永久不重试),改为等待重试;只有 404 才缓存 null
- 并发限流(8 并发 + 重试 + 递增延迟)
- Scryfall 查询缓存到 `localStorage`,下次秒开

### 6.4 CSP(admin/index.html 独立 CSP)
```
default-src 'self';
img-src 'self' data: https://cards.scryfall.io;
script-src 'self';                    -- 无内联,无 CDN
style-src 'self' 'unsafe-inline';
connect-src 'self' https://<project>.supabase.co https://api.scryfall.com;
frame-ancestors 'none'
```
- admin 引用主站样式:`<link rel="stylesheet" href="../assets/style.css">`
- admin 引用共享:`<script src="../assets/card-render.js"></script>` 在 `admin.js` 前

### 6.5 其他
- Auth 用纯 fetch(GoTrue password grant),token 存 localStorage,401 自动 refresh。不 vendor supabase-js
- **库存 vs 求购切换**:admin 顶部 tab 切"库存/求购",共用卡片网格但字段不同(wants 多 must/note;CRUD 调不同表)
- 批量添加:textarea 粘贴每行一张(inventory:`set number lang foil qty`;wants:`set number lang foil must qty | note`)
- 单卡添加:输入 set/number/lang 后实时 Scryfall 预览

## 7. Edge Function: `publish`(立即发布)

```ts
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization") ?? "";
  let userId = null;
  try { userId = JSON.parse(atob(auth.replace("Bearer ","").split(".")[1])).sub; } catch {}
  if (!userId) return new Response(JSON.stringify({error:"unauthorized"}),{status:401});
  const ghPat = Deno.env.get("GH_PAT");
  if (!ghPat) return new Response(JSON.stringify({error:"GH_PAT not configured"}),{status:500});
  const repo = Deno.env.get("GH_REPO") ?? "ClayStan404/mtg-showcase";
  const workflow = Deno.env.get("GH_WORKFLOW") ?? "auto-update.yml";
  const now = new Date().toISOString();
  // 记 publish_log(service_role bypass RLS)
  // 调 GitHub workflow_dispatch
  const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,{
    method:"POST",
    headers:{Authorization:`Bearer ${ghPat}`,Accept:"application/vnd.github+json","User-Agent":"mtg-showcase-publish"},
    body: JSON.stringify({ref:"master"}),
  });
  if (!r.ok) return new Response(JSON.stringify({error:`github ${r.status}`}),{status:502});
  return new Response(JSON.stringify({ok:true,triggered_at:now}));
});
```
- `verify_jwt: true`;env:`GH_PAT`(fine-grained PAT,`actions:write`)、`GH_REPO`、`GH_WORKFLOW`

## 8. workflow 改动(`.github/workflows/auto-update.yml`)

**inventory + wants 两侧都换:**
- 删 `fetch_wps_share`(inventory + wants)+ `parse_wps_excel` + `parse_wps_wants_excel`
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
- assemble:加 `cp -r admin site/admin`
- repo secrets:`SUPABASE_SERVICE_ROLE_KEY`
- `fetch_wps_share.py` 彻底不再用(可留作备用,但 workflow 不调)

## 9. `site_config.json`

- 删 `wps_inventory_url` + `wps_wants_url`(WPS 退役)
- 加 `"supabase_url": "https://<project>.supabase.co"`
- 保留 `title`/`subtitle`

## 10. 迁移步骤

1. Supabase 项目(Tokyo)+ 跑 schema.sql(**含 wants 表**)+ Auth(禁公开注册)
2. 建用户(Dashboard > Authentication > Users > Add user),记 UID;确认 `email_confirmed_at`(否则 `update auth.users set email_confirmed_at=now()`)
3. 配 Edge Function secret `GH_PAT`
4. **迁移 WPS 数据**:`migrate_wps_to_supabase.py`(迁 inventory + wants,需 mapping + service_role key)
5. export 脚本(inventory + wants)+ workflow 切换 + GitHub secret `SUPABASE_SERVICE_ROLE_KEY`
6. admin SPA(库存 + 求购管理,读 cards.json/wants.json 优先)
7. deploy `publish` Edge Function
8. 验证:`export --dry-run` + `build_data --validate-only` + `build_wants` 确认 json 不变;push 触发 workflow

## 11. 经验教训(必读,避免重蹈)

1. **admin 不要实时查 Scryfall API**:几百张并发查 -> 429 限流 -> 图片不显示。**优先读 `data/cards.json` + `data/wants.json`**(已富化),只有新卡 fallback Scryfall。
2. **Scryfall `type_line` 用 em dash**(`-`,U+2014):`extractTypes` 要 `split(/[--]/)`。
3. **429/529 不缓存 null**:否则该卡永久不重试。404 才缓存 null。
4. **共享 `card-render.js`**:主站 + admin 一份 `cardHtml`,避免两份维护。`cardHtml(c, ctx)` 可配置 view + mode。
5. **`handle_new_user` 要 `revoke execute from public`**:否则暴露为可公开调用 RPC(安全 advisor 会报)。
6. **`set` 是 SQL 保留词**:列名用 `set_code`,export 时映射回 `set`。
7. **CSP 严格**:`script-src 'self'`(无 CDN/内联),`connect-src` 含 supabase + api.scryfall.com,`img-src` 含 cards.scryfall.io。supabase-js 用纯 fetch 替代(无依赖)。
8. **`service_role` 绝不进前端**:anon key + RLS 兜底。
9. **`inventory/*.txt` 和 `wants/*.txt` 是接口**:复用,`build_data.py`/`build_wants.py` 不动。
10. **wants 和 inventory 对称**:但 wants 多 `must`(0/1)+ `note`(`| 备注`),用 `buyer_id`(不是 seller_id)。
11. **profiles 卖家/买家共用**:一个用户可同时有 inventory 和 wants。
12. **主站 `loadData` 读 cards.json/wants.json**(别动),admin 也要读(优先)。
13. **图片 CDN `cards.scryfall.io` 国内通常可达**,偶发 reset(重试);API `api.scryfall.com` 也可达。
14. **admin 改文件后 bump `?v=`**:否则浏览器缓存旧版。
15. **wants 的 note 清洗换行**:WPS 单元格 Alt+Enter 是 `\n`,写 txt 时替换为空格,避免断行破坏格式(见 `parse_wps_wants_excel.wants_to_txt`)。

## 12. 文件清单

**新增:**
- `supabase/schema.sql`(含 wants 表)、`supabase/functions/publish/index.ts`
- `assets/card-render.js`(共享 cardHtml + 纯函数)
- `admin/index.html`、`admin/admin.js`、`admin/admin.css`(库存 + 求购管理)
- `scripts/export_inventory_to_txt.py`、`scripts/export_wants_to_txt.py`、`scripts/migrate_wps_to_supabase.py`
- `tests/test_export_inventory.py`(可加 `test_export_wants.py`)

**修改:**
- `.github/workflows/auto-update.yml`(inventory + wants 都换 export + assemble 加 admin)
- `site_config.json`(删 wps_*_url,加 supabase_url)
- `assets/app.js`(删 cardHtml 等,用 card-render.js,改 2 处调用传 ctx)
- `index.html`(加 `card-render.js` script)
- `.gitignore`(加 `migration_mapping.json`)

**不动:**
- `scripts/build_data.py`、`build_wants.py`、`build_common.py`、`inventory_format.py`、`parse_excel_order_txt.py`
- `assets/app.js` 的 `loadData`(读 cards.json/wants.json)
- 主站展示前端、`fetch_wps_share.py`(留作备用,workflow 不调)

## 13. Supabase 已建项目信息(可复用)

- Project URL: `https://rkvtizboyikrjowfogoc.supabase.co`
- schema 已应用:**profiles + inventory + wants + publish_log** + RLS + 触发器(全部就绪)
- ClayStan user 已建:UID `cc2116b4-f7ae-4d19-867c-795c8daa3149`,email `claystan97@gmail.com`,email_confirmed
- 526 条库存已迁移(seller=claystan,734 张)
- wants 表已建,数据为空(本来没有求购内容,后续在 admin 录入)
- `publish` Edge Function 已部署(`verify_jwt=true`,需配 `GH_PAT` secret)
- anon key(公开,可嵌前端):`eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJrdnRpemJveWlrcmpvd2ZvZ29jIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQxNzg1ODAsImV4cCI6MjA5OTc1NDU4MH0.f6N0wAEAlsWj3afD75zcbh1_6gUI2IHtSuAwlrxdGT8`

如果宁可从零开始,重建项目即可(schema 在第 4 节,含 wants)。
