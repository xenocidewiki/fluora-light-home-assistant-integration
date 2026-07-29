from fluora_protocol.pa3.coap import (
    CoapMessage,
    CoapOption,
    MessageType,
    Method,
    decode,
    encode,
    make_empty_ack,
    make_request,
)


CORE_REQUEST = bytes.fromhex(
    "4401a9fcfd2687ecbb2e77656c6c2d6b6e6f776e04636f72656132"
)
CORE_RESPONSE = bytes.fromhex(
    "6445a9fcfd2687ecc128ff3c2f646973636f766572793e2c3c2f70696e673e2c"
    "3c2f646f6d61696e3e2c3c2f676c6f62616c3e2c3c2f7363686564756c653e2c"
    "3c2f706172616d657465723e2c3c2f636f6d6d616e643e2c3c2f726576697369"
    "6f6e733e3b6f62732c3c2f64656c7461733e3b6f6273"
)


def test_capture_request_round_trip() -> None:
    message = decode(CORE_REQUEST)
    assert message.msg_type is MessageType.CON
    assert message.code == Method.GET
    assert message.message_id == 0xA9FC
    assert message.token == bytes.fromhex("fd2687ec")
    assert [item.value for item in message.options if item.number == 11] == [
        b".well-known",
        b"core",
    ]
    assert encode(message) == CORE_REQUEST


def test_capture_response_round_trip() -> None:
    message = decode(CORE_RESPONSE)
    assert message.code_text == "2.05"
    assert message.first_option(12) == CoapOption(12, b"\x28")
    assert message.payload.startswith(b"</discovery>")
    assert encode(message) == CORE_RESPONSE


def test_extended_option_delta_and_length() -> None:
    message = CoapMessage(
        MessageType.CON,
        Method.GET,
        123,
        b"12345678",
        (CoapOption(300, b"x" * 300),),
    )
    assert decode(encode(message)) == message


def test_observe_zero_uses_empty_uint() -> None:
    message = make_request(Method.GET, "/deltas", 1, b"ab", observe=0)
    assert message.first_option(6) == CoapOption(6, b"")


def test_empty_ack_exact_bytes() -> None:
    assert encode(make_empty_ack(0x1234)) == bytes.fromhex("60001234")

