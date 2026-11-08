# Security policy

Rizzler is a research/demo platform, **not a hardened public multi-tenant SaaS**. Do not use the Kaggle Quick Tunnel as a permanent public deployment or upload sensitive company/customer data during public showcases.

## Secret handling

- Configure `GEMINI_API_KEY` and `RIZZLER_ACCESS_KEY` in Kaggle **Secrets**; the runtime reads them server-side. No secrets are committed to GitHub.
- CI never receives an API key. Do not print credential values or include them in logs, stack traces, screenshots, notebook outputs, demo scripts, or front-end HTML.
- A single shared access key is **not** full user authentication. For public deployment: use OIDC, user-bound authorization, per-user job ownership, revocation, rate limiting, and storage encryption.
- `RIZZLER_ACCESS_KEY` is different from your Gemini API key. If it leaks, rotate it immediately.

## Known deployment risks

Kaggle sessions are ephemeral; SQLite files and artifacts need external persistence for reliability. The browser sends a private UI key through protected HTTPS requests; it is still visible to someone who controls that browser session. The notebook's WebSocket origin check and single-user session guard do not replace a modern identity provider. Audio transcripts, uploaded datasets and output files may contain sensitive data; the current app should use strictly private demo data.

## Security backlog (release blockers)

1. Add user authentication, per-user scoped API tokens, CSRF protection, security headers without `unsafe-inline` scripts, and comprehensive rate limiting.
2. Isolate work execution and uploads; add file content and archive scanning, quotas, retention policies, and data deletion controls.
3. Move the job store to durable PostgreSQL, backed by private object storage.
4. Pin and independently audit all cloud model dependencies; maintain an SBOM and vulnerability response process.
5. Run a real adversarial assessment before exposing the service to untrusted traffic.

## Reporting

Open a GitHub Security Advisory if supported, or contact the repository owner privately. Do **not** publish credentials in an issue.
