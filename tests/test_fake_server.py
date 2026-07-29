import asyncio
from copy import deepcopy
import json

from fluora_protocol.pa3.client import Pa3Client
from fluora_protocol.pa3.coap import CoapMessage, CoapOption, MessageType, decode, encode
from fluora_protocol.pa3.constants import OPTION_CONTENT_FORMAT


SNAPSHOT = {
    "protocol": "1.1", "serial": "abc123", "type": "snapshot", "revision": 7,
    "payload": {
        "animations": [],
        "device": {"mac_address": "00:11:22:33:44:55", "model": "Fluora Mini",
                   "firmware_version": "3.1.6", "boot_count": 2},
        "engine": {
            "is_displaying": {"i": "power-id", "t": "bool", "v": True},
            "master_brightness": {"i": "brightness-id", "t": "float", "v": 0.5},
            "mode": {"i": "mode-id", "t": "int", "v": 2},
            "active_scene_index": {"i": "scene-id", "t": "int", "v": 0},
            "scenes": [],
        },
        "mode/manual": {
            "anim_manual": {"i": "animation-id", "t": "int", "v": 2},
            "anim_label": "Mirage",
            "palette": {
                "hue": {"i": "hue-id", "t": "float", "v": 0.25},
                "saturation": {"i": "sat-id", "t": "float", "v": 0.75},
            },
        },
    },
}


class FakePa3(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        request = decode(data)
        body = json.loads(request.payload)
        assert body["protocol"] == "1.1"
        assert body["type"] == "global"
        response = CoapMessage(
            MessageType.ACK, 69, request.message_id, request.token,
            (CoapOption(OPTION_CONTENT_FORMAT, b"\x32"),),
            json.dumps(SNAPSHOT, separators=(",", ":")).encode(),
        )
        self.transport.sendto(encode(response), address)


def test_global_state_against_fake_udp_server() -> None:
    async def run() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            FakePa3, local_addr=("127.0.0.1", 0)
        )
        try:
            port = transport.get_extra_info("sockname")[1]
            async with Pa3Client("127.0.0.1", port=port) as client:
                state = await client.get_state()
                assert state.serial == "abc123"
                assert state.brightness.value == 0.5
                assert state.current_effect == "Mirage"
        finally:
            transport.close()

    asyncio.run(run())


class FakePa3Writes(asyncio.DatagramProtocol):
    def __init__(self):
        self.writes = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        request = decode(data)
        body = json.loads(request.payload)
        if body["type"] == "global":
            snapshot = deepcopy(SNAPSHOT)
            snapshot["payload"]["animations"] = [
                {"label": "Twinkle", "category": "*", "is_audio": False, "occasion": 0},
                {"label": "Leaf Swirl", "category": "fluora", "is_audio": False, "occasion": 0},
                {"label": "Mirage", "category": "*", "is_audio": False, "occasion": 0},
            ]
            snapshot["payload"]["engine"]["mode"]["v"] = 1
            payload = json.dumps(snapshot, separators=(",", ":")).encode()
            code = 69
            options = (CoapOption(OPTION_CONTENT_FORMAT, b"\x32"),)
        else:
            self.writes.append(body["payload"])
            payload = b""
            code = 68
            options = ()
        response = CoapMessage(
            MessageType.ACK, code, request.message_id, request.token,
            options, payload,
        )
        self.transport.sendto(encode(response), address)


def test_effect_switches_manual_mode_then_uses_original_index() -> None:
    async def run() -> None:
        loop = asyncio.get_running_loop()
        protocol = FakePa3Writes()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol, local_addr=("127.0.0.1", 0)
        )
        try:
            port = transport.get_extra_info("sockname")[1]
            async with Pa3Client("127.0.0.1", port=port) as client:
                await client.set_effect("Mirage", allow_write=True)
            assert protocol.writes == [
                {"id": "mode-id", "value": 2},
                {"id": "animation-id", "value": 2},
            ]
        finally:
            transport.close()

    asyncio.run(run())
