# Rizzler V15 · React Work Studio

A real, standalone React 19 / TypeScript Work Studio client for the existing Rizzler FastAPI Work API, with TanStack Query polling, React Flow DAGs, native page previews and authenticated artifact downloads. The V14 browser voice interface is **not replaced**. This is an opt-in development client, not a production deployment.

## Run

1. Start the Rizzler FastAPI server and Work worker on localhost:8765.
2. `cd web-v15 && npm install && npm run dev`.
3. Open http://127.0.0.1:5173. Enter the same demo access key and session ID as your Rizzler Work identity. Production cookie-based sessions can leave the key blank when properly authenticated on the same origin.
4. `npm test && npm run build` to qualify the frontend separately.

## Security and deployment

- Keys exist only in React memory; they are never written to browser storage or query parameters. Refreshing clears them.
- Same-origin API requests use credentials, while demo mode attaches `x-rizzler-key` and `x-session-id` headers. Never expose the Vite dev server as a production service.
- Downloads use authenticated fetch and temporary object URLs; native page images come from server-rendered, owner-scoped endpoints.
- Vite's built-in proxy is for local development only. Production should serve the built app behind the existing authenticated HTTPS gateway, with CSP and CSRF configured for that origin.
- React Flow is a read-only representation of **persisted** model-authored DAGs, not an alternative planner.

## Current limits

Job list, plans, specialist statuses, original rendered pages, downloads, basic QA and text submission are supported. Voice UI migration, collaborative editing, interactive source citations, charts and rich document editing are future phases. No claim that this UI passes production browser or accessibility qualification until CI and Playwright tests are complete.
