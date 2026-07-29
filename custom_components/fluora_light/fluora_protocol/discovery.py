"""Firmware 3.x broadcast discovery."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass

DISCOVERY_PORT = 5684
PA3_PROTOCOL = "PA-CoAP-1.0"


@dataclass(frozen=True, slots=True)
class DiscoveryAnnouncement:
    """A validated PA3 broadcast announcement."""

    ip_address: str
    serial: str
    firmware_version: str
    nickname: str
    model: str
    protocol: str = PA3_PROTOCOL
    source_address: str | None = None

    @classmethod
    def from_bytes(cls, data: bytes, source_address: str) -> DiscoveryAnnouncement:
        raw = json.loads(data.decode("utf-8"))
        if raw.get("protocol") != PA3_PROTOCOL:
            raise ValueError("not a PA-CoAP-1.0 announcement")
        serial = str(raw.get("serial", "")).strip()
        if not serial:
            raise ValueError("announcement has no serial")
        return cls(
            ip_address=str(raw.get("ip_address") or source_address),
            serial=serial,
            firmware_version=str(raw.get("firmware_version", "")),
            nickname=str(raw.get("nickname", "")),
            model=str(raw.get("model", "")),
            source_address=source_address,
        )


async def discover_pa3(timeout: float = 8.0) -> list[DiscoveryAnnouncement]:
    """Listen for PA3 JSON broadcasts, deduplicated by stable serial number."""

    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", DISCOVERY_PORT))
    sock.setblocking(False)
    found: dict[str, DiscoveryAnnouncement] = {}
    deadline = loop.time() + timeout
    try:
        while (remaining := deadline - loop.time()) > 0:
            try:
                data, address = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535), remaining
                )
            except TimeoutError:
                break
            try:
                item = DiscoveryAnnouncement.from_bytes(data, address[0])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                continue
            found[item.serial] = item
    finally:
        sock.close()
    return list(found.values())

