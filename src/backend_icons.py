# backend_icons.py - ICO -> PNG decoder (pure Python, no extra deps).
# SPDX-License-Identifier: GPL-3.0-or-later

"""Self-contained ICO -> PNG conversion used to render favicon icons fetched
from package homepages. Extracted from `backend.py` so it can be tested
without spinning up the rest of the Homebrew backend.
"""

import struct
import zlib


def ico_to_png(ico_data):
    """Extract the largest image from an ICO file and return PNG bytes.

    ICO files are containers holding multiple images. Each entry is either
    an embedded PNG or a raw 32-bit BGRA BMP DIB. We pick the largest one
    and, if it's already PNG, return it directly; otherwise we decode the
    BGRA pixel data and synthesize a minimal PNG with zlib.

    Returns None if the input is not a valid ICO or the format is one we
    can't decode (e.g. non-32-bit DIBs).
    """
    try:
        if len(ico_data) < 6:
            return None

        # ICO header: reserved(2) + type(2) + count(2)
        _reserved, ico_type, count = struct.unpack_from('<HHH', ico_data, 0)
        if ico_type not in (1, 2) or count == 0 or count > 256:
            return None

        # Parse directory entries (16 bytes each, starting at offset 6)
        best_entry = None
        best_size = 0
        for i in range(count):
            offset = 6 + i * 16
            if offset + 16 > len(ico_data):
                break
            w = ico_data[offset] or 256
            h = ico_data[offset + 1] or 256
            data_size = struct.unpack_from('<I', ico_data, offset + 8)[0]
            data_offset = struct.unpack_from('<I', ico_data, offset + 12)[0]
            pixels = w * h
            if pixels >= best_size and data_offset + data_size <= len(ico_data):
                best_size = pixels
                best_entry = (w, h, data_size, data_offset)

        if not best_entry:
            return None

        w, h, data_size, data_offset = best_entry
        image_data = ico_data[data_offset:data_offset + data_size]

        # Already PNG — return as-is.
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            return image_data

        # BMP DIB -> PNG (pure Python).
        dib_header_size = struct.unpack_from('<I', image_data, 0)[0]
        bpp = struct.unpack_from('<H', image_data, 14)[0]
        if bpp != 32:
            return None  # Only handle 32-bit BGRA

        pixel_start = dib_header_size
        row_bytes = w * 4
        xor_size = w * h * 4

        if pixel_start + xor_size > len(image_data):
            return None

        # BMP rows are bottom-up; PNG wants top-down.
        raw_rows = bytearray()
        for y in range(h - 1, -1, -1):
            row_off = pixel_start + y * row_bytes
            raw_rows.append(0)  # PNG filter byte: None
            for x in range(w):
                px = row_off + x * 4
                b = image_data[px]
                g = image_data[px + 1]
                r = image_data[px + 2]
                a = image_data[px + 3]
                raw_rows.extend((r, g, b, a))

        def _png_chunk(chunk_type, data):
            chunk = chunk_type + data
            crc = struct.pack('>I', zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack('>I', len(data)) + chunk + crc

        signature = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
        ihdr = _png_chunk(b'IHDR', ihdr_data)
        idat = _png_chunk(b'IDAT', zlib.compress(bytes(raw_rows), 9))
        iend = _png_chunk(b'IEND', b'')

        return signature + ihdr + idat + iend

    except Exception:
        return None
