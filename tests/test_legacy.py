"""Legacy binary-only probing and shared-listener lifecycle regressions."""

import asyncio
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


class FakeListener:
    def __init__(self):
        self.is_running = False
        self.bound = False
        self.starts = 0
        self.stops = 0
        self.devices = {}
        self.sent = []
        self.fail_send = False
        self.block_send = False
        self.sending = asyncio.Event()
        self.state = SimpleNamespace(
            serial_number="example", mac_address="00:11:22:33:44:55", model="Monos"
        )

    async def start(self):
        if self.bound:
            raise OSError("socket is still bound")
        self.bound = self.is_running = True
        self.starts += 1

    async def stop(self):
        self.is_running = False
        self.stops += 1
        # Match asyncio's delayed DatagramTransport socket release.
        asyncio.get_running_loop().call_soon(setattr, self, "bound", False)

    async def send_to(self, packet, host, port):
        self.sent.append((packet, host, port))
        self.sending.set()
        if self.fail_send:
            raise OSError("send failed")
        if self.block_send:
            await asyncio.Future()
        device = self.devices[host]
        assert device.waiter is not None, "state waiter must precede discovery"
        # No JSON discovery reply: only the assembled binary state is delivered.
        device.waiter.set_result(self.state)


class FakeDevice:
    def __init__(self, *, ip_address, listener, **kwargs):
        self.ip_address = ip_address
        self.listener = listener
        self.waiter = None
        self.registered = False
        self.request_finished = False

    async def register(self):
        self.registered = True
        self.listener.devices[self.ip_address] = self

    async def unregister(self):
        self.registered = False

    async def get_state(self, timeout):
        self.waiter = asyncio.get_running_loop().create_future()
        try:
            return await self.waiter
        finally:
            self.request_finished = True


class FakeOscBuilder:
    def __init__(self, route):
        self.route = route
        self.args = []

    def add_arg(self, value, kind):
        assert kind == "i"
        self.args.append(value)

    def build(self):
        return SimpleNamespace(dgram=(self.route, tuple(self.args)))


@contextmanager
def legacy_module():
    # Keep the protocol test suite independent of HA and its installed SDKs.
    package = ModuleType("_fluora_legacy_test")
    package.__path__ = [str(
        Path(__file__).resolve().parents[1] / "custom_components/fluora_light"
    )]
    pixelair = ModuleType("libpixelair")
    pixelair.PixelAirDevice = FakeDevice
    pixelair.UDPListener = FakeListener
    osc = ModuleType("pythonosc.osc_message_builder")
    osc.OscMessageBuilder = FakeOscBuilder
    with patch.dict(sys.modules, {
        package.__name__: package,
        "libpixelair": pixelair,
        "pythonosc": ModuleType("pythonosc"),
        "pythonosc.osc_message_builder": osc,
    }):
        yield importlib.import_module(f"{package.__name__}.legacy")


def test_shared_listener_is_released_only_after_last_user() -> None:
    async def run(legacy):
        hass = SimpleNamespace(data={})
        first, second = await asyncio.gather(
            legacy.acquire_listener(hass), legacy.acquire_listener(hass)
        )
        assert first is second and first.starts == 1
        await legacy.release_listener(hass)
        assert second.is_running and second.stops == 0
        await legacy.release_listener(hass)
        assert not second.is_running and second.stops == 1
        again = await legacy.acquire_listener(hass)
        assert again is first and again.starts == 2
        await legacy.release_listener(hass)

    with legacy_module() as legacy:
        asyncio.run(run(legacy))


def test_probe_accepts_binary_only_state() -> None:
    async def run(legacy):
        listener = FakeListener()
        state = await legacy.probe_device("127.0.0.1", listener)
        assert state is listener.state
        packet, host, port = listener.sent[0]
        assert packet == ("/fluoraDiscovery", tuple(map(ord, "127.0.0.1")))
        assert host == "127.0.0.1" and port == 9090
        device = listener.devices[host]
        assert device.request_finished and not device.registered

    with legacy_module() as legacy:
        asyncio.run(run(legacy))


def test_probe_send_failure_cleans_up_waiter_and_device() -> None:
    async def run(legacy):
        listener = FakeListener()
        listener.fail_send = True
        with TestCase().assertRaises(OSError):
            await legacy.probe_device("127.0.0.1", listener)
        device = listener.devices["127.0.0.1"]
        assert device.waiter.cancelled()
        assert device.request_finished and not device.registered

    with legacy_module() as legacy:
        asyncio.run(run(legacy))


def test_probe_cancellation_cleans_up_waiter_and_device() -> None:
    async def run(legacy):
        listener = FakeListener()
        listener.block_send = True
        pending = asyncio.create_task(legacy.probe_device("127.0.0.1", listener))
        await listener.sending.wait()
        pending.cancel()
        with TestCase().assertRaises(asyncio.CancelledError):
            await pending
        device = listener.devices["127.0.0.1"]
        assert device.waiter.cancelled()
        assert device.request_finished and not device.registered

    with legacy_module() as legacy:
        asyncio.run(run(legacy))
