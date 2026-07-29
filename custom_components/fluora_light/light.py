"""Light entities for Fluora / PixelAir."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FluoraConfigEntry, Pa3Coordinator
from .const import CONF_PROTOCOL, DOMAIN, PROTOCOL_PA3


async def async_setup_entry(
    hass, entry: FluoraConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.data[CONF_PROTOCOL] == PROTOCOL_PA3:
        async_add_entities([Pa3Light(entry.runtime_data.coordinator, entry)])
    else:
        device, _listener = entry.runtime_data.client
        async_add_entities([LegacyLight(device, entry)])


class Pa3Light(CoordinatorEntity[Pa3Coordinator], LightEntity):
    _attr_supported_color_modes = {ColorMode.HS}

    def __init__(self, coordinator: Pa3Coordinator, entry: FluoraConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.data["serial"]
        self._attr_name = None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.data is not None
            and self.coordinator.last_update_success
        )

    @property
    def device_info(self) -> DeviceInfo:
        state = self.coordinator.data
        if state is None:
            return DeviceInfo(
                identifiers={(DOMAIN, self._entry.data["serial"])},
                name=self._entry.title,
                manufacturer="Fluora",
            )
        return DeviceInfo(
            identifiers={(DOMAIN, state.serial)},
            name=state.raw["payload"].get("config", {}).get("nickname", {}).get("v", state.serial),
            manufacturer="Fluora",
            model=state.model,
            sw_version=state.firmware_version,
            connections={("mac", state.mac_address)},
        )

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data
        return bool(state.power.value) if state is not None else None

    @property
    def brightness(self) -> int | None:
        state = self.coordinator.data
        return (
            round(float(state.brightness.value) * 255)
            if state is not None
            else None
        )

    @property
    def hs_color(self) -> tuple[float, float] | None:
        state = self.coordinator.data
        if state is None or state.hue is None or state.saturation is None:
            return None
        return float(state.hue.value) * 360, float(state.saturation.value) * 100

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.HS

    @property
    def effect_list(self) -> list[str]:
        state = self.coordinator.data
        if state is None:
            return []
        return [
            "Auto",
            *(f"Scene: {label}" for label in state.scenes),
            *(item.label for item in state.effects),
        ]

    @property
    def effect(self) -> str | None:
        state = self.coordinator.data
        return state.current_effect if state is not None else None

    @property
    def supported_features(self) -> LightEntityFeature:
        return LightEntityFeature.EFFECT

    def _optimistic_update(self, **changes: Any) -> None:
        """Keep HA responsive until Observe or polling confirms the snapshot."""

        state = self.coordinator.data
        if state is None:
            return
        parameter_changes = {
            key: replace(getattr(state, key), value=value)
            for key, value in changes.items()
            if key in {
                "power",
                "brightness",
                "mode",
                "active_scene_index",
                "manual_animation_index",
                "hue",
                "saturation",
            }
            and getattr(state, key) is not None
        }
        self.coordinator.async_set_updated_data(replace(state, **parameter_changes))

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self._entry.runtime_data.client
        await client.set_power(True, allow_write=True)
        changes: dict[str, Any] = {"power": True}
        if ATTR_BRIGHTNESS in kwargs:
            value = kwargs[ATTR_BRIGHTNESS] / 255
            await client.set_brightness(value, allow_write=True)
            changes["brightness"] = value
        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            await client.set_hs_color(hue, saturation, allow_write=True)
            changes.update(mode=2, hue=hue / 360, saturation=saturation / 100)
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            await client.set_effect(effect, allow_write=True)
            if effect == "Auto":
                changes["mode"] = 0
            elif effect.startswith("Scene: "):
                changes["mode"] = 1
                changes["active_scene_index"] = self.coordinator.data.scenes.index(
                    effect.removeprefix("Scene: ")
                )
            else:
                changes["mode"] = 2
                changes["manual_animation_index"] = next(
                    item.index
                    for item in self.coordinator.data.effects
                    if item.label == effect
                )
                changes["active_animation"] = effect
        active_animation = changes.pop("active_animation", None)
        self._optimistic_update(**changes)
        if active_animation is not None:
            self.coordinator.async_set_updated_data(
                replace(self.coordinator.data, active_animation=active_animation)
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.set_power(False, allow_write=True)
        self._optimistic_update(power=False)


class LegacyLight(LightEntity):
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, device, entry: FluoraConfigEntry) -> None:
        self._device = device
        self._attr_unique_id = entry.data["serial"]
        self._state = None

    async def async_update(self) -> None:
        self._state = await self._device.get_state()

    @property
    def is_on(self):
        return self._state.is_on if self._state else None

    @property
    def brightness(self):
        return round(self._state.brightness * 255) if self._state else None

    @property
    def hs_color(self):
        return (self._state.hue * 360, self._state.saturation * 100) if self._state else None

    @property
    def color_mode(self):
        return ColorMode.HS

    @property
    def effect(self):
        return self._state.current_effect if self._state else None

    @property
    def effect_list(self):
        return [item.display_name for item in self._state.effects] if self._state else []

    async def async_turn_on(self, **kwargs):
        await self._device.turn_on()
        if ATTR_BRIGHTNESS in kwargs:
            await self._device.set_brightness(kwargs[ATTR_BRIGHTNESS] / 255)
        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            await self._device.set_hue(hue / 360)
            await self._device.set_saturation(saturation / 100)
        if ATTR_EFFECT in kwargs:
            effect = next(
                item for item in self._state.effects
                if item.display_name == kwargs[ATTR_EFFECT]
            )
            await self._device.set_effect(effect.id)
        await self.async_update()

    async def async_turn_off(self, **kwargs):
        await self._device.turn_off()
        await self.async_update()
