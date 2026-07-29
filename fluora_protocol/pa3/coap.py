"""Narrow, RFC 7252-compliant CoAP codec used by the PA3 client."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

from .constants import OPTION_OBSERVE, OPTION_URI_PATH


class MessageType(IntEnum):
    CON = 0
    NON = 1
    ACK = 2
    RST = 3


class Method(IntEnum):
    EMPTY = 0
    GET = 1
    POST = 2
    PUT = 3
    DELETE = 4


@dataclass(frozen=True, slots=True)
class CoapOption:
    number: int
    value: bytes

    def uint(self) -> int:
        return int.from_bytes(self.value, "big")


@dataclass(frozen=True, slots=True)
class CoapMessage:
    msg_type: MessageType
    code: int
    message_id: int
    token: bytes = b""
    options: tuple[CoapOption, ...] = ()
    payload: bytes = b""

    @property
    def code_text(self) -> str:
        return f"{self.code >> 5}.{self.code & 0x1f:02d}"

    def first_option(self, number: int) -> CoapOption | None:
        return next((item for item in self.options if item.number == number), None)


def uint_option(value: int) -> bytes:
    if value < 0:
        raise ValueError("uint option cannot be negative")
    if value == 0:
        return b""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def path_options(path: str) -> list[CoapOption]:
    return [
        CoapOption(OPTION_URI_PATH, segment.encode("utf-8"))
        for segment in path.split("/")
        if segment
    ]


def _encode_extended(value: int) -> tuple[int, bytes]:
    if value < 0:
        raise ValueError("options must be ordered by number")
    if value < 13:
        return value, b""
    if value < 269:
        return 13, bytes((value - 13,))
    if value < 65805:
        return 14, struct.pack("!H", value - 269)
    raise ValueError("option delta/length exceeds RFC 7252 encoding")


def encode(message: CoapMessage) -> bytes:
    if not 0 <= message.message_id <= 0xFFFF:
        raise ValueError("message ID must fit uint16")
    if len(message.token) > 8:
        raise ValueError("CoAP token is limited to 8 bytes")
    first = 0x40 | (int(message.msg_type) << 4) | len(message.token)
    out = bytearray((first, message.code))
    out.extend(struct.pack("!H", message.message_id))
    out.extend(message.token)
    previous = 0
    for option in sorted(message.options, key=lambda item: item.number):
        delta, delta_extra = _encode_extended(option.number - previous)
        length, length_extra = _encode_extended(len(option.value))
        out.append((delta << 4) | length)
        out.extend(delta_extra)
        out.extend(length_extra)
        out.extend(option.value)
        previous = option.number
    if message.payload:
        out.append(0xFF)
        out.extend(message.payload)
    return bytes(out)


def _decode_extended(nibble: int, data: bytes, offset: int) -> tuple[int, int]:
    if nibble < 13:
        return nibble, offset
    if nibble == 13:
        if offset >= len(data):
            raise ValueError("truncated extended option")
        return data[offset] + 13, offset + 1
    if nibble == 14:
        if offset + 2 > len(data):
            raise ValueError("truncated extended option")
        return struct.unpack_from("!H", data, offset)[0] + 269, offset + 2
    raise ValueError("reserved option nibble 15")


def decode(data: bytes) -> CoapMessage:
    if len(data) < 4:
        raise ValueError("CoAP message is shorter than four-byte header")
    first, code, message_id = struct.unpack_from("!BBH", data)
    if first >> 6 != 1:
        raise ValueError(f"unsupported CoAP version {first >> 6}")
    token_length = first & 0x0F
    if token_length > 8 or len(data) < 4 + token_length:
        raise ValueError("invalid or truncated token")
    offset = 4
    token = data[offset : offset + token_length]
    offset += token_length
    number = 0
    options: list[CoapOption] = []
    payload = b""
    while offset < len(data):
        initial = data[offset]
        offset += 1
        if initial == 0xFF:
            if offset == len(data):
                raise ValueError("payload marker without payload")
            payload = data[offset:]
            break
        delta, offset = _decode_extended(initial >> 4, data, offset)
        length, offset = _decode_extended(initial & 0x0F, data, offset)
        number += delta
        end = offset + length
        if end > len(data):
            raise ValueError("truncated option value")
        options.append(CoapOption(number, data[offset:end]))
        offset = end
    return CoapMessage(
        msg_type=MessageType((first >> 4) & 3),
        code=code,
        message_id=message_id,
        token=token,
        options=tuple(options),
        payload=payload,
    )


def make_request(
    method: Method,
    path: str,
    message_id: int,
    token: bytes,
    *,
    observe: int | None = None,
    options: Iterable[CoapOption] = (),
    payload: bytes = b"",
    confirmable: bool = True,
) -> CoapMessage:
    request_options = list(options)
    if observe is not None:
        request_options.append(CoapOption(OPTION_OBSERVE, uint_option(observe)))
    request_options.extend(path_options(path))
    return CoapMessage(
        MessageType.CON if confirmable else MessageType.NON,
        int(method),
        message_id,
        token,
        tuple(request_options),
        payload,
    )


def make_empty_ack(message_id: int) -> CoapMessage:
    return CoapMessage(MessageType.ACK, 0, message_id)

