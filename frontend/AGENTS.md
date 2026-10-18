<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Frontend (Next.js)

Next.js App Router, TypeScript, Tailwind, npm. Ask before adding any dependency.

## Layout

- `src/app/` - routes and layouts.
- `src/components/` - UI components (create as needed).
- `src/lib/` - API client and shared types (create as needed).

## Commands

- Dev: `npm run dev` (port 3000)
- Lint: `npm run lint`
- Build: `npm run build`

## Rules

- Backend base URL comes from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`); template in `.env.example`.
- Start with an empty screen. Show processing, success and failure states.
- Show per-field value, state, and evidence (file, locator, excerpt); label human overrides and keep the original value visible.
- Show each rule's status, reason, and values used; the draft email is editable and never sent.
- Switching packets must clear all prior applicant data from state.
- Do not compute rule results in the UI; render what the backend returns.
