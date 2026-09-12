# OpenCode migration prompt

Use the folder `magic-leads-opencode-package/` and the reference files listed inside it to update the official Magic Leads frontend.

The official production frontend uses **Next.js 14 with the App Router and Tailwind CSS**. It is deployed on Vercel and connects to a FastAPI backend on Railway with SQLite persistence. The files from the reference app were created with React/Vite. They are a design and copy reference, not a replacement for the production entry point.

## Goal

Migrate the new Magic Leads landing page into the official public route while preserving the production application.

## Required safety process

1. Inspect the official repository before editing.
2. Find the public page at `app/page.tsx` or `src/app/page.tsx`.
3. Find global styles at `app/globals.css` or `src/app/globals.css`.
4. Find the dashboard route, auth routes, middleware, providers, API helpers and checkout components.
5. Create a backup or git checkpoint before changing anything.
6. Report the exact files changed at the end.

## Migration rules

1. Convert the reference `src/App.tsx` into the existing Next.js public page.
2. Convert the reference `src/index.css` into the official global or scoped landing styles.
3. Convert the reference `src/i18n.ts` into the official i18n approach or preserve its local PT, EN and ES state in the landing.
4. Keep the flag selector with Brazil, United States and Spain. The active flag must have the green outline and dark active surface.
5. Keep the light-first page, white grid background, mint actions, purple brand accents, dark dashboard preview and curved section folds.
6. Connect every CTA to the official login, signup or checkout route. Do not leave the reference form as the production checkout if a real flow already exists.
7. Use production API data where a safe aggregate endpoint exists for bank count, owner count, active markets and last refresh time.
8. If an aggregate endpoint does not exist, mark those UI fields as a sample. Never invent a fixed scan count.
9. Keep the wording that New York, Boston, Dallas and Chicago are current markets and that the operation is expanding to new cities.
10. Keep pricing out of individual opportunity cards. Job value is negotiated individually.
11. Do not expose private owner information in a public landing sample. Use masked or clearly illustrative values until the real authenticated flow is active.

## Do not change

- Do not delete or rewrite `/dashboard`.
- Do not remove authentication, sessions, FastAPI calls, Web Push, checkout, middleware or providers.
- Do not replace `package.json`, `next.config` or environment files without necessity.
- Do not add 311 or internal source names to the marketing copy.
- Do not add fixed daily volume promises.
- Do not use the Vite `main.tsx` as the Next.js entry point.

## Verification before completion

1. Run the official Next.js production build.
2. Open `/` and test Portuguese, English and Spanish.
3. Open `/dashboard` and confirm it still works.
4. Test login, signup, checkout and one backend request.
5. Check for TypeScript, hydration, route and image errors.
6. Return a concise list of changed files and preserved integrations.