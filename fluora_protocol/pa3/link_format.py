"""Minimal RFC 6690 CoRE Link Format parser."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ResourceLink:
    target: str
    attributes: dict[str, str | None] = field(default_factory=dict)


def parse_link_format(payload: bytes | str) -> list[ResourceLink]:
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    links: list[ResourceLink] = []
    for raw_link in _split_quoted(text, ","):
        parts = _split_quoted(raw_link.strip(), ";")
        target = parts[0].strip()
        if len(target) < 2 or target[0] != "<" or target[-1] != ">":
            raise ValueError(f"invalid link target: {target!r}")
        attributes: dict[str, str | None] = {}
        for part in parts[1:]:
            name, separator, value = part.strip().partition("=")
            attributes[name] = (
                value[1:-1] if separator and value.startswith('"') and value.endswith('"')
                else value if separator
                else None
            )
        links.append(ResourceLink(target[1:-1], attributes))
    return links


def _split_quoted(value: str, delimiter: str) -> list[str]:
    result: list[str] = []
    start = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == delimiter and not quoted:
            result.append(value[start:index])
            start = index + 1
    if quoted:
        raise ValueError("unterminated quoted string")
    result.append(value[start:])
    return result

