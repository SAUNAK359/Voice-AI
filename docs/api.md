# HTTP and WebSocket API contracts

The executable routes below are declared in the Kaggle V9 notebook. The notebook is the source of truth; `src/rizzler/` currently contains supporting contracts but not a standalone importable server.

## Voice API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Health of the application process, not evidence of warmed model inference |
| POST | `/api/auth` | Validates private `x-rizzler-key` |
| WS | `/ws` | Authentication handshake, PCM audio frames, partial/final transcript, incremental voice/audio events |
| POST | `/api/turn` | Recorded PCM16 turn; requires access key and session ID |
| POST | `/api/interrupt` | Cancels an in-flight HTTP turn, where supported |
| POST | `/api/reset` | Clears current session context |

## Work Agent API

| Method | Path | Function |
| --- | --- | --- |
| GET | `/api/agent/schema` | JSON handoff schema |
| POST | `/api/agent/jobs` | Submit a validated heavy-work request |
| GET | `/api/agent/jobs` | List session-scoped jobs |
| GET | `/api/agent/jobs/{job_id}` | Fetch status and artifacts |
| POST | `/api/agent/jobs/{job_id}/cancel` | Request cancellation |
| POST | `/api/agent/upload` | Upload CSV/Excel within size limits |
| GET | `/api/agent/artifacts/{artifact_id}` | Download an authorized artifact |
| GET | `/api/agent/automations` | List approval-gated schedules |
| POST | `/api/agent/automations/{automation_id}/approve` | Approve scheduled work |
| POST | `/api/agent/automations/{automation_id}/disable` | Disable recurring task |
| GET | `/api/agent/skills` | Skill catalogue |

## Authentication / authorization

The notebook currently accepts `x-rizzler-key` and `x-session-id` on the Work Agent API. The **key is a shared demo secret**, while session IDs are separate per-conversation identifiers. Do not mistake this for full user isolation. Stronger authentication with user-bound ownership is a prerequisite for third-party access.

```bash
# Example only. Supply the key securely in your client; never embed it in public code.
curl -H "x-rizzler-key: $RIZZLER_ACCESS_KEY" \
     -H "x-session-id: my-private-session" \
     https://YOUR_PRIVATE_PREVIEW.example/api/agent/jobs
```

Public demo endpoints should be protected by a gateway with HTTPS and access policies. Do not publish the sample key or actual API response data.
