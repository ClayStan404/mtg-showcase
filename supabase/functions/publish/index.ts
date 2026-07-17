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
    "Content-Type": "application/json",
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
  // verify_jwt=true: gateway already validated JWT; only require Bearer present.
  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) {
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

  let mode = "data";
  try {
    if (req.headers.get("Content-Type")?.includes("application/json")) {
      const body = (await req.json()) as Body;
      if (body?.mode === "full" || body?.mode === "data") mode = body.mode;
    }
  } catch {
    // empty body is fine → default data
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
        inputs: { mode },
      }),
    },
  );
  if (!r.ok) {
    return new Response(JSON.stringify({ error: `github ${r.status}` }), {
      status: 502,
      headers,
    });
  }
  return new Response(JSON.stringify({ ok: true, mode }), {
    headers,
  });
});
