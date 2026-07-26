#!/usr/bin/env python3
"""tailnet-dns-syncer — poll the Tailscale tailnet and sync A records to Netlify DNS.

Every *poll_interval* seconds:
  1. Fetch all devices from the Tailscale API.
  2. Fetch all existing A records from the Netlify DNS zone.
  3. For each device (optionally filtered by tag):
       - Derive a DNS hostname from the device name.
       - If no A record exists → create one.
       - If an A record exists but points to a different IP → update it.
  4. Remove A records for devices that are no longer in the tailnet
     (only those that were *originally* created by this tool, identified by a
      convention — the hostname must match a known device name pattern).

When NGINX_PROXY_ENABLED is set the A records point to the proxy's public IP
instead of the device's Tailscale IP, and per-device nginx config fragments
are written + reloaded to forward traffic to the real backend.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from config import Settings
from netlify_dns import NetlifyDnsClient
from tailscale import TailscaleClient

logger = logging.getLogger("syncer")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOSTNAME_SAFE = re.compile(r"[^a-z0-9.-]")


def device_hostname(device_name: str, suffix: str) -> str:
    """Turn a Tailscale device name into a DNS-safe hostname.

    Tailscale names can be like ``nas`` or ``my-laptop.example.ts.net``.
    We strip the tailnet domain part and keep only the first label so the
    hostname is short.
    """
    host = device_name.split(".")[0].lower()
    host = HOSTNAME_SAFE.sub("-", host).strip("-")
    return f"{host}.{suffix}" if suffix else host


def device_ipv4(addresses: list[str]) -> str | None:
    """Return the first Tailscale IPv4 (100.x.x.x) or None."""
    for addr in addresses:
        if addr.startswith("100.") and ":" not in addr:
            return addr
    if addresses:
        return addresses[0]
    return None


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def sync_devices(
    ts: TailscaleClient,
    nd: NetlifyDnsClient,
    settings: Settings,
) -> int:
    """Run one sync cycle.  Returns count of changes made."""
    from netlify_dns import DnsRecord

    changes = 0

    # 1. Fetch devices
    devices = ts.list_devices()
    logger.info("Fetched %d device(s) from tailnet %s", len(devices), settings.tailnet_id)

    # 2. Fetch existing DNS records
    existing = nd.list_records()
    a_map: dict[str, DnsRecord] = {r.hostname: r for r in existing if r.type == "A"}
    logger.info("Found %d existing A record(s) in DNS zone", len(a_map))

    # 3. Build expected hostname → (ip, device_info) from devices
    #    When nginx-proxy mode is on, the A-record IP is the proxy's public IP;
    #    the device's real Tailscale IP is used only for the nginx upstream.
    desired: dict[str, tuple[str, str]] = {}  # hostname → (dns_ip, tailscale_ip)

    for dev in devices:
        if settings.device_filter_tag and settings.device_filter_tag not in dev.tags:
            logger.debug("Skipping %s (no matching tag)", dev.hostname)
            continue
        tailscale_ip = device_ipv4(dev.addresses)
        if not tailscale_ip:
            logger.warning("No IPv4 for device %s, skipping", dev.name)
            continue
        host = device_hostname(dev.name, settings.domain_suffix)

        # Decide which IP goes into the DNS A record
        if settings.nginx_proxy_enabled:
            dns_ip = settings.nginx_public_ip
        else:
            dns_ip = tailscale_ip

        desired[host] = (dns_ip, tailscale_ip)

    logger.info("Desired A records: %d device(s)", len(desired))

    # 4. Create / update A records
    for host, (dns_ip, tailscale_ip) in desired.items():
        existing_record = a_map.get(host)
        if existing_record is None:
            if settings.dry_run:
                logger.info("[DRY-RUN] Would create A record %s → %s", host, dns_ip)
            else:
                nd.create_a_record(host, dns_ip)
            changes += 1
        elif existing_record.value != dns_ip:
            if settings.dry_run:
                logger.info(
                    "[DRY-RUN] Would update A record %s from %s → %s",
                    host,
                    existing_record.value,
                    dns_ip,
                )
            else:
                nd.update_a_record(existing_record.id, host, dns_ip)
            changes += 1
        else:
            logger.debug("Record %s → %s is up to date", host, dns_ip)

    # 5. Remove stale A records
    for host, record in a_map.items():
        if host in desired or host == "@":
            continue
        if settings.domain_suffix:
            expected = f".{settings.domain_suffix}"
            if not host.endswith(expected):
                continue
        elif "." in host:
            continue
        logger.info("Stale device %s (no longer in tailnet), removing DNS record", host)
        if not settings.dry_run:
            nd.delete_record(record.id)
        changes += 1

    # 6. Nginx proxy config — only when proxy mode is active
    if settings.nginx_proxy_enabled and not settings.dry_run:
        _sync_nginx_config(desired, settings, nd.zone_domain)

    return changes


def _sync_nginx_config(
    desired: dict[str, tuple[str, str]],  # hostname → (dns_ip, tailscale_ip)
    settings: Settings,
    zone_domain: str,
) -> None:
    """Write nginx config for each proxied device and remove stale ones."""
    import nginx_config

    nginx_changed = False

    # FQDN for nginx server_name blocks
    def _fqdn(host: str) -> str:
        if "." in host:
            return host  # already a FQDN (domain_suffix was set)
        return f"{host}.{zone_domain}"

    for host, (dns_ip, tailscale_ip) in desired.items():
        fqdn = _fqdn(host)
        path = nginx_config.write_device_config(
            config_dir=settings.nginx_config_dir,
            hostname=fqdn,
            tailscale_ip=tailscale_ip,
            backend_port=settings.nginx_backend_port,
        )
        if path is not None:
            nginx_changed = True

    # Stale: config files for devices no longer in desired
    config_dir = Path(settings.nginx_config_dir)
    desired_fqdns = {_fqdn(h) for h in desired}
    if config_dir.exists():
        for f in config_dir.glob("*.conf"):
            hostname = f.stem
            if hostname not in desired_fqdns:
                nginx_config.remove_device_config(settings.nginx_config_dir, hostname)
                nginx_changed = True

    if nginx_changed:
        nginx_config.reload_nginx(cmd=settings.nginx_reload_cmd)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-5s] %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.setLevel(settings.log_level.upper())

    # Write pidfile so Coolify health checks can verify the process is alive
    pidfile = Path("/var/run/tailnet-dns-syncer.pid")
    try:
        pidfile.write_text(str(pidfile.parent))
    except OSError:
        pass  # non-fatal

    ts = TailscaleClient(
        api_key=settings.tailscale_api_key,
        tailnet=settings.tailnet_id,
    )
    nd = NetlifyDnsClient(
        token=settings.netlify_api_token,
        zone_id=settings.netlify_dns_zone_id,
    )

    logger.info(
        "tailnet-dns-syncer started — polling every %ds (dry_run=%s, nginx_proxy=%s)",
        settings.poll_interval_seconds,
        settings.dry_run,
        settings.nginx_proxy_enabled,
    )

    while True:
        try:
            changed = sync_devices(ts, nd, settings)
            if changed:
                logger.info("Sync complete — %d change(s) made", changed)
            else:
                logger.info("Sync complete — no changes")
        except Exception:
            logger.exception("Sync cycle failed")
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
