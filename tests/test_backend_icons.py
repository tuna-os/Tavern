# test_backend_icons.py - Unit tests for the ICO->PNG decoder.
# SPDX-License-Identifier: GPL-3.0-or-later

import struct
import zlib

import pytest

from tavern.backend_icons import ico_to_png


def _make_minimal_png(w=2, h=2):
    """Build a tiny valid PNG so we can embed it inside an ICO container."""
    def _chunk(t, d):
        c = t + d
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(d)) + c + crc
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    raw = bytearray()
    for _ in range(h):
        raw.append(0)
        raw.extend(b'\xff\x00\x00\xff' * w)
    idat = _chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    iend = _chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


def _wrap_in_ico(payload, w=2, h=2):
    """Wrap arbitrary `payload` bytes as a single-entry ICO directory."""
    header = struct.pack('<HHH', 0, 1, 1)  # reserved, type=ICO, count=1
    data_offset = 6 + 16
    entry = bytes([
        w if w < 256 else 0,  # width
        h if h < 256 else 0,  # height
        0, 0,                  # color count, reserved
    ]) + struct.pack('<HHII', 1, 32, len(payload), data_offset)
    return header + entry + payload


def test_too_short_returns_none():
    assert ico_to_png(b'') is None
    assert ico_to_png(b'\x00\x00') is None


def test_bad_magic_returns_none():
    # type=99 is neither ICO (1) nor CUR (2)
    junk = struct.pack('<HHH', 0, 99, 1) + b'\x00' * 30
    assert ico_to_png(junk) is None


def test_embedded_png_passthrough():
    """If the ICO entry is already a PNG, ico_to_png returns it unchanged."""
    png = _make_minimal_png()
    ico = _wrap_in_ico(png)
    out = ico_to_png(ico)
    assert out == png


def test_non_32bit_dib_returns_none():
    """Non-32bpp BMP DIBs aren't supported and should bail out cleanly."""
    # Fake DIB: header_size=40, ignore most fields, set bpp=24
    dib = struct.pack('<I', 40) + b'\x00' * 12 + struct.pack('<H', 1) + struct.pack('<H', 24)
    dib += b'\x00' * 200  # padding
    ico = _wrap_in_ico(dib, w=8, h=8)
    assert ico_to_png(ico) is None
