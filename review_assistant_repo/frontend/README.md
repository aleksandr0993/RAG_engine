# Review Assistant — Next.js frontend

Minimal UI for the FastAPI backend: dashboard (project list), upload, project detail, static catalog viewer, admin assignments.

## Setup

```bash
cd frontend
cp .env.local.example .env.local
npm ci
npm run dev
```

- `NEXT_PUBLIC_API_URL` — backend base URL (default `http://127.0.0.1:8000`).
- Optional Supabase for `/login` magic link: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

## Routes

| Path | Purpose |
|------|---------|
| `/dashboard` | `GET /api/v1/projects` |
| `/projects/upload` | multipart upload |
| `/projects/[id]` | project detail + review markdown |
| `/catalog` | reads `../data/reviewer_comment_catalog.json` at **build/runtime** on the server |
| `/admin/assignments` | auto-assign + list APIs |
| `/login` | Supabase OTP (optional) |

When the API has `REQUIRE_AUTH_FOR_WRITES=true`, paste a JWT into the upload page or attach `Authorization: Bearer` in your own client.
