"""Utilities for expanding legacy DOS compressed payload files."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError

_SZDD_SIGNATURE_NORMAL = b"SZDD\x88\xF0'3"
_SZDD_SIGNATURE_QBASIC = b"SZ \x88\xF0'3\xD1"
_KWAJ_SIGNATURE_PRIMARY = b"KWAJ"
_KWAJ_SIGNATURE_SECONDARY = b"\x88\xF0'\xD1"

_KWAJ_COMP_NONE = 0
_KWAJ_COMP_XOR = 1
_KWAJ_COMP_SZDD = 2
_KWAJ_COMP_LZH = 3

_KWAJ_TABLE_BITS = 9
_KWAJ_MAX_BITS = 16
_KWAJ_MATCHLEN1_SYMS = 16
_KWAJ_MATCHLEN2_SYMS = 16
_KWAJ_LITLEN_SYMS = 32
_KWAJ_OFFSET_SYMS = 64
_KWAJ_LITERAL_SYMS = 256

_DOS_COMPRESSED_EXTENSION_MAP: dict[str, str] = {
    "38_": "386",
    "BA_": "BAT",
    "CO_": "COM",
    "CP_": "CPI",
    "DL_": "DLL",
    "DO_": "DOS",
    "EX_": "EXE",
    "HL_": "HLP",
    "IN_": "INI",
    "OV_": "OVL",
    "SY_": "SYS",
    "TX_": "TXT",
}
_DOS_UNCOMPRESSED_EXTENSION_MAP: dict[str, str] = {
    uncompressed: compressed
    for compressed, uncompressed in _DOS_COMPRESSED_EXTENSION_MAP.items()
}


def expanded_name_from_compressed(file_name: str) -> str | None:
    stem, dot, extension = file_name.rpartition(".")
    if not dot:
        return None
    target_extension = _DOS_COMPRESSED_EXTENSION_MAP.get(extension.upper())
    if target_extension is None:
        return None
    return f"{stem}.{target_extension}"


def compressed_variant_name(file_name: str) -> str | None:
    stem, dot, extension = file_name.rpartition(".")
    if not dot:
        return None
    compressed_extension = _DOS_UNCOMPRESSED_EXTENSION_MAP.get(extension.upper())
    if compressed_extension is None:
        return None
    return f"{stem}.{compressed_extension}"


def expand_dos_compressed_payload(payload: bytes) -> bytes:
    if payload.startswith(_SZDD_SIGNATURE_NORMAL):
        return _expand_szdd(payload, qbasic=False)
    if payload.startswith(_SZDD_SIGNATURE_QBASIC):
        return _expand_szdd(payload, qbasic=True)
    if payload.startswith(_KWAJ_SIGNATURE_PRIMARY) and payload[4:8] == _KWAJ_SIGNATURE_SECONDARY:
        return _expand_kwaj(payload)
    raise ValidationError("Unsupported DOS compressed payload format.")


def _expand_szdd(payload: bytes, *, qbasic: bool) -> bytes:
    header_size = 12 if qbasic else 14
    if len(payload) < header_size:
        raise ValidationError("SZDD payload is truncated.")
    if not qbasic and payload[8] != 0x41:
        raise ValidationError("Unsupported SZDD header variant.")
    return _expand_lzss_stream(payload[header_size:], qbasic=qbasic)


def _expand_kwaj(payload: bytes) -> bytes:
    if len(payload) < 14:
        raise ValidationError("KWAJ payload is truncated.")
    comp_type = int.from_bytes(payload[8:10], "little")
    data_offset = int.from_bytes(payload[10:12], "little")
    if data_offset < 14 or data_offset > len(payload):
        raise ValidationError("KWAJ payload has invalid data offset.")
    compressed = payload[data_offset:]
    if comp_type == _KWAJ_COMP_NONE:
        return compressed
    if comp_type == _KWAJ_COMP_XOR:
        return bytes(value ^ 0xFF for value in compressed)
    if comp_type == _KWAJ_COMP_SZDD:
        return _expand_lzss_stream(compressed, qbasic=True)
    if comp_type == _KWAJ_COMP_LZH:
        return _expand_kwaj_lzh_stream(compressed)
    raise ValidationError(f"Unsupported KWAJ compression method: {comp_type}")


def _expand_lzss_stream(data: bytes, *, qbasic: bool) -> bytes:
    window = bytearray(b" " * 4096)
    output = bytearray()
    position = 4096 - (18 if qbasic else 16)
    index = 0
    while index < len(data):
        control = data[index]
        index += 1
        bit = 1
        while bit <= 0x80:
            if control & bit:
                if index >= len(data):
                    return bytes(output)
                literal = data[index]
                index += 1
                window[position] = literal
                output.append(literal)
                position = (position + 1) & 0x0FFF
            else:
                if index + 1 >= len(data):
                    return bytes(output)
                match_pos = data[index]
                index += 1
                descriptor = data[index]
                index += 1
                match_pos |= (descriptor & 0xF0) << 4
                match_len = (descriptor & 0x0F) + 3
                for _ in range(match_len):
                    value = window[match_pos]
                    window[position] = value
                    output.append(value)
                    position = (position + 1) & 0x0FFF
                    match_pos = (match_pos + 1) & 0x0FFF
            bit <<= 1
    return bytes(output)


class _KwajStreamEnd(Exception):
    """Raised when KWAJ stream reads beyond available compressed payload."""


@dataclass(slots=True)
class _KwajBitReader:
    payload: bytes
    index: int = 0
    bit_buffer: int = 0
    bits_left: int = 0
    fake_bits: int = 0

    def read_bits_safe(self, count: int) -> int:
        self._ensure(count)
        value = self.bit_buffer >> (32 - count)
        self.bit_buffer = (self.bit_buffer << count) & 0xFFFFFFFF
        self.bits_left -= count
        if self.fake_bits and self.bits_left < self.fake_bits:
            raise _KwajStreamEnd()
        return value

    def read_huffman_symbol(
        self,
        *,
        table: list[int],
        lengths: list[int],
        symbol_count: int,
    ) -> int:
        self._ensure(_KWAJ_MAX_BITS)
        symbol = table[self.bit_buffer >> (32 - _KWAJ_TABLE_BITS)]
        if symbol >= symbol_count:
            traverse_mask = 1 << (32 - _KWAJ_TABLE_BITS)
            while symbol >= symbol_count:
                traverse_mask >>= 1
                if traverse_mask == 0:
                    raise ValidationError("Invalid KWAJ Huffman table traversal.")
                table_index = (symbol << 1) | (1 if (self.bit_buffer & traverse_mask) else 0)
                if table_index >= len(table):
                    raise ValidationError("Corrupt KWAJ Huffman stream.")
                symbol = table[table_index]

        bit_count = lengths[symbol]
        if bit_count <= 0:
            raise ValidationError("Invalid KWAJ Huffman code length.")
        self.bit_buffer = (self.bit_buffer << bit_count) & 0xFFFFFFFF
        self.bits_left -= bit_count
        if self.fake_bits and self.bits_left < self.fake_bits:
            raise _KwajStreamEnd()
        return symbol

    def _ensure(self, count: int) -> None:
        while self.bits_left < count:
            if self.index < len(self.payload):
                value = self.payload[self.index]
                self.index += 1
            else:
                self.fake_bits += 8
                value = 0
            self.bit_buffer |= value << (32 - 8 - self.bits_left)
            self.bits_left += 8


def _expand_kwaj_lzh_stream(data: bytes) -> bytes:
    reader = _KwajBitReader(data)
    window = bytearray(b" " * 4096)
    output = bytearray()
    position = 0

    try:
        encoding_types = [reader.read_bits_safe(4) for _ in range(6)]
    except _KwajStreamEnd:
        return b""

    matchlen1_lengths = _read_kwaj_lens(reader, encoding_types[0], _KWAJ_MATCHLEN1_SYMS)
    matchlen2_lengths = _read_kwaj_lens(reader, encoding_types[1], _KWAJ_MATCHLEN2_SYMS)
    litlen_lengths = _read_kwaj_lens(reader, encoding_types[2], _KWAJ_LITLEN_SYMS)
    offset_lengths = _read_kwaj_lens(reader, encoding_types[3], _KWAJ_OFFSET_SYMS)
    literal_lengths = _read_kwaj_lens(reader, encoding_types[4], _KWAJ_LITERAL_SYMS)

    matchlen1_table = _make_kwaj_decode_table(matchlen1_lengths, _KWAJ_TABLE_BITS)
    matchlen2_table = _make_kwaj_decode_table(matchlen2_lengths, _KWAJ_TABLE_BITS)
    litlen_table = _make_kwaj_decode_table(litlen_lengths, _KWAJ_TABLE_BITS)
    offset_table = _make_kwaj_decode_table(offset_lengths, _KWAJ_TABLE_BITS)
    literal_table = _make_kwaj_decode_table(literal_lengths, _KWAJ_TABLE_BITS)

    literal_run = 0
    while True:
        try:
            if literal_run:
                match_len_symbol = reader.read_huffman_symbol(
                    table=matchlen2_table,
                    lengths=matchlen2_lengths,
                    symbol_count=_KWAJ_MATCHLEN2_SYMS,
                )
            else:
                match_len_symbol = reader.read_huffman_symbol(
                    table=matchlen1_table,
                    lengths=matchlen1_lengths,
                    symbol_count=_KWAJ_MATCHLEN1_SYMS,
                )
        except _KwajStreamEnd:
            break

        if match_len_symbol > 0:
            match_length = match_len_symbol + 2
            literal_run = 0
            try:
                offset_high = reader.read_huffman_symbol(
                    table=offset_table,
                    lengths=offset_lengths,
                    symbol_count=_KWAJ_OFFSET_SYMS,
                )
                offset_low = reader.read_bits_safe(6)
            except _KwajStreamEnd:
                break
            offset = (offset_high << 6) | offset_low
            for _ in range(match_length):
                value = window[(position + 4096 - offset) & 0x0FFF]
                window[position] = value
                output.append(value)
                position = (position + 1) & 0x0FFF
            continue

        try:
            literal_count = reader.read_huffman_symbol(
                table=litlen_table,
                lengths=litlen_lengths,
                symbol_count=_KWAJ_LITLEN_SYMS,
            )
        except _KwajStreamEnd:
            break
        literal_count += 1
        literal_run = 0 if literal_count == 32 else 1
        for _ in range(literal_count):
            try:
                literal = reader.read_huffman_symbol(
                    table=literal_table,
                    lengths=literal_lengths,
                    symbol_count=_KWAJ_LITERAL_SYMS,
                )
            except _KwajStreamEnd:
                return bytes(output)
            window[position] = literal
            output.append(literal)
            position = (position + 1) & 0x0FFF

    return bytes(output)


def _read_kwaj_lens(reader: _KwajBitReader, encoding_type: int, symbol_count: int) -> list[int]:
    if encoding_type == 0:
        fixed = {16: 4, 32: 5, 64: 6, 256: 8}.get(symbol_count)
        if fixed is None:
            raise ValidationError(f"Unsupported KWAJ code table size: {symbol_count}")
        return [fixed] * symbol_count

    lengths: list[int] = []
    if encoding_type == 1:
        current = reader.read_bits_safe(4)
        lengths.append(current)
        for _ in range(1, symbol_count):
            selector = reader.read_bits_safe(1)
            if selector == 0:
                lengths.append(current)
                continue
            selector = reader.read_bits_safe(1)
            if selector == 0:
                current += 1
            else:
                current = reader.read_bits_safe(4)
            lengths.append(current)
        return lengths

    if encoding_type == 2:
        current = reader.read_bits_safe(4)
        lengths.append(current)
        for _ in range(1, symbol_count):
            selector = reader.read_bits_safe(2)
            if selector == 3:
                current = reader.read_bits_safe(4)
            else:
                current += selector - 1
            if current < 0:
                raise ValidationError("Invalid KWAJ code table delta.")
            lengths.append(current)
        return lengths

    if encoding_type == 3:
        return [reader.read_bits_safe(4) for _ in range(symbol_count)]

    raise ValidationError(f"Unsupported KWAJ table encoding type: {encoding_type}")


def _kwaj_decode_table_size(symbol_count: int, table_bits: int) -> int:
    table_size = 1 << table_bits
    if table_size < (symbol_count * 2):
        return symbol_count * 4
    return table_size + (symbol_count * 2)


def _make_kwaj_decode_table(lengths: list[int], table_bits: int) -> list[int]:
    symbol_count = len(lengths)
    table_size = _kwaj_decode_table_size(symbol_count, table_bits)
    table = [0] * table_size
    pos = 0
    table_mask = 1 << table_bits
    bit_mask = table_mask >> 1

    for bit_num in range(1, table_bits + 1):
        for symbol, length in enumerate(lengths):
            if length != bit_num:
                continue
            leaf = pos
            pos += bit_mask
            if pos > table_mask:
                raise ValidationError("Invalid KWAJ Huffman lengths.")
            for _ in range(bit_mask):
                table[leaf] = symbol
                leaf += 1
        bit_mask >>= 1

    if pos != table_mask:
        for index in range(pos, table_mask):
            table[index] = 0xFFFF

        next_symbol = symbol_count if (table_mask >> 1) < symbol_count else (table_mask >> 1)
        pos <<= 16
        table_mask <<= 16
        bit_mask = 1 << 15

        for bit_num in range(table_bits + 1, _KWAJ_MAX_BITS + 1):
            for symbol, length in enumerate(lengths):
                if length != bit_num:
                    continue
                if pos >= table_mask:
                    raise ValidationError("Invalid KWAJ Huffman table overflow.")
                leaf = pos >> 16
                for fill in range(bit_num - table_bits):
                    if table[leaf] == 0xFFFF:
                        left = next_symbol << 1
                        right = left + 1
                        if right >= len(table):
                            raise ValidationError("Invalid KWAJ Huffman table size.")
                        table[left] = 0xFFFF
                        table[right] = 0xFFFF
                        table[leaf] = next_symbol
                        next_symbol += 1
                    leaf = table[leaf] << 1
                    if (pos >> (15 - fill)) & 1:
                        leaf += 1
                if leaf >= len(table):
                    raise ValidationError("Invalid KWAJ Huffman table index.")
                table[leaf] = symbol
                pos += bit_mask
            bit_mask >>= 1

        if pos != table_mask:
            raise ValidationError("Incomplete KWAJ Huffman table.")

    return table
