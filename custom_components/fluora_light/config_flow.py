"""Config flow for local Fluora devices."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import (
    CONF_MAC,
    CONF_PROTOCOL,
    CONF_SERIAL,
    DOMAIN,
    PROTOCOL_LEGACY,
    PROTOCOL_PA3,
)
from .fluora_protocol.discovery import discover_pa3
from .fluora_protocol.pa3.client import Pa3Client

CONF_DEVICE = "device"
MANUAL = "__manual__"


class FluoraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Discover a Fluora or configure one by IP address."""

    VERSION = 3

    def __init__(self) -> None:
        self._discovered: dict[str, dict[str, str]] = {}

    async def _async_discover_legacy(self) -> list[dict[str, str]]:
        from libpixelair import DiscoveryService
        from .legacy import acquire_listener, release_listener

        listener = await acquire_listener(self.hass)
        try:
            devices = await DiscoveryService(listener).discover_with_info(
                timeout=5.0,
                broadcast_count=3,
                broadcast_interval=1.0,
                state_timeout=5.0,
            )
            return [
                {
                    CONF_HOST: item.ip_address,
                    CONF_PROTOCOL: PROTOCOL_LEGACY,
                    CONF_SERIAL: item.serial_number,
                    CONF_MAC: item.mac_address or "",
                    "title": item.nickname or item.model or item.serial_number,
                    "model": item.model or "Legacy PixelAir",
                }
                for item in devices
                if item.mac_address
            ]
        except (OSError, RuntimeError, TimeoutError):
            return []
        finally:
            await release_listener(self.hass)

    async def _async_discover_all(self) -> None:
        pa3_result, legacy_result = await asyncio.gather(
            discover_pa3(5.0),
            self._async_discover_legacy(),
            return_exceptions=True,
        )
        found: list[dict[str, str]] = []
        if not isinstance(pa3_result, BaseException):
            found.extend(
                {
                    CONF_HOST: item.ip_address,
                    CONF_PROTOCOL: PROTOCOL_PA3,
                    CONF_SERIAL: item.serial,
                    CONF_MAC: "",
                    "title": item.nickname or item.serial,
                    "model": item.model,
                }
                for item in pa3_result
            )
        if not isinstance(legacy_result, BaseException):
            found.extend(legacy_result)
        self._discovered = {
            f"{item[CONF_PROTOCOL]}:{item[CONF_SERIAL]}": item for item in found
        }

    async def _async_create_device_entry(
        self, device: dict[str, str]
    ) -> ConfigFlowResult:
        serial = device[CONF_SERIAL]
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: device[CONF_HOST]}, reload_on_update=True
        )
        data = {
            CONF_HOST: device[CONF_HOST],
            CONF_PROTOCOL: device[CONF_PROTOCOL],
            CONF_SERIAL: serial,
        }
        if device.get(CONF_MAC):
            data[CONF_MAC] = device[CONF_MAC]
        return self.async_create_entry(title=device["title"], data=data)

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Discover devices and offer a picker."""

        if not self._discovered:
            await self._async_discover_all()
        if user_input is not None:
            selected = user_input[CONF_DEVICE]
            if selected == MANUAL:
                return await self.async_step_manual()
            return await self._async_create_device_entry(self._discovered[selected])

        choices = {
            key: (
                f"{item['title']} — {item['model']} "
                f"({item[CONF_HOST]}, {item[CONF_PROTOCOL].upper()})"
            )
            for key, item in self._discovered.items()
        }
        choices[MANUAL] = "Enter an IP address manually"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(choices)}),
        )

    async def _async_probe_pa3(self, host: str) -> dict[str, str] | None:
        client = Pa3Client(host, ack_timeout=1.0, max_retransmit=1)
        try:
            response = await client.get("/discovery")
            payload: Any = response.decoded_payload()
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                return None
            serial = payload.get("serial_number") or payload.get("serial")
            if not serial or payload.get("protocol") != "PA-CoAP-1.0":
                return None
            return {
                CONF_HOST: host,
                CONF_PROTOCOL: PROTOCOL_PA3,
                CONF_SERIAL: str(serial),
                CONF_MAC: "",
                "title": str(
                    payload.get("name")
                    or payload.get("nickname")
                    or serial
                ),
                "model": str(payload.get("platform") or payload.get("model") or "Fluora"),
            }
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        finally:
            client.close()

    async def _async_probe_legacy(self, host: str) -> dict[str, str] | None:
        from .legacy import acquire_listener, probe_device, release_listener

        listener = await acquire_listener(self.hass)
        try:
            item = await probe_device(host, listener)
            if not item.mac_address or not item.serial_number:
                return None
            return {
                CONF_HOST: host,
                CONF_PROTOCOL: PROTOCOL_LEGACY,
                CONF_SERIAL: item.serial_number,
                CONF_MAC: item.mac_address,
                "title": item.nickname or item.model or item.serial_number,
                "model": item.model or "Legacy PixelAir",
            }
        except (OSError, RuntimeError, TimeoutError, ValueError):
            return None
        finally:
            await release_listener(self.hass)

    async def async_step_manual(self, user_input=None) -> ConfigFlowResult:
        """Accept only an IP and derive every identity field."""

        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device = await self._async_probe_pa3(host)
            if device is None:
                device = await self._async_probe_legacy(host)
            if device is not None:
                return await self._async_create_device_entry(device)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )
