from fluora_protocol.pa3.link_format import parse_link_format


CAPTURE = (
    "</discovery>,</ping>,</domain>,</global>,</schedule>,</parameter>,"
    "</command>,</revisions>;obs,</deltas>;obs"
)


def test_captured_resource_directory() -> None:
    resources = parse_link_format(CAPTURE)
    assert [item.target for item in resources] == [
        "/discovery",
        "/ping",
        "/domain",
        "/global",
        "/schedule",
        "/parameter",
        "/command",
        "/revisions",
        "/deltas",
    ]
    assert resources[-2].attributes == {"obs": None}
    assert resources[-1].attributes == {"obs": None}


def test_quoted_delimiters_are_not_split() -> None:
    resource = parse_link_format('</x>;title="a,b;c";ct=50')[0]
    assert resource.attributes == {"title": "a,b;c", "ct": "50"}

