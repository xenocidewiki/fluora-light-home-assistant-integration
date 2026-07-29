"""Typed projections of the PA3 global snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Parameter:
    identifier: str
    type: str
    value: bool | int | float | str

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> Parameter:
        return cls(str(raw["i"]), str(raw["t"]), raw["v"])


@dataclass(frozen=True, slots=True)
class Effect:
    index: int
    label: str
    category: str
    is_audio: bool
    occasion: int


@dataclass(frozen=True, slots=True)
class Pa3State:
    serial: str
    mac_address: str
    model: str
    firmware_version: str
    boot_count: int
    revision: int
    power: Parameter
    brightness: Parameter
    mode: Parameter
    active_scene_index: Parameter
    manual_animation_index: Parameter | None
    hue: Parameter | None
    saturation: Parameter | None
    active_animation: str | None
    effects: tuple[Effect, ...]
    scenes: tuple[str, ...]
    raw: dict[str, Any]

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> Pa3State:
        if snapshot.get("protocol") != "1.1" or snapshot.get("type") != "snapshot":
            raise ValueError("not a PA3 protocol 1.1 snapshot")
        payload = snapshot["payload"]
        device = payload["device"]
        engine = payload["engine"]
        manual = payload.get("mode/manual", {})
        palette = manual.get("palette", {})
        animations = payload.get("animations", [])
        return cls(
            serial=str(snapshot["serial"]),
            mac_address=str(device["mac_address"]),
            model=str(device["model"]),
            firmware_version=str(device["firmware_version"]),
            boot_count=int(device["boot_count"]),
            revision=int(snapshot["revision"]),
            power=Parameter.from_wire(engine["is_displaying"]),
            brightness=Parameter.from_wire(engine["master_brightness"]),
            mode=Parameter.from_wire(engine["mode"]),
            active_scene_index=Parameter.from_wire(engine["active_scene_index"]),
            manual_animation_index=(
                Parameter.from_wire(manual["anim_manual"])
                if "anim_manual" in manual
                else (
                    Parameter.from_wire(manual["anim_index"])
                    if "anim_index" in manual
                    else None
                )
            ),
            hue=Parameter.from_wire(palette["hue"]) if "hue" in palette else None,
            saturation=(
                Parameter.from_wire(palette["saturation"])
                if "saturation" in palette
                else None
            ),
            active_animation=manual.get("anim_label"),
            effects=tuple(
                Effect(
                    index=index,
                    label=str(item["label"]),
                    category=str(item["category"]),
                    is_audio=bool(item["is_audio"]),
                    occasion=int(item["occasion"]),
                )
                for index, item in enumerate(animations)
            ),
            scenes=tuple(str(item["label"]) for item in engine.get("scenes", [])),
            raw=snapshot,
        )

    @property
    def current_effect(self) -> str | None:
        """Return the displayed bank/effect using the engine mode."""

        mode = int(self.mode.value)
        if mode == 0:
            return "Auto"
        if mode == 1:
            index = int(self.active_scene_index.value)
            if 0 <= index < len(self.scenes):
                return f"Scene: {self.scenes[index]}"
            return "Scene"
        if mode == 2:
            return self.active_animation
        return None
