"""Diagnostics for Fluora entries."""

from homeassistant.components.diagnostics import async_redact_data

from . import FluoraConfigEntry

TO_REDACT = {"host", "ip_address", "mac_address", "gateway", "subnet"}


async def async_get_config_entry_diagnostics(hass, entry: FluoraConfigEntry):
    data = entry.runtime_data
    state = data.coordinator.data.raw if data.coordinator is not None else {}
    return async_redact_data(
        {"entry": dict(entry.data), "state": state}, TO_REDACT
    )
