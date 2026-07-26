# tailnet-dns-syncer

Poll your Tailscale tailnet and automatically sync A records to Netlify DNS.

Every device in your tailnet gets a DNS A record pointing to its Tailscale IPv4 — so you can reach `nas.yourdomain.com` instead of remembering `100.x.x.x`.

## How it works

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Tailscale   │────▶│  tailnet-dns-    │────▶│  Netlify DNS │
│  API         │     │  syncer          │     │  Zone        │
│  /devices    │     │  (Docker)        │     │  /dns_records│
└──────────────┘     └──────────────────┘     └──────────────┘
     poll every              │                      A records
     5 min                   │                 nas → 100.99.1.2
                             │                 nas → 100.99.1.2
                             │                 web → 100.99.1.5
                             ▼
                      Stale records
                      are removed
```

## Quick start

### 1. Get your API keys

**Tailscale:**
1. Go to https://login.tailscale.com/admin/settings/authkeys
2. Generate an API access token
3. Note your tailnet name (e.g. `mynetwork.ts.net`)

**Netlify:**
1. Go to https://app.netlify.com/user/applications#personal-access-tokens
2. Generate a PAT
3. Find your DNS zone ID:
   ```
   curl -H "Authorization: Bearer $NETLIFY_TOKEN" \
     https://api.netlify.com/api/v1/dns_zones
   ```
4. Copy the `id` of the zone you want to manage

### 2. Configure

```bash
cp .env.example .env
# Fill in your keys, tailnet ID, and DNS zone ID
```

| Variable | Required | Description |
|----------|----------|-------------|
| `TAILSCALE_API_KEY` | ✅ | Tailscale API access token |
| `TAILNET_ID` | ✅ | Tailscale tailnet name (e.g. `example.ts.net`) |
| `NETLIFY_API_TOKEN` | ✅ | Netlify personal access token |
| `NETLIFY_DNS_ZONE_ID` | ✅ | Netlify DNS zone ID |
| `POLL_INTERVAL_SECONDS` | ❌ | How often to scan (default: 300) |
| `DOMAIN_SUFFIX` | ❌ | Append to hostnames (e.g. `vpn.example.com` → `nas.vpn.example.com`) |
| `DEVICE_FILTER_TAG` | ❌ | Only sync devices with this tag (e.g. `tag:synced`) |
| `DRY_RUN` | ❌ | `true` to log changes without making them |

### 3. Run

```bash
docker compose up -d
```

## Deploy on Coolify

1. Create a new **Docker Compose** resource
2. Point it to `https://github.com/monika-runtime/tailnet-dns-syncer`
3. Set the environment variables in the Coolify UI
4. Deploy

That's it — no exposed ports, no volumes, just a lightweight sync loop.

## Behaviour

- **Create**: new tailnet device → new A record
- **Update**: device changes IP → record is updated
- **Remove**: device leaves tailnet → stale record is cleaned up
- **Filter**: set `DEVICE_FILTER_TAG` to manage only tagged devices
- **Dry-run**: set `DRY_RUN=true` to preview changes safely
