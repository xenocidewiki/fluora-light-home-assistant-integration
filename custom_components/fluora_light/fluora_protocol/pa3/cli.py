"""Diagnostic CLI for PA-CoAP-1.0 devices; writes are explicitly gated."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone

from ..discovery import discover_pa3
from .client import Pa3Client, Pa3Response
from .constants import OBSERVABLE_RESOURCES, READ_RESOURCES, RESOURCE_DIRECTORY


def _report(path: str, response: Pa3Response) -> dict[str, object]:
    message = response.message
    decoded = response.decoded_payload()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoint": f"{response.peer[0]}:{response.peer[1]}",
        "method": "GET",
        "path": path,
        "code": message.code_text,
        "type": message.msg_type.name,
        "message_id": message.message_id,
        "token_hex": message.token.hex(),
        "options": [
            {"number": item.number, "value_hex": item.value.hex()}
            for item in message.options
        ],
        "content_format": response.content_format,
        "content_type": response.content_type,
        "payload_hex": message.payload.hex(),
        "decoded_payload": (
            {"binary_hex": decoded.hex()} if isinstance(decoded, bytes) else decoded
        ),
    }


async def _run(args: argparse.Namespace) -> None:
    host = args.host
    if not host:
        devices = await discover_pa3(args.discovery_timeout)
        if not devices:
            raise SystemExit("No PA-CoAP-1.0 broadcast received")
        for item in devices:
            print(json.dumps({"discovered": asdict(item)}, default=str))
        host = devices[0].ip_address

    async with Pa3Client(
        host,
        port=args.port,
        ack_timeout=args.timeout,
        max_retransmit=args.retransmit,
    ) as client:
        if args.action == "probe":
            paths = (RESOURCE_DIRECTORY, *READ_RESOURCES)
            for path in paths:
                try:
                    response = await client.get(path)
                    print(json.dumps(_report(path, response), indent=2))
                except TimeoutError as error:
                    print(json.dumps({"path": path, "error": str(error)}, indent=2))
        elif args.action == "state":
            response = await client.get_global()
            print(json.dumps(_report("/global", response), indent=2))
        elif args.action == "observe":
            paths = (args.resource,) if args.resource else OBSERVABLE_RESOURCES
            # Observe one resource per socket so notification streams cannot starve.
            for path in paths:
                async with Pa3Client(host, port=args.port) as observer:
                    async for response in observer.observe(path, duration=args.seconds):
                        print(json.dumps(_report(path, response), indent=2))
        elif args.action == "power":
            response = await client.set_power(args.on, allow_write=args.allow_write)
            print(json.dumps(_report("/parameter", response), indent=2))
        elif args.action == "brightness":
            response = await client.set_brightness(
                args.value, allow_write=args.allow_write
            )
            print(json.dumps(_report("/parameter", response), indent=2))
        elif args.action == "color":
            for response in await client.set_hs_color(
                args.hue, args.saturation, allow_write=args.allow_write
            ):
                print(json.dumps(_report("/parameter", response), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fluora-pa3")
    parser.add_argument(
        "action",
        choices=("probe", "state", "observe", "power", "brightness", "color"),
    )
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=5683)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--retransmit", type=int, default=2)
    parser.add_argument("--discovery-timeout", type=float, default=8.0)
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--resource", choices=("/revisions", "/deltas"))
    parser.add_argument("--allow-write", action="store_true")
    power = parser.add_mutually_exclusive_group()
    power.add_argument("--on", action="store_true")
    power.add_argument("--off", dest="on", action="store_false")
    parser.set_defaults(on=True)
    parser.add_argument("--value", type=float)
    parser.add_argument("--hue", type=float)
    parser.add_argument("--saturation", type=float)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.action in {"power", "brightness", "color"} and not args.allow_write:
        raise SystemExit("Refusing device mutation without --allow-write")
    if args.action == "brightness" and args.value is None:
        raise SystemExit("brightness requires --value")
    if args.action == "color" and (args.hue is None or args.saturation is None):
        raise SystemExit("color requires --hue and --saturation")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
