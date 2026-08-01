# Supabase Development

`config.toml` and `migrations/` define the local and reviewable backend state.
Historical placeholder files mirror the migration versions already recorded by
production. The latest reconciliation migration declares the complete desired
state: profiles, inventory, wants, RLS policies, triggers, indexes, constraints,
and Storage buckets.

For a new local database:

```bash
supabase start
supabase db reset
supabase functions serve publish
```

Before pushing to the hosted project, run `supabase migration list` and
`supabase db diff --linked`. The reconciliation migration is designed for both
fresh and existing projects, but its new constraints still require existing
rows to be valid.

Keep `verify_jwt = true` for `publish`. Store `GH_PAT` and allowed origins as
Edge Function secrets; never place them in this directory.
