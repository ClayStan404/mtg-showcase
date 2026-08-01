-- Reconcile the full desired schema on fresh and existing projects.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  seller_name text not null default '',
  city text not null default '',
  contact text not null default '',
  created_at timestamptz not null default now(),
  constraint profiles_seller_name_length check (char_length(seller_name) <= 50),
  constraint profiles_city_length check (char_length(city) <= 50),
  constraint profiles_contact_length check (char_length(contact) <= 100)
);

create table if not exists public.inventory (
  id uuid primary key default gen_random_uuid(),
  seller_id uuid not null references public.profiles(id) on delete cascade,
  set_code text not null,
  number text not null,
  lang text not null default 'en',
  foil boolean not null default false,
  quantity integer not null default 1,
  price numeric(10, 2) not null default 0,
  note text not null default '',
  updated_at timestamptz not null default now(),
  constraint inventory_quantity_check check (quantity >= 1),
  constraint inventory_price_nonneg check (price >= 0),
  constraint inventory_note_len check (char_length(note) <= 200),
  constraint inventory_lang_valid check (lang in ('en', 'zhs', 'ja', 'other'))
);

create table if not exists public.wants (
  id uuid primary key default gen_random_uuid(),
  buyer_id uuid not null references public.profiles(id) on delete cascade,
  set_code text not null,
  number text not null,
  lang text not null default 'en',
  foil boolean not null default false,
  quantity integer not null default 1,
  must boolean not null default false,
  price numeric(10, 2) not null default 0,
  note text not null default '',
  updated_at timestamptz not null default now(),
  constraint wants_quantity_check check (quantity >= 1),
  constraint wants_price_nonneg check (price >= 0),
  constraint wants_note_len check (char_length(note) <= 200),
  constraint wants_lang_valid check (lang in ('en', 'zhs', 'ja', 'other'))
);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_seller_name_length'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table public.profiles
      add constraint profiles_seller_name_length check (char_length(seller_name) <= 50);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_city_length'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table public.profiles
      add constraint profiles_city_length check (char_length(city) <= 50);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_contact_length'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table public.profiles
      add constraint profiles_contact_length check (char_length(contact) <= 100);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'inventory_lang_valid'
      and conrelid = 'public.inventory'::regclass
  ) then
    alter table public.inventory
      add constraint inventory_lang_valid check (lang in ('en', 'zhs', 'ja', 'other'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'wants_lang_valid'
      and conrelid = 'public.wants'::regclass
  ) then
    alter table public.wants
      add constraint wants_lang_valid check (lang in ('en', 'zhs', 'ja', 'other'));
  end if;
end
$$;

create unique index if not exists profiles_seller_name_uniq
  on public.profiles (lower(seller_name))
  where seller_name <> '';
create unique index if not exists inventory_uniq
  on public.inventory (seller_id, set_code, number, lang, foil, price, note);
create index if not exists inventory_seller_id_idx on public.inventory (seller_id);
create unique index if not exists wants_uniq
  on public.wants (buyer_id, set_code, number, lang, foil, must, price, note);
create index if not exists wants_buyer_id_idx on public.wants (buyer_id);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists inventory_touch_updated_at on public.inventory;
create trigger inventory_touch_updated_at
  before update on public.inventory
  for each row execute function public.touch_updated_at();

drop trigger if exists wants_touch_updated_at on public.wants;
create trigger wants_touch_updated_at
  before update on public.wants
  for each row execute function public.touch_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end;
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

alter table public.profiles enable row level security;
alter table public.inventory enable row level security;
alter table public.wants enable row level security;

drop policy if exists "profiles select own" on public.profiles;
create policy "profiles select own"
  on public.profiles for select
  using ((select auth.uid()) = id);
drop policy if exists "profiles update own" on public.profiles;
create policy "profiles update own"
  on public.profiles for update
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

drop policy if exists "inventory select own" on public.inventory;
create policy "inventory select own"
  on public.inventory for select
  using ((select auth.uid()) = seller_id);
drop policy if exists "inventory insert own" on public.inventory;
create policy "inventory insert own"
  on public.inventory for insert
  with check ((select auth.uid()) = seller_id);
drop policy if exists "inventory update own" on public.inventory;
create policy "inventory update own"
  on public.inventory for update
  using ((select auth.uid()) = seller_id)
  with check ((select auth.uid()) = seller_id);
drop policy if exists "inventory delete own" on public.inventory;
create policy "inventory delete own"
  on public.inventory for delete
  using ((select auth.uid()) = seller_id);

drop policy if exists "wants select own" on public.wants;
create policy "wants select own"
  on public.wants for select
  using ((select auth.uid()) = buyer_id);
drop policy if exists "wants insert own" on public.wants;
create policy "wants insert own"
  on public.wants for insert
  with check ((select auth.uid()) = buyer_id);
drop policy if exists "wants update own" on public.wants;
create policy "wants update own"
  on public.wants for update
  using ((select auth.uid()) = buyer_id)
  with check ((select auth.uid()) = buyer_id);
drop policy if exists "wants delete own" on public.wants;
create policy "wants delete own"
  on public.wants for delete
  using ((select auth.uid()) = buyer_id);

grant usage on schema public to authenticated, service_role;
revoke all on public.profiles, public.inventory, public.wants from anon, authenticated;
grant select, update on public.profiles to authenticated;
grant select, insert, update, delete on public.inventory, public.wants to authenticated;
grant all on public.profiles, public.inventory, public.wants to service_role;

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values
  (
    'site-data',
    'site-data',
    true,
    52428800,
    array['application/json', 'application/javascript', 'text/javascript']
  ),
  (
    'db-backups',
    'db-backups',
    false,
    104857600,
    array['application/gzip', 'application/x-gzip', 'application/octet-stream']
  )
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
