# Vibe Coded Disclaimer
This integration and all the work related to it was all done using AI.

# Fluora / PixelAir local integration

This repository contains a standalone protocol client, evidence, tests, and a
Home Assistant custom integration for legacy and PA3 firmware.

Read-only diagnostics:

```bash
python -m fluora_protocol.pa3.cli probe --host DEVICE_IP
python -m fluora_protocol.pa3.cli state --host DEVICE_IP
python -m fluora_protocol.pa3.cli observe --host DEVICE_IP --seconds 60
```

Writes are never enabled implicitly:

```bash
python -m fluora_protocol.pa3.cli power --host DEVICE_IP --on --allow-write
python -m fluora_protocol.pa3.cli brightness --host DEVICE_IP --value 0.5 --allow-write
python -m fluora_protocol.pa3.cli color --host DEVICE_IP --hue 220 --saturation 80 --allow-write
```

All of this is based off of the APK code on the Android client. I've verified this works at home.

Version 0.6 exposes PA3 Auto, scene, and animation effects for physical
testing. HS color selection automatically enters Manual mode. Home Assistant
updates successful writes immediately while Observe and polling confirm the
authoritative device state.

## Home Assistant

Copy `custom_components/fluora_light` into the Home Assistant configuration
directory, restart, and add “Fluora / PixelAir” in Devices & services. The
flow discovers both PA3 and legacy devices and presents a device picker. If
broadcast discovery is unavailable, choose manual setup and enter only the
device IP; protocol, serial, MAC, nickname, and model are derived automatically.

For migration from the old YAML component, note the IP and serial, remove its
YAML, restart, and add the device through the config flow. The serial is the
stable unique ID. PA3 effect writes are available for physical testing, and
legacy effect control remains available.

### Install with HACS

In HACS, open the menu, choose **Custom repositories**, add:

```text
https://github.com/xenocidewiki/fluora-light-home-assistant-integration
```

Select **Integration** as the category, install Fluora / PixelAir, restart
Home Assistant, then add the integration from **Settings → Devices & services**.
