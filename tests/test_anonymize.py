from __future__ import annotations

from urllib.parse import urlparse

from uiprotect.test_util.anonymize import anonymize_data

_STREAMS = {
    "high": "rtsps://192.168.1.10:7441/abcdef123456?enableSrtp",
    "medium": "rtsps://192.168.1.10:7441/secretmediumalias",
    "package": "rtsps://192.168.1.10:7441/packagealias",
}


def test_rtsps_streams_dict_anonymized() -> None:
    result = anonymize_data({"rtspsStreams": dict(_STREAMS)}, name="camera")[
        "rtspsStreams"
    ]

    assert set(result) == set(_STREAMS)
    for quality, url in result.items():
        assert url != _STREAMS[quality]
        parts = urlparse(url)
        assert parts.scheme == "rtsps"
        assert "192.168.1.10" not in url
        assert parts.path.lstrip("/") not in _STREAMS[quality]


def test_rtsps_streams_within_public_camera_dump() -> None:
    dump = {
        "modelKey": "camera",
        "id": "aabbccddeeff00112233",
        "rtspsStreams": dict(_STREAMS),
    }

    result = anonymize_data(dump)

    for quality, url in result["rtspsStreams"].items():
        assert url != _STREAMS[quality]
        assert "192.168.1.10" not in url


def test_rtsps_streams_list_anonymized() -> None:
    result = anonymize_data(list(_STREAMS.values()), name="rtspsStreams")

    for original, url in zip(_STREAMS.values(), result, strict=True):
        assert url != original
        assert "192.168.1.10" not in url
        assert urlparse(url).scheme == "rtsps"


def test_rtsps_streams_preserves_non_string_values() -> None:
    result = anonymize_data(
        {"rtspsStreams": {"high": None, "enabled": True}}, name="camera"
    )

    assert result["rtspsStreams"] == {"high": None, "enabled": True}
