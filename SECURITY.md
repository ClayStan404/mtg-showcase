# Security Policy

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability. Contact the
repository owner through the email listed on the
[GitHub profile](https://github.com/ClayStan404). Include the affected
component, reproduction steps, and likely impact. A response is expected
within 48 hours.

## Security Scope

The system consists of:

- a public static storefront hosted on GitHub Pages;
- an authenticated Supabase admin application;
- Postgres tables protected by row-level security;
- public, generated inventory snapshots in Supabase Storage;
- a JWT-protected Edge Function that queues GitHub Actions;
- self-hosted build and logical-backup workflows.

Database schema, constraints, triggers, and RLS policies are versioned under
`supabase/migrations/`. The browser uses the public Supabase anon key; the
`SUPABASE_SERVICE_ROLE_KEY` and `GH_PAT` are server-side secrets only.

## Public Data and Privacy

Published snapshots intentionally expose seller or buyer names, cities, contact
details, prices, notes, and card metadata. Admin users must only enter contact
information they consent to publish. Source filenames, profile UUIDs,
enrichment diagnostics, backups, and Auth metadata must not appear in public
snapshots.

## Operational Safeguards

- Import and restore commands default to dry-run and require `--apply` to write.
- Logical backups are stored in a private bucket and do not include passwords,
  a full Postgres dump, or point-in-time recovery.
- Python, npm, and GitHub Actions dependencies are monitored by Dependabot.
- Pull requests run Python lint/tests and JavaScript syntax/unit checks.

Report exposed secrets immediately so they can be revoked and rotated.
