"""Configuration for tailnet-dns-syncer — loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings, cli_never_set=True):
    # ── Tailscale ──────────────────────────────────────────────
    tailscale_api_key: str
    """Tailscale API access token (generated from https://login.tailscale.com/admin/settings/authkeys)."""

    tailnet_id: str
    """Tailscale tailnet ID (e.g. 'example.ts.net' or the tailnet UUID)."""

    # ── Netlify ────────────────────────────────────────────────
    netlify_api_token: str
    """Netlify personal access token (https://app.netlify.com/user/applications#personal-access-tokens)."""

    netlify_dns_zone_id: str
    """Netlify DNS zone ID to add A records to (find via ntl DNS:list or API)."""

    # ── Behaviour ──────────────────────────────────────────────
    poll_interval_seconds: int = 300
    """How often to scan the tailnet for changes (default 5 min)."""

    domain_suffix: str = ""
    """Optional domain suffix appended to device hostnames, e.g. 'vpn.example.com'
       so device 'nas' becomes 'nas.vpn.example.com'.  Empty = use bare hostname."""

    device_filter_tag: str = ""
    """If set, only sync devices that carry this tag (e.g. 'tag:monitored').
       Empty = sync every device in the tailnet."""

    dry_run: bool = False
    """When true, log what *would* be done without calling the Netlify write API."""

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
