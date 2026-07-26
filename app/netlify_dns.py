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
    hostname: str  # bare / relative to the zone (e.g. "nas", not "nas.example.com")
    type: str
    value: str
    ttl: int


class NetlifyDnsClient:
    """Thin wrapper around the Netlify DNS records API."""

    def __init__(self, token: str, zone_id: str) -> None:
        self.zone_id = zone_id
        self._zone_domain: str | None = None
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
    # Zone domain — fetched lazily so we can normalise hostnames
    # ------------------------------------------------------------------

    @property
    def zone_domain(self) -> str:
        if self._zone_domain is None:
            resp = self._client.get(f"/dns_zones/{self.zone_id}")
            resp.raise_for_status()
            self._zone_domain = resp.json()["name"]
            logger.debug("Zone domain: %s", self._zone_domain)
        return self._zone_domain

    def _rel_hostname(self, hostname: str) -> str:
        """Strip the zone domain from a full hostname.

        ``nas.694206969.xyz`` → ``nas``,  ``@`` → ``@`` (root).
        """
        domain = self.zone_domain
        if hostname == domain:
            return "@"
        if hostname.endswith(f".{domain}"):
            return hostname[: -len(f".{domain}")]
        return hostname  # already bare

    # ------------------------------------------------------------------
    # Record operations
    # ------------------------------------------------------------------

    def list_records(self) -> list[DnsRecord]:
        """Return all DNS records in the zone with *relative* hostnames."""
        resp = self._client.get(f"/dns_zones/{self.zone_id}/dns_records")
        resp.raise_for_status()
        raw = resp.json()
        out: list[DnsRecord] = []
        for r in raw:
            out.append(
                DnsRecord(
                    id=r["id"],
                    hostname=self._rel_hostname(r["hostname"]),
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

    def update_a_record(self, record_id: str, hostname: str, ip: str, ttl: int = 300) -> dict:
        """Update an existing A record in-place via PUT."""
        payload = {
            "type": "A",
            "hostname": hostname,
            "value": ip,
            "ttl": ttl,
        }
        resp = self._client.put(
            f"/dns_zones/{self.zone_id}/dns_records/{record_id}",
            json=payload,
        )
        resp.raise_for_status()
        logger.info("Updated A record %s → %s (TTL=%d)", hostname, ip, ttl)
        return resp.json()

    def delete_record(self, record_id: str) -> None:
        """Remove a DNS record by its ID."""
        resp = self._client.delete(
            f"/dns_zones/{self.zone_id}/dns_records/{record_id}"
        )
        resp.raise_for_status()
        logger.info("Deleted DNS record %s", record_id)
