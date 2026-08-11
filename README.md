# Redirect Tracer

A full affiliate / tracking-link redirect analyzer — an AffiliTest-style tool that
follows a tracking URL through its **entire** chain (HTTP 3xx, meta-refresh,
JavaScript/SDK redirects and JSON click responses), identifies the tracking
platform at every hop (Adjust, AppsFlyer, Branch, Singular, Kochava, …) and
extracts the final app-store destination.

Egress is routed through **ScraperAPI** so requests come from real
residential/geo IPs in the country you choose — the piece that makes protected
ad-network links resolve instead of returning `403 Forbidden`.

---

## Why the previous version returned `403 Forbidden`

The old tool ran `httpx` directly from the AWS EC2 box and "spoofed" the country
by setting `X-Forwarded-For` / `CF-Connecting-IP` headers.

**Those headers do nothing against a real anti-bot system.** The origin server
(`r.prmin.net`, Adjust, etc.) sees the actual TCP source IP — your AWS datacenter
range — recognizes it as a non-residential/cloud IP, and blocks it on hop 1.
`X-Forwarded-For` is only trusted when a server sits *behind* a proxy it already
trusts; an origin treats a client-supplied value as noise (or a red flag).

The only fix is to **change the real egress IP** to a residential/mobile IP in the
target country. That's what this rebuild does via ScraperAPI proxy mode, and it's
what AffiliTest does under the hood.

---

## How it works

For each hop the engine sends the request through ScraperAPI proxy mode:

```
http://scraperapi.follow_redirect=false.keep_headers=true.country_code=in.device_type=mobile:APIKEY@proxy-server.scraperapi.com:8001
```

- `follow_redirect=false` → ScraperAPI returns the raw `301/302` + `Location`, so
  **we** build the chain hop by hop instead of only seeing the final page.
- `keep_headers=true` → our exact device User-Agent / client-hints / Accept-Language.
- `country_code` → residential/geo egress for the selected country.
- `premium` / `ultra_premium` → residential and hardened-anti-bot IPs.
- `render=true` → only used as an escalation, to resolve a hop whose next step is
  driven by JavaScript/SDK code that plain HTTP can't see.

Between hops the engine also parses each `200` body for `meta refresh`,
`window.location`/`location.replace(...)`, `Refresh:` headers, and JSON
`clickUrl`/`redirect` fields — the redirect mechanisms tracking links actually use.

### Adaptive tier ladder (cost control)

With `PROXY_TIER=auto` (default) each hop starts on cheap datacenter proxies and
only escalates when it sees a block (`403/429/503/...`):

`datacenter (1 credit)` → `residential (10)` → `ultra-premium (30)`

Set `PROXY_TIER=premium` to force residential on every hop when you know the
network blocks datacenter IPs (most ad networks do).

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your ScraperAPI key into .env
uvicorn app.main:app --reload
# open http://localhost:8000
```

Environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `SCRAPERAPI_KEY` | _(empty)_ | Your ScraperAPI key. Empty ⇒ **direct mode** (open links only; ad networks 403). |
| `PROXY_TIER` | `auto` | `auto` \| `basic` \| `premium` \| `ultra` |
| `ENABLE_RENDER_ESCALATION` | `true` | Headless-render a stalled hop to resolve JS/SDK redirects |
| `MAX_HOPS` | `25` | Safety cap on chain length |
| `REQUEST_TIMEOUT` / `RENDER_TIMEOUT` | `40` / `80` | Per-request timeouts (seconds) |

---

## ⚠️ ScraperAPI plan requirements (important for India)

- **Country-level geotargeting (`country_code=in`, `us`, `gb`, …) requires a
  ScraperAPI Business plan or higher.** Hobby / Startup plans only support
  **US and EU** region targeting — individual country codes like **India are not
  available** on those tiers, so a "India" trace would silently egress from a
  different region.
- `premium=true` (residential) and `ultra_premium=true` credits are consumed fast
  (10 / 30 credits per request). Watch your credit balance when tracing long
  chains — a 15-hop link on forced residential is ~150 credits.

If your current plan doesn't include India geotargeting, either upgrade to
Business, or test with `US` first to confirm the pipeline end-to-end.

---

## API

| Endpoint | Description |
|---|---|
| `GET /` | The web UI |
| `GET /health` | Liveness probe |
| `GET /api/config` | Non-secret runtime config (engine, countries, tier) for the UI |
| `GET /api/trace?url=&device=&country=&tier=&screenshot=` | Trace a link. `device` = `desktop\|android\|ios`; `country` = ISO code; returns the full chain, platforms, and destination |
| `GET /api/egress-ip?country=` | Report the real proxy exit IP for a country (verifies geo egress) |

Example:

```bash
curl "http://localhost:8000/api/trace?url=https://r.prmin.net/o/out?uh=...&device=android&country=IN&tier=premium"
```

---

## Deployment (AWS ECR + EC2)

The existing GitHub Actions pipeline (`.github/workflows/deploy.yml`) builds the
image, pushes to ECR, and runs it on EC2. It now passes the key at runtime:

```
docker run -d -p 80:8000 --name fastapi-app --restart always \
  -e SCRAPERAPI_KEY='***' -e PROXY_TIER='auto' <image>
```

Add these **GitHub repository secrets** so the deploy injects them:

- `SCRAPERAPI_KEY` — your key
- `PROXY_TIER` — e.g. `auto` or `premium`

The key is never baked into the image and `.env` is git-ignored + docker-ignored.

---

## Limitations

- ScraperAPI's rendered mode returns the final page, not a per-navigation trace, so
  a chain that is *entirely* driven by in-browser JS is captured as
  "hop → (rendered) → destination" rather than each intermediate JS bounce. HTTP,
  meta-refresh, `Refresh` header and simple `location` JS hops are captured
  individually.
- Destination app-name extraction is best-effort from the store URL (package name
  for Google Play; app id + slug for the App Store).
- Direct mode (no key) exists for local testing and open links only.
