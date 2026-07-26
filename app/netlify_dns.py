"""Netlify DNS API client — manage A records in a zone."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

NETLIFY_API = "https://api.netlify.com/api/v1"


@dataclass
class DnsRecord:
    id: str
    hostname: str
    type: str
    value: str
    ttl: int


class NetlifyDnsClient:
    """Thin wrapper around the Netlify DNS records API."""

    def __init__(self, token: str, zone_id: str) -> None:
        self.zone_id = zone_id
        self._client = httpx.Client(
            base_url=NETLIFY_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    # ------------------------------------------------------------------

    def list_records(self) -> list[DnsRecord]:
        """Return all DNS records in the zone."""
        resp = self._client.get(f"/dns_zones/{self.zone_id}/dns_records")
        resp.raise_for_status()
        raw = resp.json()
        out: list[DnsRecord] = []
        for r in raw:
            out.append(
                DnsRecord(
                    id=r["id"],
                    hostname=r["hostname"],
                    type=r["type"],
                    value=r["value"],
                    ttl=r.get("ttl", 3600),
                )
            )
        return out

    def create_a_record(self, hostname: str, ip: str, ttl: int = 300) -> dict:
        """Create an A record.  Returns the API response JSON."""
        payload = {
            "type": "A",
            "hostname": hostname,
            "value": ip,
            "ttl": ttl,
        }
        resp = self._client.post(
            f"/dns_zones/{self.zone_id}/dns_records",
            json=payload,
        )
        resp.raise_for_status()
        logger.info("Created A record %s → %s (TTL=%d)", hostname, ip, ttl)
        return resp.json()

    def delete_record(self, record_id: str) -> None:
        """Remove a DNS record by its ID."""
        resp = self._client.delete(
            f"/dns_zones/{self.zone_id}/dns_records/{record_id}"
        )
        resp.raise_for_status()
        logger.info("Deleted DNS record %s", record_id)

    def update_a_record(self, record_id: str, hostname: str, ip: str, ttl: int = 300) -> dict:
        """Replace an existing A record's value.  Netlify treats this as
        delete + create under the hood (PUT is not available), so we
        simplify by calling delete_record then create_a_record."""
        self.delete_record(record_id)
        return self.create_a_record(hostname, ip, ttl)
