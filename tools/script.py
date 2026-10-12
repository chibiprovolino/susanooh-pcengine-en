#!/usr/bin/env python3
"""Susano-O Densetsu script decoder.

Format (see docs/text-format.md):
- Block pointer table: 16-bit words at bank $38 CPU $C75C (file 0x7075C).
  ptr bits 15-13 = bank offset from $24, bits 12-0 = offset in the bank window.
- Huffman tree at bank $24 (file 0x48000), root at CPU $4000.
  Node: byte0 bit7 set -> leaf, value = byte1.
        else bit 0 -> next node (addr+2); bit 1 -> node at CPU (byte0<<8 | byte1).
  Bits are read MSB first.
- A block is a run of strings, each terminated by 0x00.
  0x1F n = insert string n of block 0x19 (names).
"""
import struct, sys, unicodedata

import os
ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rom", "Susanoo Densetsu (Japan).pce")
TABLE = 0x7075C
TREE_BANK = 0x24
TEXT_BANK = 0x24


def load(path=ROM_PATH):
    return open(path, "rb").read()


def block_ptr(rom, n):
    return struct.unpack_from("<H", rom, TABLE + 2 * n)[0]


def ptr_to_file(p):
    return (TEXT_BANK + (p >> 13)) * 0x2000 + (p & 0x1FFF)


class BitReader:
    def __init__(self, rom, off):
        self.rom, self.off, self.mask = rom, off, 0x80

    def bit(self):
        b = 1 if self.rom[self.off] & self.mask else 0
        self.mask >>= 1
        if not self.mask:
            self.mask, self.off = 0x80, self.off + 1
        return b


def huff_sym(rom, br):
    node = 0x4000
    while True:
        f = TREE_BANK * 0x2000 + (node - 0x4000)
        b0 = rom[f]
        if b0 & 0x80:
            return rom[f + 1]
        if br.bit():
            node = (b0 << 8) | rom[f + 1]
        else:
            node += 2


def decode_block(rom, n, count=None, stop_at=None):
    """Return list of strings (each a list of byte codes, without the 0 terminator)
    and the file offset/bitmask where decoding stopped."""
    br = BitReader(rom, ptr_to_file(block_ptr(rom, n)))
    out = []
    while count is None or len(out) < count:
        if stop_at is not None and br.off + (br.mask != 0x80) >= stop_at:
            break
        s = []
        while True:
            c = huff_sym(rom, br)
            if c == 0:
                break
            s.append(c)
            if c == 0x1F:
                s.append(huff_sym(rom, br))
            if len(s) > 400 or (stop_at is not None and br.off >= stop_at):
                break
        out.append(s)
    return out, br


EMPTY_PTR = 0xC7A2          # placeholder entry (blocks 03, 04, 06, 18, 21)
NUM_BLOCKS = 0x23
LAST_BLOCK_COUNT = 20     # block 0D is the last one; FF padding follows at 0x51DE3


def all_blocks(rom):
    """{block: [strings]} for every real block, each decoded up to the next block's start."""
    ptrs = {b: block_ptr(rom, b) for b in range(NUM_BLOCKS) if block_ptr(rom, b) != EMPTY_PTR}
    starts = sorted(set(ptr_to_file(p) for p in ptrs.values()))
    res = {}
    for b, p in ptrs.items():
        f = ptr_to_file(p)
        later = [o for o in starts if o > f]
        res[b] = decode_block(rom, b, stop_at=later[0] if later else None,
                              count=None if later else LAST_BLOCK_COUNT)[0]
    return res


# ---- code -> text -----------------------------------------------------------
HIRA = ("　。「」、・をぁぃぅぇぉゃゅょっーあいうえおかきくけこさしすせそたちつてとなにぬねの"
        "はひふへほまみむめもやゆよらりるれろわん゛゜")
KATA = ("　。「」、・ヲァィゥェォャュョッーアイウエオカキクケコサシスセソタチツテトナニヌネノ"
        "ハヒフヘホマミムメモヤユヨラリルレロワン゛゜")


KANJI = ("凄王魔獣朱紗瓜生雪代東西南北男女人町村城洞窟塔船飛行機武沼森林湖大陸川砂漠岬海山"
         "空朝昼夕方夜闇日年強弱倒苦恐退剣盾鎧兜器悪邪教長祖力話攻防青真悟美")
# codes 0x60-0x9F hold the first 64 kanji; the last 9 continue at 0xE0-0xE8
KANJI_MAP = {(0x60 + i if i < 64 else 0xE0 + i - 64): k for i, k in enumerate(KANJI)}


def code_name(c, kanji=KANJI_MAP):
    if 0x20 <= c <= 0x5F:
        return chr(c)
    if 0xA0 <= c <= 0xDF:
        return HIRA[c - 0xA0]
    if kanji and c in kanji:
        return kanji[c]
    return f"[{c:02X}]"


def render(s, kanji=KANJI_MAP, names=None):
    """Codes -> readable Japanese. 0x01/0x02 switch kana to katakana and back;
    a 0xDE/0xDF (dakuten/handakuten) code precedes the kana it modifies."""
    out, i, kata = [], 0, False
    while i < len(s):
        c = s[i]
        if c == 0x01: kata = True; i += 1; continue
        if c == 0x02: kata = False; i += 1; continue
        if c in (0xDE, 0xDF) and i + 1 < len(s) and 0xA0 <= s[i + 1] <= 0xDF:
            base = (KATA if kata else HIRA)[s[i + 1] - 0xA0]
            out.append(unicodedata.normalize("NFC", base + ("\u3099" if c == 0xDE else "\u309A")))
            i += 2; continue
        if kata and 0xA0 <= c <= 0xDF:
            out.append(KATA[c - 0xA0]); i += 1; continue
        if c == 0x1F and i + 1 < len(s):
            nm = names[s[i + 1]] if names and s[i + 1] < len(names) else None
            out.append(f"{{{render(nm, kanji) if nm else 'DICT %02X' % s[i + 1]}}}")
            i += 2; continue
        out.append(code_name(c, kanji))
        i += 1
    return "".join(out)


if __name__ == "__main__":
    rom = load()
    blk = int(sys.argv[1], 0)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    strs, br = decode_block(rom, blk, n)
    for i, s in enumerate(strs):
        print(f"{blk:02X}:{i:03d} {render(s)}")
