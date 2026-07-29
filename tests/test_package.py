import json
import zipfile
from pathlib import Path


def test_custom_component_manifest() -> None:
    root = Path("custom_components/fluora_light")
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["domain"] == "fluora_light"
    assert manifest["config_flow"] is True
    for required in ("__init__.py", "config_flow.py", "light.py", "diagnostics.py"):
        assert (root / required).is_file()


def test_home_assistant_api_and_write_regressions() -> None:
    root = Path("custom_components/fluora_light")
    setup = (root / "__init__.py").read_text()
    flow = (root / "config_flow.py").read_text()
    light = (root / "light.py").read_text()
    assert "entry.runtime_data =" in setup
    assert 'observer.observe("/deltas")' in setup
    assert "async_forward_entry_setups" in setup
    assert "_attr_supported_color_modes = {ColorMode.HS}" in light
    assert "set_power(False, allow_write=True)" in light
    assert "return LightEntityFeature.EFFECT" in light
    assert "await client.set_effect(effect, allow_write=True)" in light
    assert "changes.update(mode=2" in light
    assert "discover_with_info" in flow
    assert "discover_pa3" in flow
    assert "async_step_manual" in flow
    assert "device = await self._async_probe_pa3(host)" in flow
    assert "device = await self._async_probe_legacy(host)" in flow
    manual_section = flow.split("async def async_step_manual", 1)[1]
    assert "vol.Required(CONF_HOST)" in manual_section
    assert "vol.Required(CONF_SERIAL)" not in manual_section
    assert "vol.Required(CONF_MAC)" not in manual_section


def test_distribution_zip_when_present() -> None:
    archive = Path("dist/fluora_light.zip")
    if not archive.exists():
        return
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
    assert "fluora_light/manifest.json" in names
    assert "fluora_light/light.py" in names
