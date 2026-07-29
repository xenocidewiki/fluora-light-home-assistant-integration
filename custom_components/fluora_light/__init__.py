"""Fluora / PixelAir local integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_PROTOCOL, PLATFORMS, PROTOCOL_PA3
from .fluora_protocol.pa3.client import Pa3Client
from .fluora_protocol.pa3.models import Pa3State

_LOGGER = logging.getLogger(__name__)


class Pa3Coordinator(DataUpdateCoordinator[Pa3State]):
    """Poll the global snapshot; Observe support can trigger refreshes."""

    def __init__(self, hass: HomeAssistant, client: Pa3Client) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Fluora PA3",
            update_interval=__import__("datetime").timedelta(seconds=15),
        )
        self.client = client

    async def _async_update_data(self) -> Pa3State:
        try:
            return await self.client.get_state()
        except (OSError, TimeoutError, ValueError) as error:
            raise UpdateFailed(str(error)) from error


@dataclass(slots=True)
class RuntimeData:
    coordinator: Pa3Coordinator | None
    client: Any
    observe_task: asyncio.Task[None] | None = None
    refresh_task: asyncio.Task[None] | None = None


FluoraConfigEntry = ConfigEntry[RuntimeData]


async def _observe_pa3(coordinator: Pa3Coordinator, host: str) -> None:
    """Refresh state when a delta notification arrives, reconnecting on failure."""

    while True:
        observer = Pa3Client(host)
        try:
            initial = True
            async for _response in observer.observe("/deltas"):
                if initial:
                    initial = False
                    continue
                await coordinator.async_request_refresh()
        except (OSError, TimeoutError, ValueError):
            await asyncio.sleep(5)
        finally:
            observer.close()


async def _initial_refresh_pa3(coordinator: Pa3Coordinator) -> None:
    """Fetch initial state without holding up Home Assistant startup."""

    try:
        await coordinator.async_refresh()
    except asyncio.CancelledError:
        raise
    except Exception:
        _LOGGER.debug("Initial PA3 refresh failed; background polling will retry", exc_info=True)


async def async_setup_entry(hass: HomeAssistant, entry: FluoraConfigEntry) -> bool:
    """Set up one device."""

    if entry.data[CONF_PROTOCOL] == PROTOCOL_PA3:
        client = Pa3Client(entry.data["host"])
        coordinator = Pa3Coordinator(hass, client)
        entry.runtime_data = RuntimeData(coordinator, client)
    else:
        from libpixelair import PixelAirDevice, UDPListener

        listener = UDPListener()
        await listener.start()
        device = await PixelAirDevice.from_identifiers(
            mac_address=entry.data.get("mac_address"),
            serial_number=entry.data["serial"],
            listener=listener,
        )
        if device is None:
            await listener.stop()
            raise ConfigEntryNotReady("Legacy PixelAir device was not found")
        await device.register()
        entry.runtime_data = RuntimeData(None, (device, listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if entry.data[CONF_PROTOCOL] == PROTOCOL_PA3:
        data = entry.runtime_data
        assert data.coordinator is not None
        data.refresh_task = hass.async_create_background_task(
            _initial_refresh_pa3(data.coordinator),
            f"fluora-pa3-initial-refresh-{entry.data['serial']}",
        )
        data.observe_task = hass.async_create_background_task(
            _observe_pa3(data.coordinator, entry.data["host"]),
            f"fluora-pa3-observe-{entry.data['serial']}",
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FluoraConfigEntry) -> bool:
    """Unload platforms and close sockets."""

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    data = entry.runtime_data
    if data.coordinator is not None:
        tasks = [
            task
            for task in (data.observe_task, data.refresh_task)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        data.client.close()
    else:
        device, listener = data.client
        await device.unregister()
        await listener.stop()
    return True
