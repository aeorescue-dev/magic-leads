# Magic Leads OpenCode Package

This folder is the single handoff package for migrating the new landing page into the official Magic Leads application.

Send this folder together with the complete official Next.js repository. The files listed in `SOURCE_MANIFEST.md` are the landing reference files already present in the parent project. They must be copied or attached with this folder when uploading to OpenCode.

The separate migration prompt is `OPENCODE_MIGRATION_PROMPT.md` in the project root.

## Official app

- Next.js 14
- App Router
- Tailwind CSS
- Vercel frontend
- FastAPI backend on Railway
- SQLite database with Railway persistence

## Target

OpenCode must migrate the reference landing into `app/page.tsx` or `src/app/page.tsx`, preserving all production routes and integrations.

## Never overwrite

- Dashboard
- Authentication and sessions
- FastAPI API clients
- Web Push
- Checkout and payments
- Middleware and providers
- Environment files