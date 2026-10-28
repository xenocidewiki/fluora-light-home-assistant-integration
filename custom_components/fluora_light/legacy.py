"""Shared transport and binary-state discovery for older PixelAir firmware."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import socket
from typing import TYPE_CHECKING

from libpixelair import PixelAirDevice, UDPListener
from pythonosc.osc_message_builder import OscMessageBuilder

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from libpixelair import DeviceState


@dataclass
class LegacyTransport:
    listener: UDPListener = field(default_factory=UDPListener)
    users: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def acquire_listener(hass: HomeAssistant) -> UDPListener:
    """Keep one socket on UDP 12345 for runtime devices and config flows."""

    data = hass.data.setdefault(DOMAIN, {})
    transport = data.get("legacy_transport")
    if transport is None:
        transport = data["legacy_transport"] = LegacyTransport()
    async with transport.lock:
        if not transport.users:
            await transport.listener.start()
        transport.users += 1
    return transport.listener


async def release_listener(hass: HomeAssistant) -> None:
    transport = hass.data[DOMAIN]["legacy_transport"]
    async with transport.lock:
        transport.users -= 1
        if not transport.users:
            await transport.listener.stop()
            # DatagramTransport.close releases its socket on the next loop turn.
            await asyncio.sleep(0)


async def request_state(device: PixelAirDevice, listener: UDPListener) -> DeviceState:
    """Prime the reply address; firmware 2.1.9 returns a binary snapshot."""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((device.ip_address, 9090))
        source_ip = sock.getsockname()[0]
    builder = OscMessageBuilder("/fluoraDiscovery")
    for char in source_ip:
        builder.add_arg(ord(char), "i")
    pending = asyncio.create_task(device.get_state(timeout=5.0))
    try:
        # Install the state waiter before the device can answer discovery.
        await asyncio.sleep(0)
        await listener.send_to(builder.build().dgram, device.ip_address, 9090)
        return await pending
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def probe_device(host: str, listener: UDPListener) -> DeviceState:
    """Read identity from the snapshot without requiring JSON discovery."""

    device = PixelAirDevice(
        ip_address=host,
        listener=listener,
        serial_number="",
        mac_address="",
        _internal=True,
    )
    await device.register()
    try:
        return await request_state(device, listener)
    finally:
        await device.unregister()
