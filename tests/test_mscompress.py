from __future__ import annotations

import pytest

from dosforge.errors import ValidationError
from dosforge.mscompress import compressed_variant_name, expand_dos_compressed_payload, expanded_name_from_compressed


def _encode_literal_lzss_stream(payload: bytes) -> bytes:
    encoded = bytearray()
    index = 0
    while index < len(payload):
        chunk = payload[index : index + 8]
        control = (1 << len(chunk)) - 1
        encoded.append(control)
        encoded.extend(chunk)
        index += len(chunk)
    return bytes(encoded)


def test_expanded_name_from_compressed_maps_known_extensions() -> None:
    assert expanded_name_from_compressed("SUBST.EX_") == "SUBST.EXE"
    assert expanded_name_from_compressed("MODE.CO_") == "MODE.COM"
    assert expanded_name_from_compressed("README.TX_") == "README.TXT"
    assert expanded_name_from_compressed("UNKNOWN.BIN") is None


def test_compressed_variant_name_maps_known_extensions() -> None:
    assert compressed_variant_name("SUBST.EXE") == "SUBST.EX_"
    assert compressed_variant_name("MODE.COM") == "MODE.CO_"
    assert compressed_variant_name("README.TXT") == "README.TX_"
    assert compressed_variant_name("UNKNOWN.BIN") is None


def test_expand_dos_compressed_payload_supports_szdd_literal_stream() -> None:
    source = b"ABC"
    compressed_stream = _encode_literal_lzss_stream(source)
    header = b"SZDD\x88\xF0'3" + bytes([0x41, 0x00]) + len(source).to_bytes(4, "little")
    assert expand_dos_compressed_payload(header + compressed_stream) == source


def test_expand_dos_compressed_payload_supports_kwaj_szdd_literal_stream() -> None:
    source = b"HELLO"
    compressed_stream = _encode_literal_lzss_stream(source)
    header = b"KWAJ\x88\xF0'\xD1" + (2).to_bytes(2, "little") + (14).to_bytes(2, "little") + (0).to_bytes(2, "little")
    assert expand_dos_compressed_payload(header + compressed_stream) == source


def test_expand_dos_compressed_payload_rejects_unknown_format() -> None:
    with pytest.raises(ValidationError, match="Unsupported DOS compressed payload format"):
        expand_dos_compressed_payload(b"not-a-compressed-file")
