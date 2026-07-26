"""Tailscale API v2 client — fetch devices in a tailnet."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TAILSCALE_API = "https://api.tailscale.com/api/v2"


@dataclass
class TailscaleDevice:
    """A single device/node in the tailnet."""

    id: str
    name: str  # e.g. "nas" or "nas.example.ts.net"
    hostname: str
    addresses: list[str]  # Tailscale IPs (100.x.x.x, fd7a:...)
    tags: list[str]
    os: str
    user: str
    last_seen: str | None


class TailscaleClient:
    """Thin wrapper around the Tailscale API v2."""

    def __init__(self, api_key: str, tailnet: str) -> None:
        self._auth = (api_key, "")  # Basic auth with empty password
        self.tailnet = tailnet
        self._client = httpx.Client(
            auth=self._auth,
            base_url=TAILSCALE_API,
            headers={"Accept": "application/json"},
            timeout=30,
        )

    # ------------------------------------------------------------------

    def list_devices(self) -> list[TailscaleDevice]:
        """Return every device currently in the tailnet."""
        resp = self._client.get(f"/tailnet/{self.tailnet}/devices")
        resp.raise_for_status()
        raw = resp.json()["devices"]
        logger.debug("Tailscale returned %d device(s)", len(raw))

        devices: list[TailscaleDevice] = []
        for d in raw:
            devices.append(
                TailscaleDevice(
                    id=d["id"],
                    name=d["name"],
                    hostname=d.get("hostname", d["name"].split(".")[0]),
                    addresses=d.get("addresses", []),
                    tags=d.get("tags", []),
                    os=d.get("os", "unknown"),
                    user=d.get("user", ""),
                    last_seen=d.get("lastSeen"),
                )
            )
        return devices
