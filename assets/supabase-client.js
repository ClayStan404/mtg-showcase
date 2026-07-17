/* supabase-client.js -- 主站 + admin 共享的 Supabase 客户端 + auth 辅助。
 *
 * 配置来源：window.__MTG_DATA__.site（build 时从 site_config.json 下发，见 build_common.load_site_config）。
 *   - supabase_url / supabase_anon_key 都是公开值（anon key 受 RLS 约束，可嵌前端）。
 *
 * 主站：不预加载 vendor（212KB），点「登录」时 MTGSupabase.getClient() 首次调用动态注入
 *   /assets/vendor/supabase-js.min.js，纯看牌买家首屏零成本。
 * admin：admin.html 直接 <script> include vendor，getClient() 命中 window.supabase 立即返回。
 *
 * 暴露 window.MTGSupabase = { site, getClient, getSession, requireUser, signOut }。
 */
(function () {
  "use strict";

  const SITE =
    (window.__MTG_DATA__ && window.__MTG_DATA__.site) ||
    (window.__MTG_WANTS__ && window.__MTG_WANTS__.site) ||
    {};

  let _client = null;
  let _vendorPromise = null;

  function loadVendor() {
    if (window.supabase && typeof window.supabase.createClient === "function") {
      return Promise.resolve();
    }
    if (_vendorPromise) return _vendorPromise;
    _vendorPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/assets/vendor/supabase-js.min.js";
      s.onload = () => resolve();
      s.onerror = () => {
        _vendorPromise = null;
        reject(new Error("supabase-js 加载失败"));
      };
      document.head.appendChild(s);
    });
    return _vendorPromise;
  }

  async function getClient() {
    if (_client) return _client;
    if (!SITE.supabase_url || !SITE.supabase_anon_key) {
      throw new Error("site 缺 supabase_url / supabase_anon_key（site_config.json 未配？）");
    }
    await loadVendor();
    _client = window.supabase.createClient(SITE.supabase_url, SITE.supabase_anon_key, {
      auth: { persistSession: true, autoRefreshToken: true },
    });
    return _client;
  }

  async function getSession() {
    const c = await getClient();
    const { data } = await c.auth.getSession();
    return data.session || null;
  }

  /** admin 入口用：无 session 跳回主站登录。返回 user 或 null（已跳转）。 */
  async function requireUser() {
    const session = await getSession();
    if (session && session.user) return session.user;
    window.location.href = "/";
    return null;
  }

  async function signOut() {
    const c = await getClient();
    await c.auth.signOut();
  }

  /** 轻量探测本地 session（不加载 vendor）。
   * supabase-js v2 把 session 存在 localStorage 的 sb-<project-ref>-auth-token。
   * 仅用于主站首屏决定显「登录」还是「管理」按钮；权威校验由 admin 的 requireUser() 做。 */
  function hasLocalSession() {
    try {
      const m = (SITE.supabase_url || "").match(/^https:\/\/([^.]+)\.supabase\.co/);
      if (!m) return false;
      return localStorage.getItem(`sb-${m[1]}-auth-token`) != null;
    } catch {
      return false;
    }
  }

  window.MTGSupabase = { site: SITE, getClient, getSession, requireUser, signOut, hasLocalSession };
})();
