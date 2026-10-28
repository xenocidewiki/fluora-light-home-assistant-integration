"""Polling and service calls must not compete for one UDP socket."""

import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

from fluora_protocol.pa3.client import Pa3Client
from fluora_protocol.pa3.coap import CoapMessage, MessageType, decode, encode


class DelayedServer(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, raw, peer):
        request = decode(raw)
        reply = CoapMessage(
            MessageType.ACK, 69, request.message_id, request.token, (), b"pong"
        )
        asyncio.get_running_loop().call_later(
            0.01, self.transport.sendto, encode(reply), peer
        )


def _check_concurrent_requests(client_type) -> None:
    async def run():
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            DelayedServer, local_addr=("127.0.0.1", 0)
        )
        try:
            port = transport.get_extra_info("sockname")[1]
            async with client_type(
                "127.0.0.1", port=port, ack_timeout=0.2, max_retransmit=0
            ) as client:
                results = await asyncio.gather(client.get("/ping"), client.get("/ping"))
                assert [result.message.payload for result in results] == [b"pong", b"pong"]
        finally:
            transport.close()

    asyncio.run(run())


def test_concurrent_requests_keep_their_responses() -> None:
    _check_concurrent_requests(Pa3Client)


def test_bundled_client_keeps_concurrent_responses() -> None:
    # Exercise the copy shipped to HA without importing Home Assistant itself.
    package = ModuleType("_fluora_bundled_protocol")
    package.__path__ = [str(
        Path(__file__).resolve().parents[1]
        / "custom_components/fluora_light/fluora_protocol"
    )]
    with patch.dict(sys.modules, {package.__name__: package}):
        bundled = importlib.import_module(f"{package.__name__}.pa3.client")
        _check_concurrent_requests(bundled.Pa3Client)
