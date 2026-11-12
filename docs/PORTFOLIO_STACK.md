# Rizzler Portfolio — `stack.py`

A polished **always-on landing page** on your own laptop, with an on-demand,
**single-visitor, 30-minute GPU trial** and **server-side cost controls**.

**What it is not:** a way to start free managed Google Colab in the background.
Google Colab prioritizes interactive notebook use and does not provide a normal
external web visitor auto-start API. Colab Enterprise has different APIs and
billing. The optional Colab link on the page opens a notebook **manually**.

The automated implementation uses the **RunPod REST API v2** and a **prebuilt
Rizzler GPU container**. As of November 2026, RunPod's GPU catalog does **not**
list the NVIDIA T4. The example chooses an **RTX A4000 (16 GB)**; configure a
supported card from the provider catalog if desired. It **costs money** and
GPU availability is not guaranteed.

## Files

- `stack.py` — FastAPI gateway, signed sessions, SQLite lease ledger, RunPod
  provisioning, expiry watchdog, direct reverse proxy, privacy-limited visitor
  analytics, WebSocket relay, secret injection and offline mock mode.
- `stack_site.html`, `stack_site.js` — professional responsive showcase and
  animated article/architecture panels, countdown, status and trial frame.
- `Dockerfile.portfolio-gpu`, `portfolio-entrypoint.sh` — GPU container that
  launches the **actual Rizzler API and Work Agent** and self-exits at an
  absolute deadline even if the laptop gateway goes offline.
- `test_stack.py` — offline gateway, auth, concurrency, restart and expiration
  tests; no real GPU required.

## Step 1 — install Python on Windows

Use Python **3.11 or 3.12**. In Windows PowerShell, from the folder containing
`stack.py` and the two `stack_site` files:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "httpx>=0.27,<1" "websockets>=14,<17" "pytest>=8,<10"
python -m pytest -q test_stack.py
```

## Step 2 — public HTTPS address (stable resume link)

Tailscale Funnel can expose `http://127.0.0.1:8787` over HTTPS. In an
**Administrator PowerShell** window, after installing Tailscale and enabling
Funnel in your tailnet:

```powershell
tailscale funnel --bg 8787
tailscale funnel status
```

Use the exact `https://YOUR-LAPTOP.YOUR-TAILNET.ts.net` address printed by
Tailscale as `STACK_PUBLIC_ORIGIN`. **The origin must match exactly**; the
launcher rejects mismatched `Origin` headers. For a custom resume domain, use
a trusted HTTPS reverse proxy/tunnel that supports WebSockets, not an exposed
raw HTTP port. The gateway listens on `127.0.0.1` by default.

The privacy log normally sees the proxy IP. If your proxy appends a verified
`X-Forwarded-For` chain and strips untrusted forwarding headers, configure
`STACK_TRUSTED_PROXY_IPS=127.0.0.1,::1`. Otherwise leave it unset; do **not**
assume an IP is the actual visitor or try to identify their MAC address.

## Step 3 — build the GPU application image

Build from the **root of the Voice-AI repository**, using the included
`Dockerfile.portfolio-gpu` at `deploy/Dockerfile.portfolio-gpu` and its paired
`deploy/portfolio-entrypoint.sh` file. The GitHub repository already includes
these paths; when using the standalone ZIP instead, copy them into the
repository's `deploy` directory first.

```powershell
# Replace these example registry names with your own.
docker build -f deploy/Dockerfile.portfolio-gpu -t ghcr.io/YOUR_ACCOUNT/rizzler-demo:v10 .
docker push ghcr.io/YOUR_ACCOUNT/rizzler-demo:v10
```

For a **private** container registry, configure a RunPod registry credential
and use `STACK_RUNPOD_REGISTRY_ID`. Avoid publishing a proprietary application
image if you do not want its internal code inspectable. Image provisioning may
require substantial first-start download time. Check CUDA/TTS compatibility
in a real RunPod environment before distributing the resume link.

The GPU image has no API keys baked in. The gateway passes temporary keys when
it creates each Pod over authenticated HTTPS. Those keys are never inserted
into the browser page or served by the portfolio gateway.

## Step 4 — configure server secrets (PowerShell)

```powershell
$env:STACK_PUBLIC_ORIGIN = "https://YOUR-LAPTOP.YOUR-TAILNET.ts.net"
$env:STACK_MASTER_KEY = $(python -c "import secrets;print(secrets.token_urlsafe(48))")
$env:STACK_PROVIDER = "runpod"
$env:RUNPOD_API_KEY = "YOUR_SCOPED_RUNPOD_API_KEY"
$env:STACK_POD_IMAGE = "ghcr.io/YOUR_ACCOUNT/rizzler-demo:v10"
$env:STACK_RUNPOD_REGISTRY_ID = ""  # optional for private images
$env:GEMINI_API_KEY = "YOUR_SERVER_SIDE_GEMINI_API_KEY"
$env:STACK_GPU_ID = "NVIDIA RTX A4000"
$env:STACK_DAILY_LIMIT = "3"
$env:STACK_IP_LIMIT = "2"
$env:STACK_LOG_RETENTION_DAYS = "7"
$env:STACK_COLAB_NOTEBOOK_URL = "https://colab.research.google.com/drive/YOUR_NOTEBOOK_ID" # optional
python stack.py serve
```

**Store `STACK_MASTER_KEY` and provider keys in a persistent, restricted secret
store. Do not regenerate the master key on each reboot**: visitor cookies and
temporary derived Pod credentials must remain recoverable for a leased demo.
Do not commit `.env` files, real tokens or secrets. Keep the process alive as a
Windows service or Task Scheduler job that loads the restricted secrets at
startup; ensure Windows sleep/hibernate is disabled during public hosting.

## Visitor experience

1. A public resume link opens the public animated blog. **GET alone never
   starts a paid GPU**. This prevents previews and crawlers from spending money.
2. Visitor explicitly selects **Launch 30-minute demo**. A signed browser
   session is created, and the global slot/daily limits are enforced.
3. The gateway calls RunPod API v2 to provision the configured GPU image.
   It forwards the real Rizzler app only after remote `/ready` reports ready.
4. Voice and Work requests—including WebSocket traffic—travel via the laptop's
   HTTPS origin. The gateway injects short-lived server-side credentials.
5. At **30 minutes measured from the launch request**, the proxy refuses all
   further app traffic. The gateway attempts to **terminate** the Pod; if API
   deletion fails, it retries. Separately, the GPU image exits at the absolute
   deadline so it does not continue serving if the laptop goes offline.
6. The visitor sees: *“Hope you enjoyed the experience! You can restart the
   demo if you wanna go for another spin.”* They can restart within the
   configured daily quota once cleanup completes.

This is **a single-GPU showcase**, not an unmetered public cloud service. An
external GPU Pod can still incur charges if the laptop is offline or provider
shutdown is delayed. Enable provider spending alerts, review active Pods and
billing, and use a cloud-side lease watcher for any hard financial guarantee.

## Privacy and observability

The public page displays its privacy notice. The gateway logs only the
server-observed IP (which may be a tunnel/relay address), time, user-agent,
referrer **hostname**, and visit/launch actions. No invasive fingerprinting,
GPS tracking, webcam access, or MAC-address harvesting. Data expires after
`STACK_LOG_RETENTION_DAYS` (default 7) when new visits are logged.

```powershell
python stack.py visitors
python stack.py visitors --show-ip  # operator-only local command
```

Never publish that operator output on the landing page. If collecting visitor
contact details becomes necessary, use a separate clear, opt-in form and
compliant retention notice. Do not assume browser details identify a person.

## Offline demo without GPU

```powershell
$env:STACK_PUBLIC_ORIGIN = "http://127.0.0.1:8787"
$env:STACK_MASTER_KEY = "replace-with-at-least-32-characters-of-demo-key"
$env:STACK_PROVIDER = "mock"
python stack.py serve
```

The blog and 30-minute state machine work in mock mode. The iframe is disabled
because **no actual model is running**. The `disabled` provider serves the
blog only, with no launch button available.

## Operational limitations

- Standard consumer Colab and its T4 are not auto-launchable using this flow;
  using Google Colab Enterprise would require a separately designed, billed
  Google Cloud integration and application-serving strategy.
- You must supply and test a working GPU container image. This portfolio
  gateway cannot build your image or obtain your API keys automatically.
- Public guest access is intentionally limited to one running Pod. Jobs and
  files are ephemeral in the demo container and are not a substitute for a
  persistent multi-user production environment.
- A running laptop and a stable HTTPS tunnel are required for the resume URL
  to stay reachable. The GPU-side expiry guard protects the process when the
  gateway disappears, but provider accounting still needs independent checks.
- Browser microphones require explicit browser permission; the blog itself
  never opens a microphone.
- The site deliberately makes no unverified first-audio-latency, accuracy, GPU
  utilization or head-to-head model-superiority claims.

Reference: RunPod REST API v2 at https://docs.runpod.io/api-reference-v2/overview,
Google Colab FAQ at https://research.google.com/colaboratory/faq.html and
Tailscale Funnel at https://tailscale.com/docs/reference/tailscale-cli/funnel.
