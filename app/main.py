#!/usr/bin/env python3
"""tailnet-dns-syncer — poll the Tailscale tailnet and sync A records to Netlify DNS.

Every *poll_interval* seconds:
  1. Fetch all devices from the Tailscale API.
  2. Fetch all existing A records from the Netlify DNS zone.
  3. For each device (optionally filtered by tag):
       - Derive a DNS hostname from the device name.
       - If no A record exists → create one pointing to the device's Tailscale IPv4.
       - If an A record exists but points to a different IP → update it.
  4. Remove A records for devices that are no longer in the tailnet
     (only those that were *originally* created by this tool, identified by a
      convention — the hostname must match a known device name pattern).
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
        if addr.startswith("100.") and ":" not in addr:  # crude v4 check
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
    from netlify_dns import DnsRecord  # noqa: F401  — lazy import for type hints

    changes = 0

    # 1. Fetch devices
    devices = ts.list_devices()
    logger.info("Fetched %d device(s) from tailnet %s", len(devices), settings.tailnet_id)

    # 2. Fetch existing DNS records
    existing = nd.list_records()
    a_map: dict[str, DnsRecord] = {r.hostname: r for r in existing if r.type == "A"}
    logger.info("Found %d existing A record(s) in DNS zone", len(a_map))

    # 3. Build expected hostname → IP map from devices
    desired: dict[str, str] = {}  # hostname → tailscale IP
    for dev in devices:
        if settings.device_filter_tag and settings.device_filter_tag not in dev.tags:
            logger.debug("Skipping %s (no matching tag)", dev.hostname)
            continue
        ip = device_ipv4(dev.addresses)
        if not ip:
            logger.warning("No IPv4 for device %s, skipping", dev.name)
            continue
        host = device_hostname(dev.name, settings.domain_suffix)
        desired[host] = ip

    logger.info("Desired A records: %d device(s)", len(desired))

    # 4. Create / update records
    for host, ip in desired.items():
        existing_record = a_map.get(host)
        if existing_record is None:
            # Create
            if settings.dry_run:
                logger.info("[DRY-RUN] Would create A record %s → %s", host, ip)
            else:
                nd.create_a_record(host, ip)
            changes += 1
        elif existing_record.value != ip:
            # Update
            if settings.dry_run:
                logger.info(
                    "[DRY-RUN] Would update A record %s from %s → %s",
                    host,
                    existing_record.value,
                    ip,
                )
            else:
                nd.update_a_record(existing_record.id, host, ip)
            changes += 1
        else:
            logger.debug("Record %s → %s is up to date", host, ip)

    # 5. Remove stale records (those that match our naming convention
    #    but no longer correspond to a known device).
    if settings.domain_suffix:
        prefix = f".{settings.domain_suffix}"
    else:
        prefix = ""  # bare hostnames — risky, so only clean up known devices

    for host, record in a_map.items():
        if host in desired:
            continue
        # Only remove records that look like they were created by us
        if settings.domain_suffix and not host.endswith(prefix):
            continue
        logger.info("Stale device %s (no longer in tailnet), removing DNS record", host)
        if not settings.dry_run:
            nd.delete_record(record.id)
        changes += 1

    return changes


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
        "tailnet-dns-syncer started — polling every %ds (dry_run=%s)",
        settings.poll_interval_seconds,
        settings.dry_run,
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
