"""Async UDP CoAP client for read-only PA3 investigation."""

from __future__ import annotations

import asyncio
import json
import os
import random
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from .coap import (
    CoapMessage,
    CoapOption,
    MessageType,
    Method,
    decode,
    encode,
    make_empty_ack,
    make_request,
)
from .constants import (
    COAP_PORT,
    CONTENT_FORMATS,
    OPTION_BLOCK2,
    OPTION_CONTENT_FORMAT,
    OPTION_OBSERVE,
)
from .models import Pa3State, Parameter
from .mutations import parameter_update


@dataclass(frozen=True, slots=True)
class Pa3Response:
    message: CoapMessage
    raw: bytes
    peer: tuple[str, int]

    @property
    def content_format(self) -> int | None:
        option = self.message.first_option(OPTION_CONTENT_FORMAT)
        return option.uint() if option else None

    @property
    def content_type(self) -> str | None:
        value = self.content_format
        return CONTENT_FORMATS.get(value, f"unknown/{value}") if value is not None else None

    def decoded_payload(self) -> object:
        if not self.message.payload:
            return None
        if self.content_format == 50:
            return json.loads(self.message.payload)
        try:
            return self.message.payload.decode("utf-8")
        except UnicodeDecodeError:
            return self.message.payload


class Pa3ProtocolError(RuntimeError):
    """A PA3 endpoint returned a non-successful CoAP response."""


class Pa3Client:
    """Small CoAP client with retransmission, correlation, ACK, and Observe."""

    def __init__(
        self,
        host: str,
        port: int = COAP_PORT,
        *,
        ack_timeout: float = 2.0,
        max_retransmit: int = 4,
    ) -> None:
        self.host = host
        self.port = port
        self.ack_timeout = ack_timeout
        self.max_retransmit = max_retransmit
        self._socket: socket.socket | None = None
        self._seen: set[tuple[str, int, int]] = set()

    async def __aenter__(self) -> Pa3Client:
        self._ensure_socket()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()

    def _ensure_socket(self) -> socket.socket:
        if self._socket is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("", 0))
            sock.connect((self.host, self.port))
            sock.setblocking(False)
            self._socket = sock
        return self._socket

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._seen.clear()

    async def get(self, path: str, *, timeout: float | None = None) -> Pa3Response:
        request = make_request(
            Method.GET,
            path,
            random.randrange(0x10000),
            os.urandom(4),
        )
        return await self._exchange(request, timeout=timeout)

    async def get_json_body(
        self, path: str, body: dict[str, object], *, block_size_exponent: int = 6
    ) -> Pa3Response:
        """GET with an APK-compatible JSON body and assemble Block2 responses."""

        payload = json.dumps(body, separators=(",", ":")).encode()
        chunks: list[bytes] = []
        block_number = 0
        last_response: Pa3Response | None = None
        while True:
            block_value = (block_number << 4) | block_size_exponent
            request = make_request(
                Method.GET,
                path,
                random.randrange(0x10000),
                os.urandom(2),
                options=(CoapOption(OPTION_BLOCK2, block_value.to_bytes(
                    max(1, (block_value.bit_length() + 7) // 8), "big"
                )),),
                payload=payload,
            )
            response = await self._exchange(request)
            chunks.append(response.message.payload)
            last_response = response
            block = response.message.first_option(OPTION_BLOCK2)
            if block is None or not (block.uint() & 0x08):
                break
            block_number = (block.uint() >> 4) + 1
        assert last_response is not None
        combined = b"".join(chunks)
        message = CoapMessage(
            last_response.message.msg_type,
            last_response.message.code,
            last_response.message.message_id,
            last_response.message.token,
            tuple(
                option
                for option in last_response.message.options
                if option.number != OPTION_BLOCK2
            ),
            combined,
        )
        return Pa3Response(message, last_response.raw, last_response.peer)

    async def get_global(self, request_id: int | None = None) -> Pa3Response:
        """Fetch the PA3 global snapshot using the exact APK request envelope."""

        now = datetime.now(timezone.utc)
        body = {
            "protocol": "1.1",
            "type": "global",
            "method": "GET",
            "timestamp": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "request_id": request_id if request_id is not None else int(now.timestamp() * 1000),
        }
        return await self.get_json_body("/global", body)

    async def get_state(self) -> Pa3State:
        response = await self.get_global()
        decoded = response.decoded_payload()
        if not isinstance(decoded, dict):
            raise ValueError("PA3 global response was not JSON")
        return Pa3State.from_snapshot(decoded)

    async def update_parameter(
        self,
        parameter: Parameter,
        value: bool | int | float | str,
        *,
        allow_write: bool = False,
        final: bool = True,
    ) -> Pa3Response:
        if not allow_write:
            raise PermissionError("PA3 writes require allow_write=True")
        response = await self._exchange(
            parameter_update(parameter, value, final=final)
        )
        if response.message.code >> 5 != 2:
            detail = response.decoded_payload()
            raise Pa3ProtocolError(
                f"/parameter returned {response.message.code_text}: {detail!r}"
            )
        return response

    async def set_power(self, enabled: bool, *, allow_write: bool = False) -> Pa3Response:
        state = await self.get_state()
        return await self.update_parameter(state.power, enabled, allow_write=allow_write)

    async def set_brightness(
        self, value: float, *, allow_write: bool = False
    ) -> Pa3Response:
        if not 0.0 <= value <= 1.0:
            raise ValueError("brightness must be between 0.0 and 1.0")
        state = await self.get_state()
        return await self.update_parameter(
            state.brightness, value, allow_write=allow_write
        )

    async def set_hs_color(
        self, hue: float, saturation: float, *, allow_write: bool = False
    ) -> tuple[Pa3Response, ...]:
        if not 0.0 <= hue <= 360.0:
            raise ValueError("hue must be between 0 and 360 degrees")
        if not 0.0 <= saturation <= 100.0:
            raise ValueError("saturation must be between 0 and 100 percent")
        state = await self.get_state()
        if state.hue is None or state.saturation is None:
            raise RuntimeError("manual color routes are absent from the snapshot")
        responses: list[Pa3Response] = []
        if int(state.mode.value) != 2:
            responses.append(
                await self.update_parameter(
                    state.mode, 2, allow_write=allow_write
                )
            )
            await asyncio.sleep(0.5)
        responses.append(await self.update_parameter(
            state.hue, hue / 360.0, allow_write=allow_write
        ))
        responses.append(await self.update_parameter(
            state.saturation, saturation / 100.0, allow_write=allow_write
        ))
        return tuple(responses)

    async def set_effect(
        self, effect: str, *, allow_write: bool = False
    ) -> tuple[Pa3Response, ...]:
        """Select Auto, a scene, or a zero-based manual animation."""

        state = await self.get_state()
        responses: list[Pa3Response] = []
        if effect == "Auto":
            return (
                await self.update_parameter(
                    state.mode, 0, allow_write=allow_write
                ),
            )
        if effect.startswith("Scene: "):
            label = effect.removeprefix("Scene: ")
            try:
                index = state.scenes.index(label)
            except ValueError as error:
                raise ValueError(f"unknown scene: {label}") from error
            if int(state.mode.value) != 1:
                responses.append(
                    await self.update_parameter(
                        state.mode, 1, allow_write=allow_write
                    )
                )
                await asyncio.sleep(0.5)
            responses.append(
                await self.update_parameter(
                    state.active_scene_index, index, allow_write=allow_write
                )
            )
            return tuple(responses)
        match = next((item for item in state.effects if item.label == effect), None)
        if match is None:
            raise ValueError(f"unknown animation: {effect}")
        if state.manual_animation_index is None:
            raise RuntimeError("manual animation route is absent from the snapshot")
        if int(state.mode.value) != 2:
            responses.append(
                await self.update_parameter(
                    state.mode, 2, allow_write=allow_write
                )
            )
            await asyncio.sleep(0.5)
        responses.append(
            await self.update_parameter(
                state.manual_animation_index,
                match.index,
                allow_write=allow_write,
            )
        )
        return tuple(responses)

    async def get_domain(
        self, domain: str, request_id: int | None = None
    ) -> Pa3Response:
        """Fetch one state domain using the exact APK request envelope."""

        now = datetime.now(timezone.utc)
        body = {
            "protocol": "1.1",
            "type": "domain",
            "method": "GET",
            "domain": domain,
            "timestamp": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "request_id": request_id if request_id is not None else int(now.timestamp() * 1000),
        }
        return await self.get_json_body("/domain", body)

    async def _exchange(
        self, request: CoapMessage, *, timeout: float | None = None
    ) -> Pa3Response:
        loop = asyncio.get_running_loop()
        sock = self._ensure_socket()
        wire = encode(request)
        retransmit_timeout = timeout or self.ack_timeout
        attempts = self.max_retransmit + 1 if request.msg_type == MessageType.CON else 1
        for attempt in range(attempts):
            sock.send(wire)
            deadline = loop.time() + retransmit_timeout
            while (remaining := deadline - loop.time()) > 0:
                try:
                    raw = await asyncio.wait_for(loop.sock_recv(sock, 65535), remaining)
                    peer = (self.host, self.port)
                except (TimeoutError, asyncio.TimeoutError):
                    break
                message = decode(raw)
                if message.token != request.token:
                    continue
                if message.msg_type == MessageType.CON:
                    sock.send(encode(make_empty_ack(message.message_id)))
                return Pa3Response(message, raw, peer)
            retransmit_timeout *= 2
        raise TimeoutError(
            f"no response from {self.host}:{self.port} after {attempts} attempt(s)"
        )

    async def observe(
        self,
        path: str,
        *,
        duration: float | None = None,
    ) -> AsyncIterator[Pa3Response]:
        """Register Observe=0 and yield correlated, duplicate-filtered notifications."""

        loop = asyncio.get_running_loop()
        sock = self._ensure_socket()
        token = os.urandom(4)
        request = make_request(Method.GET, path, random.randrange(0x10000), token, observe=0)
        sock.send(encode(request))
        deadline = loop.time() + duration if duration is not None else None
        while deadline is None or (remaining := deadline - loop.time()) > 0:
            wait = remaining if deadline is not None else None
            try:
                raw = await asyncio.wait_for(loop.sock_recv(sock, 65535), wait)
                peer = (self.host, self.port)
            except (TimeoutError, asyncio.TimeoutError):
                return
            message = decode(raw)
            if message.token != token:
                continue
            duplicate_key = (peer[0], peer[1], message.message_id)
            if message.msg_type == MessageType.CON:
                sock.send(encode(make_empty_ack(message.message_id)))
            if duplicate_key in self._seen:
                continue
            self._seen.add(duplicate_key)
            yield Pa3Response(message, raw, peer)
            if message.code >> 5 != 2 or message.first_option(OPTION_OBSERVE) is None:
                return
