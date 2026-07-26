"""Configuration for tailnet-dns-syncer — loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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

    # ── Nginx reverse-proxy mode ───────────────────────────────
    nginx_proxy_enabled: bool = False
    """When true, A records for tagged devices point to NGINX_PROXY_PUBLIC_IP
       instead of the device's Tailscale IP, and the syncer writes nginx config
       that reverse-proxies from the public domain to the device's Tailscale IP.
       Requires DEVICE_FILTER_TAG to also be set."""

    nginx_public_ip: str = ""
    """Public IP address of the machine running nginx — used as the A-record
       value for every proxied device."""

    nginx_config_dir: str = "/etc/nginx/conf.d"
    """Directory to write per-device nginx config files into.  Each file is
       named ``<hostname>.conf`` and gets reloaded automatically."""

    nginx_backend_port: int = 80
    """Default backend port to proxy requests to on each device."""

    nginx_reload_cmd: str = "nginx -s reload"
    """Command to reload nginx after config changes."""

    # ── Validators — applied after field defaults ──────────────

    def check_nginx_proxy_requires_tag(self) -> Self:
        if self.nginx_proxy_enabled and not self.device_filter_tag:
            raise ValueError(
                "NGINX_PROXY_ENABLED requires DEVICE_FILTER_TAG to also be set "
                "so the syncer knows which devices to proxy."
            )
        if self.nginx_proxy_enabled and not self.nginx_public_ip:
            raise ValueError(
                "NGINX_PROXY_ENABLED requires NGINX_PUBLIC_IP to be set."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validators={"check_nginx_proxy_requires_tag": "after"},
    )
