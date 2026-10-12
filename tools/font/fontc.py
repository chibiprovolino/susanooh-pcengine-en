#!/usr/bin/env python3
"""Compile tools/font/font.txt (the English font source) for the patch (docs/design.md).

    python3 tools/font/fontc.py            check font.txt, write tools/font/widths.json, print metrics
    python3 tools/font/fontc.py --blob F   also write the bank $61 VWF blob to F

Outputs (also available as functions for tools/mod_font.py and tools/font/preview.py):
  widths.json     {"<decimal code>": advance} for every drawable code (read with int(k, 0) or int(k))
  vwf_blob()      bank $61 image: advance table at $6000 (128 bytes, index = code, 0 = no glyph),
                  glyphs at $6080 + code*16 (16 rows, MSB = leftmost pixel, row 0 = top of the cell);
                  bold set (bold_glyph(): row | row>>1, advance + 1; space and keep glyphs unchanged):
                  advances at $6880, glyphs at $6900 + code*16 (codes 09/0A switch it on/off in VWF text)
  fixed_glyphs()  {code: 12 bytes} 8x12 versions of 0x20-0x5A (cell rows 2-13, ink centred in 8 px)
                  for the original putc at file 0x6B7A0 + (code-0x20)*12; "keep" glyphs are left out.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_TXT = os.environ.get("SUSANOO_FONT_TXT") or os.path.join(HERE, "font.txt")   # env: try a variant
WIDTHS_JSON = os.path.join(HERE, "widths.json")
SRC_ROM = os.path.join(os.path.dirname(os.path.dirname(HERE)), "rom", "Susanoo Densetsu (Japan).pce")

ORIG_FONT = 0x6B7A0          # file offset of the original ASCII-range glyphs (code 0x20), 12 bytes each
FIXED_FIRST, FIXED_LAST = 0x20, 0x5A
KEEP_CODES = {0x23, 0x24, 0x25, 0x3C, 0x3E, 0x40, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F}
VWF_WIDTHS, VWF_GLYPHS = 0x0000, 0x0080   # offsets inside bank $61 ($6000 / $6080)
BOLD_WIDTHS, BOLD_GLYPHS = 0x0880, 0x0900 # bold set ($6880 / $6900), feature "bold names"
BLOB_SIZE = 0x900 + 0x80 * 16
DIGITS = range(0x30, 0x3A)
NEEDED = ([0x20, 0x21, 0x22, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x3A, 0x3B, 0x3D, 0x3F]
          + list(DIGITS) + list(range(0x41, 0x5B)) + list(range(0x61, 0x7B)) + [0x60, 0x7B, 0x7C, 0x7D])


class Glyph:
    def __init__(self, code, name, advance, keep, rows, line):
        self.code, self.name, self.advance, self.keep, self.rows, self.line = code, name, advance, keep, rows, line

    def bits(self):
        """16 row bytes, MSB = leftmost pixel."""
        return [sum(0x80 >> i for i, ch in enumerate(r) if ch == "#") for r in self.rows]

    def ink_cols(self):
        cols = [i for r in self.rows for i, ch in enumerate(r) if ch == "#"]
        return (min(cols), max(cols)) if cols else None

    def ink_rows(self):
        rows = [y for y, r in enumerate(self.rows) if "#" in r]
        return (min(rows), max(rows)) if rows else None


def load(path=FONT_TXT):
    """Parse font.txt -> {code: Glyph}. Raises ValueError with the line number on any format error."""
    glyphs = {}
    lines = open(path, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        p = s.split()
        if p[0] != "glyph" or len(p) not in (4, 5) or (len(p) == 5 and p[4] != "keep"):
            raise ValueError(f"{path}:{i + 1}: expected 'glyph <hex> <name> <advance> [keep]', got {s!r}")
        code, name, adv, keep = int(p[1], 16), p[2], int(p[3]), len(p) == 5
        rows = [lines[i + 1 + k].strip() for k in range(16)] if i + 16 < len(lines) else []
        if len(rows) != 16 or any(len(r) != 8 or set(r) - set(".#") for r in rows):
            raise ValueError(f"{path}:{i + 1}: glyph {code:02X} needs 16 rows of 8 '.'/'#'")
        if code in glyphs:
            raise ValueError(f"{path}:{i + 1}: glyph {code:02X} defined twice")
        glyphs[code] = Glyph(code, name, adv, keep, rows, i + 1)
        i += 17
    return glyphs


def check(glyphs, src_rom=None):
    """Return a list of error strings (empty = font is valid)."""
    err = []
    for c in NEEDED:
        if c not in glyphs:
            err.append(f"missing glyph {c:02X}")
    for c in KEEP_CODES:
        if c not in glyphs or not glyphs[c].keep:
            err.append(f"glyph {c:02X} must be a 'keep' glyph (original game glyph)")
    digit_adv = {glyphs[c].advance for c in DIGITS if c in glyphs}
    if len(digit_adv) > 1:
        err.append(f"digits must share one advance, have {sorted(digit_adv)}")
    for c, g in sorted(glyphs.items()):
        tag = f"glyph {c:02X} ({g.name}, line {g.line})"
        if not 0x20 <= c <= 0x7F:
            err.append(f"{tag}: code outside 0x20-0x7F")
        if not 1 <= g.advance <= 8:
            err.append(f"{tag}: advance {g.advance} not in 1-8")
        if g.keep:
            if c not in KEEP_CODES:
                err.append(f"{tag}: 'keep' is only for {sorted(hex(k) for k in KEEP_CODES)}")
            if any("#" in g.rows[y] for y in (0, 1, 14, 15)):
                err.append(f"{tag}: keep glyph has ink outside rows 2-13")
            if src_rom is not None:
                o = ORIG_FONT + (c - 0x20) * 12
                if bytes(g.bits()[2:14]) != src_rom[o:o + 12]:
                    err.append(f"{tag}: keep glyph differs from the original at 0x{o:05X}")
            continue
        if c in KEEP_CODES:
            err.append(f"{tag}: must be marked keep")
        ink = g.ink_cols()
        rows = g.ink_rows()
        if ink:
            if ink[1] > g.advance - 2:
                err.append(f"{tag}: ink reaches column {ink[1]}, advance {g.advance} leaves no 1-px spacing")
            if rows[0] < 1 or rows[1] > 14:
                err.append(f"{tag}: ink in rows {rows[0]}-{rows[1]}, VWF glyphs may use rows 1-14 only")
            if FIXED_FIRST <= c <= FIXED_LAST and (rows[0] < 2 or rows[1] > 13):
                err.append(f"{tag}: fixed-range glyph has ink in rows {rows[0]}-{rows[1]}, must stay in 2-13")
    return err


def widths(glyphs):
    return {c: g.advance for c, g in sorted(glyphs.items())}


def bold_glyph(g):
    """(advance, 16 row bytes) of the bold version: every row OR'ed with itself shifted right by one,
    advance + 1 (the 1-px spacing stays). Space (no ink) and the game's keep glyphs are unchanged.
    Max advance 9 (the VWF core handles px + 9 <= 16)."""
    if g.keep or not g.ink_cols():
        return g.advance, list(g.bits())
    return g.advance + 1, [(b | (b >> 1)) & 0xFF for b in g.bits()]


def bold_widths(glyphs):
    return {c: bold_glyph(g)[0] for c, g in sorted(glyphs.items())}


def vwf_blob(glyphs):
    """The bank $61 image (0x1100 bytes from $6000): regular set, then the bold set."""
    blob = bytearray(BLOB_SIZE)
    for c, g in glyphs.items():
        blob[VWF_WIDTHS + c] = g.advance
        blob[VWF_GLYPHS + c * 16:VWF_GLYPHS + c * 16 + 16] = bytes(g.bits())
        adv, bits = bold_glyph(g)
        blob[BOLD_WIDTHS + c] = adv
        blob[BOLD_GLYPHS + c * 16:BOLD_GLYPHS + c * 16 + 16] = bytes(bits)
    return bytes(blob)


def fixed_glyph(g):
    """8x12 fixed-cell version: cell rows 2-13, ink centred in 8 px (extra pixel goes right)."""
    bits = g.bits()[2:14]
    ink = g.ink_cols()
    if not ink:
        return bytes(12)
    w = ink[1] - ink[0] + 1
    shift = (8 - w) // 2 - ink[0]          # >0: move right
    return bytes(((b >> shift) if shift >= 0 else (b << -shift)) & 0xFF for b in bits)


def fixed_glyphs(glyphs):
    return {c: fixed_glyph(glyphs[c]) for c in range(FIXED_FIRST, FIXED_LAST + 1)
            if c in glyphs and not glyphs[c].keep}


def metrics(glyphs):
    lc = [glyphs[c].advance for c in range(0x61, 0x7B)]
    uc = [glyphs[c].advance for c in range(0x41, 0x5B)]
    return {
        "glyphs": len(glyphs),
        "space": glyphs[0x20].advance,
        "digits": glyphs[0x30].advance,
        "lower_avg": sum(lc) / len(lc), "upper_avg": sum(uc) / len(uc),
        "max_advance": max(g.advance for g in glyphs.values() if not g.keep),
    }


def write_widths(glyphs, path=WIDTHS_JSON):
    data = {str(c): a for c, a in widths(glyphs).items()}
    text = json.dumps(data, indent=0) + "\n"
    if not os.path.exists(path) or open(path).read() != text:      # only rewrite when it changed
        with open(path, "w") as f:
            f.write(text)


def main():
    args = sys.argv[1:]
    src = open(SRC_ROM, "rb").read() if os.path.exists(SRC_ROM) else None
    glyphs = load()
    err = check(glyphs, src)
    for e in err:
        print("ERROR:", e)
    if err:
        sys.exit(1)
    write_widths(glyphs)
    m = metrics(glyphs)
    print(f"{m['glyphs']} glyphs; space {m['space']} px, digits {m['digits']} px, "
          f"lowercase avg {m['lower_avg']:.2f} px, uppercase avg {m['upper_avg']:.2f} px -> {WIDTHS_JSON}")
    if "--blob" in args:
        p = args[args.index("--blob") + 1]
        open(p, "wb").write(vwf_blob(glyphs))
        print(f"VWF blob {BLOB_SIZE} bytes -> {p}")


if __name__ == "__main__":
    main()
