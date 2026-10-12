"""Build module: the English font (docs/design.md).

Source: tools/font/font.txt, compiled by tools/font/fontc.py.
- bank $61 (claimed "font.vwf"): VWF advance table at $6000 (128 bytes, index = code) and 16-row
  glyphs at $6080 + code*16 (MSB = leftmost pixel, row 0 = top of the 8x16 cell); the bold set
  (fontc.bold_glyph) at $6880 (advances) and $6900 + code*16 (glyphs); rest of the bank 0xFF.
- file 0x6B7A0 + (code-0x20)*12: fixed 8x12 versions of 0x20-0x5A for the original putc, same design.
  The game's specials 0x23, 0x24/0x25, 0x3C, 0x3E, 0x40 (and 0x5B-0x5F, outside the range) stay as they are.
- b.data['font_widths'] = {code: advance} for the text module (tools/font/widths.json holds the same).
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "font"))
import fontc  # noqa: E402

BANK = 0x2000
# The original glyphs 0x20-0x5A at file 0x6B7A0 (59 x 12 bytes), asserted before they are replaced.
ORIG_FIXED = bytes.fromhex(
    "000000000000000000000000101010101010101000001010242400000000000000000000e080c080e4342c240e09090e"
    "7e7e60606060000000000000000000000000060606067e7e304848484832528a84868478181818100000000000000000"
    "f0e0e0c0c0c0c0c0c0e0e0f01e0e0e0606060606060e0e1e0000925438fe3854920000000010101010fe101010100000"
    "00000000000000181808100000000000007e00000000000000000000000000001818000000000002060c183060c08000"
    "3c4242464a4a52526242423c30501010101010101010107c3c424242020408102040407e3c424202041804020242423c"
    "040c0c1414242444447e04047c404040407c02020202423c3c4242407c4242424242423c7e4242040408080810101010"
    "3c424242241824424242423c3c42424242423e020242423c000018180000000018180000000018180000000018180810"
    "00000010307efe7e30100000000000007e00007e000000000000001018fcfefc181000003c4242420418101010001010"
    "00003844b2caceb244380000101038286c4444fe82828282f088848488f88482828284f8384482808080808082824438"
    "f088848482828282848488f0fe80808080f88080808080fefe80808080f88080808080803844828280808e8282824438"
    "8282828282fe8282828282823810101010101010101010381e040404040404040484847880848890a0c0c0a090888482"
    "8080808080808080808080fe8282c6c6aaba92828282828282c2c2e2a2b2929a8a8e8686384482828282828282824438"
    "f88482828284f8808080808038448282828282bac6443a02f88482828284f88884848282384482824038040282824438"
    "fe1010101010101010101010828282828282828282824438828282444444442828281010828282828292baaac6c68282"
    "828244442810284444828282828244442828101010101010fe04040808102020404080fe")
assert len(ORIG_FIXED) == (fontc.FIXED_LAST - fontc.FIXED_FIRST + 1) * 12


def apply(b):
    glyphs = fontc.load()
    errors = fontc.check(glyphs, b.src)
    for e in errors:
        b.error("font.txt: " + e)
    if errors:
        return

    # VWF font in bank $61 (mapped at MPR3 = $6000 by the vwf module)
    first, last = b.claim("font.vwf")
    blob = fontc.vwf_blob(glyphs)
    base = first * BANK
    if any(x != 0xFF for x in b.rom[base:base + BANK]):
        b.error(f"bank ${first:02X} is not empty (0xFF) before the font is written")
        return
    b.write(base, blob)
    b.log(f"VWF font -> bank ${first:02X} (file 0x{base:05X}): widths $6000-$607F, glyphs $6080-$687F, "
          f"bold widths $6880-$68FF, bold glyphs $6900-${0x6000 + len(blob) - 1:04X}, "
          f"{len(blob)} bytes, {sum(1 for g in glyphs.values() if not g.keep)} drawn + "
          f"{sum(1 for g in glyphs.values() if g.keep)} original glyphs")

    # fixed 8x12 glyphs for the original putc (font bank $35)
    fixed = fontc.fixed_glyphs(glyphs)
    for c, data in sorted(fixed.items()):
        o = fontc.ORIG_FONT + (c - fontc.FIXED_FIRST) * 12
        k = (c - fontc.FIXED_FIRST) * 12
        b.patch(o, ORIG_FIXED[k:k + 12], data)
    for c in sorted(fontc.KEEP_CODES):
        if c <= fontc.FIXED_LAST:
            o = fontc.ORIG_FONT + (c - fontc.FIXED_FIRST) * 12
            b.expect(o, ORIG_FIXED[(c - 0x20) * 12:(c - 0x20) * 12 + 12])
    b.log(f"fixed glyphs: {len(fixed)} of 0x20-0x5A redrawn at 0x{fontc.ORIG_FONT:05X} ({len(fixed) * 12} bytes); "
          f"kept 0x23 0x24 0x25 0x3C 0x3E 0x40 (and 0x5B-0x5F)")

    w = fontc.widths(glyphs)
    b.data["font_widths"] = w
    b.data["font_vwf_bank"] = first
    m = fontc.metrics(glyphs)
    b.log(f"widths: space {m['space']}, digits {m['digits']}, lowercase avg {m['lower_avg']:.2f}, "
          f"uppercase avg {m['upper_avg']:.2f} px (tools/font/widths.json)")
    fontc.write_widths(glyphs)
