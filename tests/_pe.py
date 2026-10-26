# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Minimal Windows PE files for tests: the header fields and import table reshade_games reads, nothing more."""

import struct

MACHINE = {32: 0x14C, 64: 0x8664}


def make_pe(bits, imports=(), body=b""):
    """A PE32/PE32+ image importing the given DLL names, with body appended (for string scans)."""
    dirs = 96 if bits == 32 else 112
    opt = bytearray(dirs + 16 * 8)
    struct.pack_into("<H", opt, 0, 0x10B if bits == 32 else 0x20B)
    raw_ptr, va = 0x200, 0x1000
    n = len(imports)
    names_at = (n + 1) * 20
    table, names = bytearray(names_at), bytearray()
    for i, name in enumerate(imports):
        struct.pack_into("<I", table, i * 20 + 12, va + names_at + len(names))
        names += name.encode() + b"\0"
    section = bytes(table + names)
    if imports:
        struct.pack_into("<II", opt, dirs + 8, va, len(table))
    coff = struct.pack("<HHIIIHH", MACHINE[bits], 1, 0, 0, 0, len(opt), 0x22)
    header = struct.pack("<8sIIIIIIHHI", b".idata", len(section), va, len(section), raw_ptr, 0, 0, 0, 0, 0)
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    image = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + header
    return image.ljust(raw_ptr, b"\0") + section + body
