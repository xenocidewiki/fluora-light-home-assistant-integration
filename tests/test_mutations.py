import json

from fluora_protocol.pa3.coap import MessageType, Method, decode, encode
from fluora_protocol.pa3.models import Parameter
from fluora_protocol.pa3.mutations import (
    command_message,
    parameter_message,
    parameter_method,
    parameter_update,
)


def test_power_parameter_envelope() -> None:
    message = parameter_message("phnzVG", False, request_id=123, final=True)
    decoded = decode(encode(message))
    assert decoded.msg_type is MessageType.CON
    assert decoded.code == Method.PUT
    assert [option.value for option in decoded.options] == [b"parameter"]
    body = json.loads(decoded.payload)
    assert body["protocol"] == "1.1"
    assert body["type"] == "parameter"
    assert body["method"] == "PUT"
    assert body["request_id"] == 123
    assert body["payload"] == {"id": "phnzVG", "value": False}


def test_intermediate_parameter_is_nonconfirmable() -> None:
    assert parameter_message("vChKsv", 0.5, final=False).msg_type is MessageType.NON


def test_command_envelope() -> None:
    message = command_message("example", request_id=456)
    assert message.msg_type is MessageType.CON
    assert message.code == Method.POST
    assert json.loads(message.payload)["payload"] == {"command": "example"}


def test_apk_parameter_method_routing() -> None:
    assert parameter_method("bool") is Method.POST
    assert parameter_method("int", final=False) is Method.POST
    assert parameter_method("float", final=False) is Method.PUT
    assert parameter_method("float", final=True) is Method.POST


def test_parameter_update_uses_device_descriptor() -> None:
    message = parameter_update(
        Parameter("phnzVG", "bool", True), 0, request_id=123
    )
    assert message.code == Method.POST
    assert message.msg_type is MessageType.CON
    body = json.loads(message.payload)
    assert body["payload"] == {"id": "phnzVG", "value": False}
