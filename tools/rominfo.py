#!/usr/bin/env python3
"""Identify a PC Engine HuCard dump and scan it for Shift-JIS text.

  rominfo.py ROM [--strings MINLEN]

Reports size, whether a 512-byte copier header is present, CRC32/MD5/SHA1
(of the headerless image, which is what the patch targets), and optionally
lists runs of valid Shift-JIS kana/kanji so we can tell whether the game
stores its script as plain SJIS or in a custom table/compressed format.
"""
import sys, zlib, hashlib


def is_sjis_pair(a, b):
    return ((0x81 <= a <= 0x9F or 0xE0 <= a <= 0xEF)
            and (0x40 <= b <= 0xFC and b != 0x7F))


def scan(data, minlen):
    i, n = 0, len(data)
    while i < n - 1:
        j = i
        while j < n - 1 and is_sjis_pair(data[j], data[j + 1]):
            j += 2
        if (j - i) // 2 >= minlen:
            try:
                yield i, data[i:j].decode("shift_jis")
            except UnicodeDecodeError:
                pass
            i = j
        else:
            i += 1


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    raw = open(sys.argv[1], "rb").read()
    header = len(raw) % 8192 == 512
    data = raw[512:] if header else raw
    print(f"file size      : {len(raw)} bytes")
    print(f"copier header  : {'yes (512 bytes, stripped below)' if header else 'no'}")
    print(f"image size     : {len(data)} bytes ({len(data) // 1024} KiB)")
    print(f"CRC32          : {zlib.crc32(data):08X}")
    print(f"MD5            : {hashlib.md5(data).hexdigest()}")
    print(f"SHA1           : {hashlib.sha1(data).hexdigest()}")
    if "--strings" in sys.argv:
        minlen = int(sys.argv[sys.argv.index("--strings") + 1])
        for off, s in scan(data, minlen):
            print(f"{off:06X}: {s}")


if __name__ == "__main__":
    main()
