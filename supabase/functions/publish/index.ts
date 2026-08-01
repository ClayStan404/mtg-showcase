import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// Publish: logged-in users trigger GitHub Actions workflow_dispatch.
// Scheme C: default mode=data (export+build+upload Storage snapshots, skip Pages).
// Full Pages deploy still happens on push to master.
// CORS: Authorization POST triggers preflight; only reflect allowed origins.
// ALLOWED_ORIGIN: comma-separated origins (prod + local dev).

const ALLOWED = (Deno.env.get("ALLOWED_ORIGIN") ?? "https://claystan.cc")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const COOLDOWN_MS = 60_000;
const lastDispatchByUser = new Map<string, number>();

/**
 * Build CORS headers. Unauthorized browser Origin → null (caller returns 403).
 * Missing Origin (curl / server-to-server) → headers without ACAO.
 * Uses Bearer tokens, not cookies — no Access-Control-Allow-Credentials.
 */
function resolveCors(
  req: Request,
): { ok: true; headers: Record<string, string> } | { ok: false } {
  const origin = req.headers.get("Origin");
  const headers: Record<string, string> = {
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "Vary": "Origin",
  };
  if (!origin) {
    return { ok: true, headers };
  }
  if (!ALLOWED.includes(origin)) {
    return { ok: false };
  }
  headers["Access-Control-Allow-Origin"] = origin;
  return { ok: true, headers };
}

type Body = { mode?: string };

function jwtSubject(auth: string): string | null {
  try {
    const token = auth.slice("Bearer ".length);
    const part = token.split(".")[1];
    if (!part) return null;
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as { sub?: unknown };
    return typeof payload.sub === "string" && payload.sub ? payload.sub : null;
  } catch {
    return null;
  }
}

Deno.serve(async (req: Request) => {
  const cors = resolveCors(req);
  if (!cors.ok) {
    return new Response(JSON.stringify({ error: "origin not allowed" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }
  const { headers } = cors;

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { ...headers, Allow: "POST, OPTIONS" },
    });
  }
  // verify_jwt=true: gateway already validated JWT; only require Bearer present.
  const auth = req.headers.get("Authorization") ?? "";
  const subject = auth.startsWith("Bearer ") ? jwtSubject(auth) : null;
  if (!subject) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers,
    });
  }
  const ghPat = Deno.env.get("GH_PAT");
  if (!ghPat) {
    return new Response(JSON.stringify({ error: "GH_PAT not configured" }), {
      status: 500,
      headers,
    });
  }

  if (req.headers.get("Content-Type")?.includes("application/json")) {
    try {
      const body = (await req.json()) as Body;
      if (body?.mode && body.mode !== "data") {
        return new Response(JSON.stringify({ error: "only data mode is allowed" }), {
          status: 400,
          headers,
        });
      }
    } catch {
      return new Response(JSON.stringify({ error: "invalid JSON body" }), {
        status: 400,
        headers,
      });
    }
  }

  const now = Date.now();
  const lastDispatch = lastDispatchByUser.get(subject) ?? 0;
  if (now - lastDispatch < COOLDOWN_MS) {
    const retryAfter = Math.ceil((COOLDOWN_MS - (now - lastDispatch)) / 1000);
    return new Response(JSON.stringify({ error: "publish cooldown", retry_after: retryAfter }), {
      status: 429,
      headers: { ...headers, "Retry-After": String(retryAfter) },
    });
  }
  // Best-effort per-isolate protection; GitHub workflow concurrency remains the
  // cross-isolate guard. Reserve the slot before the first await to avoid races.
  lastDispatchByUser.set(subject, now);
  for (const [user, timestamp] of lastDispatchByUser) {
    if (now - timestamp > COOLDOWN_MS * 10) lastDispatchByUser.delete(user);
  }

  const repo = Deno.env.get("GH_REPO") ?? "ClayStan404/mtg-showcase";
  const workflow = Deno.env.get("GH_WORKFLOW") ?? "auto-update.yml";
  const r = await fetch(
    `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ghPat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "mtg-showcase-publish",
      },
      body: JSON.stringify({
        ref: "master",
        inputs: { mode: "data" },
      }),
    },
  );
  if (!r.ok) {
    lastDispatchByUser.delete(subject);
    return new Response(JSON.stringify({ error: `github ${r.status}` }), {
      status: 502,
      headers,
    });
  }
  return new Response(JSON.stringify({ ok: true, mode: "data" }), {
    headers,
  });
});
