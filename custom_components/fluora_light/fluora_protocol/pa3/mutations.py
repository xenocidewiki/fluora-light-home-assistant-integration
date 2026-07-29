"""APK-verified PA3 mutation envelopes and wire messages.

This module only serializes recovered formats. Hardware transmission remains
explicitly gated by the client/CLI.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone

from .coap import CoapMessage, Method, make_request
from .models import Parameter


def _base(type_name: str, method: Method, request_id: int | None) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "protocol": "1.1",
        "type": type_name,
        "method": method.name,
        "timestamp": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "request_id": request_id if request_id is not None else int(now.timestamp() * 1000),
    }


def parameter_message(
    parameter_id: str,
    value: bool | int | float | str,
    *,
    request_id: int | None = None,
    final: bool = True,
    method: Method = Method.PUT,
) -> CoapMessage:
    if not parameter_id or parameter_id.startswith("/"):
        raise ValueError("parameter ID must be a non-empty device-issued ID")
    if method not in (Method.PUT, Method.POST):
        raise ValueError("APK supports PUT or POST for /parameter")
    body = _base("parameter", method, request_id)
    body["payload"] = {"id": parameter_id, "value": value}
    return make_request(
        method,
        "/parameter",
        random.randrange(0x10000),
        os.urandom(2),
        payload=json.dumps(body, separators=(",", ":")).encode(),
        confirmable=final if method is Method.PUT else True,
    )


def parameter_method(parameter_type: str, *, final: bool = True) -> Method:
    """Return the method selected by APK getCoAPParameterMethod."""

    normalized = parameter_type.lower()
    if normalized in {"string", "bool", "boolean", "int", "trigger"}:
        return Method.POST
    if normalized == "float":
        return Method.POST if final else Method.PUT
    return Method.POST if final else Method.PUT


def parameter_update(
    parameter: Parameter,
    value: bool | int | float | str,
    *,
    request_id: int | None = None,
    final: bool = True,
) -> CoapMessage:
    """Serialize an update using a device-issued descriptor."""

    if parameter.type.lower() in {"bool", "boolean"}:
        value = bool(value)
    return parameter_message(
        parameter.identifier,
        value,
        request_id=request_id,
        final=final,
        method=parameter_method(parameter.type, final=final),
    )


def command_message(command: str, *, request_id: int | None = None) -> CoapMessage:
    command = command.strip()
    if not command:
        raise ValueError("command must not be empty")
    body = _base("command", Method.POST, request_id)
    body["payload"] = {"command": command}
    return make_request(
        Method.POST,
        "/command",
        random.randrange(0x10000),
        os.urandom(2),
        payload=json.dumps(body, separators=(",", ":")).encode(),
        confirmable=True,
    )
