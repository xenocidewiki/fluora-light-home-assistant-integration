"""CoAP and PA3 constants."""

COAP_PORT = 5683
RESOURCE_DIRECTORY = "/.well-known/core"
READ_RESOURCES = (
    "/discovery",
    "/ping",
    "/domain",
    "/global",
    "/schedule",
    "/parameter",
    "/command",
    "/revisions",
    "/deltas",
)
OBSERVABLE_RESOURCES = ("/revisions", "/deltas")

OPTION_OBSERVE = 6
OPTION_URI_PATH = 11
OPTION_CONTENT_FORMAT = 12
OPTION_MAX_AGE = 14
OPTION_ACCEPT = 17
OPTION_BLOCK2 = 23

CONTENT_FORMATS = {
    0: "text/plain; charset=utf-8",
    40: "application/link-format",
    42: "application/octet-stream",
    50: "application/json",
    60: "application/cbor",
}

