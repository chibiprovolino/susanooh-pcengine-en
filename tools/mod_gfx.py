"""Build module: graphics. 1) Town shop signs. Drawbridge Village's sign sprites 酒 (bar) and 宿 (inn) become a
tankard and a bed, like the gun and bag signs already there.

The signs are 16x16 sprite patterns (object id $B8, mode $41: planes 0-2 coded, plane 3 zero), each a separate
Huffman stream in bank $22 (descriptors at file 0x47B94, 7 bytes each). Decoder: b04 $C2DA/$C347 (bytes XOR the
previous even/odd byte, 16 words per plane), bit reader b00 $F5D9 with the tree at bank $0F $4000 (file 0x1E000,
nodes of 2 bytes: leaf = $80|x, value; else pointer to the 1-branch, the 0-branch follows). The new streams are
coded with the same tree and written over the old ones (they must fit). Colours: palette 8 of the signs,
1 grey, 2 beige (background), 3 tan, 4/5 black, 6/7 dark reds. The frame (outer 2 pixels) is kept.
"""
import os

TREE = 0x1E000
SIGN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gfx", "signs")
SIGNS = {  # file offset, size of the original stream, 12x12 interior (rows 2-13, cols 2-13); . = background
    "bar": (0x45183, 0x40, [      # tankard with foam, silhouette centred (cols 1-11 of 13)
        ".............",
        "...44..44....",
        "..42244224...",
        ".4222222224..",
        "..44444444...",
        "..4222222444.",
        "..42121124.4.",
        "..42121124.4.",
        "..4212112444.",
        "..42222224...",
        "..44444444...",
        ".............",
    ]),
    "inn": (0x45133, 0x50, [      # bed centred in the 13x12 inner area: post, pillow, red blanket, legs
        ".............",
        ".............",
        ".4...........",
        ".4...........",
        ".4.444.......",
        ".4.422466666.",
        ".44444477777.",
        ".44444444444.",
        ".4.........4.",
        ".4.........4.",
        ".............",
        ".............",
    ]),
}


def _node(R, a):
    o = TREE + a - 0x4000
    return R[o], R[o + 1]


def codes(R):
    res = {}
    def walk(a, pre):
        b0, b1 = _node(R, a)
        if b0 & 0x80:
            res.setdefault(b1, pre)
            return
        walk(a + 2, pre + "0")
        walk(b0 << 8 | b1, pre + "1")
    walk(0x4000, "")
    return res


def decode(R, off, n):
    out, p, m = [], off, 0x80
    for _ in range(n):
        a = 0x4000
        while True:
            b0, b1 = _node(R, a)
            if b0 & 0x80:
                out.append(b1)
                break
            bit = R[p] & m
            m >>= 1
            if m == 0:
                m, p = 0x80, p + 1
            a = (b0 << 8 | b1) if bit else a + 2
    return out


def planes_to_pixels(d):
    """96 delta bytes -> 16x16 colour indices."""
    w, pe, po = [], 0, 0
    for i in range(0, 96, 2):
        pe ^= d[i]
        po ^= d[i + 1]
        w.append(pe | po << 8)
    return [[sum(((w[16 * k + y] >> (15 - x)) & 1) << k for k in range(3)) for x in range(16)] for y in range(16)]


def pixels_to_stream(px, cd):
    d, pe, po = [], 0, 0
    for k in range(3):
        for y in range(16):
            v = sum(((px[y][x] >> k) & 1) << (15 - x) for x in range(16))
            lo, hi = v & 0xFF, v >> 8
            d += [lo ^ pe, hi ^ po]
            pe, po = lo, hi
    bits = "".join(cd[x] for x in d)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def build(R):
    cd = codes(R)
    out = {}
    for name, (off, size, art) in SIGNS.items():
        px = planes_to_pixels(decode(R, off, 96))
        for y, row in enumerate(art):
            for x, c in enumerate(row):
                px[2 + y][2 + x] = 2 if c == "." else int(c)
        final = os.path.join(SIGN_DIR, f"{name}-sign-final.png")
        if os.path.exists(final):          # coloured version (indexed 16x16, palette 8 indices)
            from PIL import Image
            im = Image.open(final)
            assert im.mode == "P" and im.size == (16, 16), final
            px = [[im.getpixel((x, y)) for x in range(16)] for y in range(16)]
            assert max(max(r) for r in px) <= 7, final
        s = pixels_to_stream(px, cd)
        assert len(s) <= size, f"sign {name}: {len(s)} > {size} bytes"
        out[name] = (off, size, s, px)
    return out


# 2) Title screen: the kana line ダイナミック企画 (bitmap tiles, colour 1) -> "Dynamic Planning" drawn in the pixel
# style of the "Kadokawa shoten" line above it (letters copied from it where they exist). asm/title_b01.s.
GLYPHS = {  # 11 rows (0-2 ascender, 3-10 x-height); y adds rows 11-12; "1" = ink
    "(": ["..1", ".1.", ".1.", "1..", "1..", "1..", "1..", "1..", ".1.", ".1.", "..1"],
    ")": ["1..", ".1.", ".1.", "..1", "..1", "..1", "..1", "..1", ".1.", ".1.", "1.."],
    "C": [".11.", "1..1", "1...", "1...", "1...", "1...", "1...", "1...", "1...", "1..1", ".11."],
    "D": ["111.", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", "111."],
    "P": ["111.", "1..1", "1..1", "1..1", "111.", "1...", "1...", "1...", "1...", "1...", "1..."],
    "y": ["....", "....", "....", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", ".111", "...1", ".11."],
    "n": [".....", ".....", ".....", "1.11.", ".1..1", ".1..1", ".1..1", ".1..1", ".1..1", ".1..1", ".1..1"],
    "a": [".....", ".....", ".....", ".11..", "1..1.", "...1.", ".111.", "1..1.", "1..1.", "1..1.", ".11.1"],
    "m": [".....", ".....", ".....", "11.1.", "1.1.1", "1.1.1", "1.1.1", "1.1.1", "1.1.1", "1.1.1", "1.1.1"],
    "i": [".", "1", ".", "1", "1", "1", "1", "1", "1", "1", "1"],
    "c": ["....", "....", "....", ".11.", "1..1", "1...", "1...", "1...", "1...", "1..1", ".11."],
    "r": ["....", "....", "....", "1.11", "11..", "1...", "1...", "1...", "1...", "1...", "1..."],
    "o": ["....", "....", "....", ".11.", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", ".11."],
    "l": ["1", "1", "1", "1", "1", "1", "1", "1", "1", "1", "1"],
    "g": ["....", "....", "....", ".11.", "1..1", "1..1", "1..1", "1..1", "1..1", "1..1", ".111", "...1", ".11."],
    " ": [".....", "....."],
}
TITLE_TEXT = "Dynamic Planning"   # the official English name of ダイナミック企画
TITLE_Y = 212 - 208   # pen inside the 88x24 patch (cols 16-26, tile rows 26-28); x is centred


TITLE_JUSTIFY = (129, 207)   # ink columns: "Kadokawa"/"HUDSON" start, "shoten"/"SOFT" end (original title)


def title_bitmap():
    """The credit line, justified: first ink on TITLE_JUSTIFY[0], last ink on TITLE_JUSTIFY[1]; the gap
    between the words takes up the slack."""
    W, H = 88, 24
    px = [[0] * W for _ in range(H)]
    words = TITLE_TEXT.split(" ")
    widths = [sum(len(GLYPHS[c][0]) + 1 for c in w) - 1 for w in words]
    left, right = TITLE_JUSTIFY
    slack = right - left + 1 - sum(widths)
    assert slack >= 3 * (len(words) - 1), f"title line too wide ({sum(widths)} px of ink)"
    x = left - 128
    for i, w in enumerate(words):
        for ch in w:
            g = GLYPHS[ch]
            for y, row in enumerate(g):
                for k, c in enumerate(row):
                    if c == "1":
                        px[TITLE_Y + y][x + k] = 1
            x += len(g[0]) + 1
        x -= 1
        if i < len(words) - 1:
            gap = slack // (len(words) - 1) + (1 if i < slack % (len(words) - 1) else 0)
            x += gap
    cols = [c for c in range(W) if any(px[y][c] for y in range(H))]
    assert (cols[0] + 128, cols[-1] + 128) == TITLE_JUSTIFY, (cols[0] + 128, cols[-1] + 128)
    return px


def title_data(px):
    out = bytearray()
    for r in range(3):
        for c in range(11):
            for y in range(8):
                row = px[r * 8 + y][c * 8:c * 8 + 8]
                out.append(sum(v << (7 - k) for k, v in enumerate(row)))
    return bytes(out)


def apply(b):
    R = bytes(b.src) if hasattr(b, "src") else bytes(b.rom)
    for name, (off, size, s, px) in build(R).items():
        b.write(off, s)
        check = planes_to_pixels(decode(bytes(b.rom), off, 96))
        assert check == px, f"sign {name}: round trip failed"
        b.log(f"sign {name}: {len(s)}/{size} bytes at file 0x{off:05X}")
    # title: the English logo in gfx/title/ (an edited background PNG there would be applied too)
    logo = edited("title-logo.png", LOGO_PAL, (LOGO_W, LOGO_H))
    bg = edited("title-bg.png", BG_PAL, (256, 256))
    bgn, gfx_bank = 0, BANKS_GFX
    if bg is not None:
        orig = load_indexed(os.path.join(GFX_DIR, ".orig", "title-bg.png"), BG_PAL, (256, 256))
        bgn, data_bg = bg_patches(bg, orig)
        gfx_bank = b.claim("gfx.far")[0]
        code, lf = b.asm("title_bg_far.s", 0x6000 + BG_DATA, {"BG_COUNT": bgn})
        blob = code + data_bg
        assert len(blob) <= 0x1000, f"title-bg.png: {bgn} tiles changed, too many"
        base = gfx_bank * 0x2000 + BG_DATA
        assert all(x == 0xFF for x in b.rom[base:base + len(blob)])
        b.write(base, blob)
        b.log(f"title-bg.png edited: {bgn} tiles re-drawn")
    # title credit line (+ the edited background tiles)
    lay = logo_layout(logo) if logo is not None else None
    lab = b.asm_region("title_b01.s", "gfx.b01", {"BG_COUNT": bgn, "GFX_BANK": gfx_bank,
                                                  "LOGO_LIST": 1 if lay else 0, "LIST_BANK": BANKS_GFX,
                                                  "UPL_BANK": BANKS_GFX + 1})
    data = title_data(title_bitmap())
    a = lab["DATA"]
    assert a + len(data) - 1 <= 0xDFFF, "title data does not fit gfx.b01"
    b.write(off_(1, a), data)
    b.patch(off_(1, 0xC299), bytes.fromhex("20 DA C3"), b"\x20" + bytes([lab["T_STUB"] & 0xFF, lab["T_STUB"] >> 8]))
    b.log(f"title: {TITLE_TEXT!r} over the kana line, data b01:${a:04X}-${a + len(data) - 1:04X}")
    if lay:
        apply_logo_layout(b, logo, lay, lab["L_STUB"])
    elif LOGO_ENABLED:
        apply_logo(b)


LOGO_ENABLED = False   # user 14:17: keep the original logo; an edited gfx/title/title-logo.png turns it on
GFX_DIR = os.environ.get("SUSANOO_GFX") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gfx", "title")
LOGO_PAL = [0x003, 0x1FF, 0x000, 0x038, 0x1C0, 0x000, 0x000, 0x1F8]   # sprite palette 12 (0 = transparent)
BG_PAL = [0x003, 0x038, 0x1FF]          # 0 background, 1 ink rows 0-127 (palette 0), 2 ink rows 128-255
BG_DATA = 0x1000                        # BG tile patches in bank gfx.far at $7000 (MPR3)


def pce_rgb(c):
    return ((c >> 3 & 7) * 255 // 7, (c >> 6 & 7) * 255 // 7, (c & 7) * 255 // 7)


def save_indexed(px, pal, path):
    from PIL import Image
    im = Image.new("P", (len(px[0]), len(px)))
    im.putpalette([v for c in pal for v in pce_rgb(c)] + [0] * (768 - 3 * len(pal)))
    im.putdata([v for row in px for v in row])
    im.save(path)


def load_indexed(path, pal, size):
    """Pixel indices of an indexed PNG; checks the size and that only palette indices are used, with
    their colours unchanged."""
    from PIL import Image
    im = Image.open(path)
    assert im.mode == "P", f"{path}: not an indexed-colour PNG (mode {im.mode})"
    assert im.size == size, f"{path}: size {im.size}, expected {size}"
    p = im.getpalette()
    data = list(im.getdata())
    for i in sorted(set(data)):
        assert i < len(pal), f"{path}: colour index {i} is not allowed (0-{len(pal) - 1})"
        assert tuple(p[3 * i:3 * i + 3]) == pce_rgb(pal[i]), f"{path}: colour {i} changed"
    w = size[0]
    return [data[y * w:(y + 1) * w] for y in range(size[1])]


def edited(name, pal, size):
    """The PNG's pixels if it is present (and differs from an exported .orig copy, if there is one), else None."""
    p, o = os.path.join(GFX_DIR, name), os.path.join(GFX_DIR, ".orig", name)
    if not os.path.exists(p):
        return None
    a = load_indexed(p, pal, size)
    return a if not os.path.exists(o) or a != load_indexed(o, pal, size) else None


def bg_patches(new, orig):
    """Entries (VRAM word address, 8 plane-0 bytes) for the 8x8 tiles whose ink differs."""
    out = bytearray()
    n = 0
    for r in range(32):
        for c in range(32):
            rows = [new[r * 8 + y][c * 8:c * 8 + 8] for y in range(8)]
            if rows == [orig[r * 8 + y][c * 8:c * 8 + 8] for y in range(8)]:
                continue
            addr = (0x100 + r * 32 + c) * 16          # title BAT: row r, col c -> tile $100 + 32r + c
            out += bytes([addr & 0xFF, addr >> 8])
            out += bytes(sum((1 if v else 0) << (7 - k) for k, v in enumerate(row)) for row in rows)
            n += 1
    return n, bytes(out)


def apply_logo(b, cells=None):
    """Unused (LOGO_ENABLED). Uploads 29 sprite cells (3712 bytes, 4 planes, VRAM words $6000-$673F, the
    order of SPRITES) over the title logo object $60. cells defaults to logo_cells(logo_canvas())."""
    first, _last = b.claim("gfx.far")
    base = first * 0x2000
    assert all(x == 0xFF for x in b.rom[base:base + 29 * 128]), f"bank ${first:02X} is not free"
    data = cells or logo_cells(logo_canvas())
    assert len(data) == 29 * 128
    b.write(base, data)
    l4 = b.asm_region("logo_b04.s", "gfx.b04", {"LOGO_BANK": first, "CNT_A": 29, "CNT_B": 0})
    b.patch(off_(4, 0xC2AD), bytes.fromhex("20 DA C2"), b"\x20" + bytes([l4["G_STUB"] & 0xFF, l4["G_STUB"] >> 8]))
    b.log(f"title logo -> bank ${first:02X}, {len(data)} bytes")


BANKS_GFX = 0x62

# ---- edited title logo (gfx/title/title-logo.png): a new sprite layout ------------------------------------
# Every 16x16 cell of the 136x88 canvas (screen LOGO_EDIT_X,Y = x60,y40) holding an opaque pixel becomes one 16x16 sprite; the
# grid offset is the one with the fewest cells. Patterns: cells 0-28 (VRAM $6000-$673F, the old logo's) and
# 48-63 ($6C00-$6FFF, free on the title screen); cell 29 ($6740) is the START cursor, $6780-$6BFF is left alone.
# Bank gfx.far first ($62): list code + entries at +$0000 (asm/logo_list_far.s), BG patches at +$1000;
# second ($63): upload code (asm/logo_upload_far.s, run from L_STUB) at +$0000, the cells at +$0200.
LOGO_FREE_CELLS = list(range(29)) + list(range(48, 64))


def logo_layout(px):
    """(ox, oy, [(cx, cy), ...]): cell (cx, cy) covers canvas x 16cx-ox.., y 16cy-oy.."""
    best = None
    for ox in range(16):
        for oy in range(16):
            cells = sorted({((x + ox) // 16, (y + oy) // 16) for y in range(LOGO_H) for x in range(LOGO_W)
                            if px[y][x]}, key=lambda c: (c[1], c[0]))
            if not cells:
                return None
            rows = max(sum(1 for c in cells if c[1] == r) for r in {c[1] for c in cells})
            k = (len(cells), rows)
            if best is None or k < best[0]:
                best = (k, ox, oy, cells)
    (n, rows), ox, oy, cells = best
    assert n <= len(LOGO_FREE_CELLS), f"title-logo.png needs {n} 16x16 sprites, at most {len(LOGO_FREE_CELLS)}"
    assert rows <= 15, f"title-logo.png: {rows} sprites on one line (limit 16 incl. the cursor)"
    return ox, oy, cells


def logo_layout_mask(lay):
    ox, oy, cells = lay
    m = [[0] * LOGO_W for _ in range(LOGO_H)]
    for cx, cy in cells:
        for y in range(16 * cy - oy, 16 * cy - oy + 16):
            for x in range(16 * cx - ox, 16 * cx - ox + 16):
                if 0 <= y < LOGO_H and 0 <= x < LOGO_W:
                    m[y][x] = 1
    return m


def apply_logo_layout(b, px, lay, l_stub):
    ox, oy, cells = lay
    first, last = b.claim("gfx.far")
    data, ent = bytearray(), bytearray()
    for i, (cx, cy) in enumerate(cells):
        x0, y0 = 16 * cx - ox, 16 * cy - oy
        c = [[px[y0 + y][x0 + x] if 0 <= y0 + y < LOGO_H and 0 <= x0 + x < LOGO_W else 0 for x in range(16)]
             for y in range(16)]
        for k in range(4):
            for y in range(16):
                v = sum(((c[y][x] >> k) & 1) << (15 - x) for x in range(16))
                data += bytes([v & 0xFF, v >> 8])
        sx, sy = LOGO_EDIT_X + x0, LOGO_EDIT_Y + y0
        ent += bytes([sy + 0x11, sx + 8, LOGO_FREE_CELLS[i], 0x00])   # b01 $CB68: y-$11, x-8 (object at -8,-16)
    assert last == BANKS_GFX + 1
    na = min(len(cells), 29)
    sig = bytearray()
    for i in range(len(cells)):                  # one distinctive word per cell, checked each frame
        words = [data[128 * i + 2 * k] | data[128 * i + 2 * k + 1] << 8 for k in range(64)]
        k = max(range(64), key=lambda k: (words[k] not in (0, 0xFFFF), bin(words[k]).count("1") % 16 != 0, -k))
        cell = i if i < na else 48 + (i - na)
        addr = 0x6000 + cell * 64 + k
        sig += bytes([addr & 0xFF, addr >> 8, words[k] & 0xFF, words[k] >> 8])
    UPL_CELLS = 0x200
    code, _ = b.asm("logo_upload_far.s", 0x6000, {"LGU_N": len(cells), "CNT_A": na, "CNT_B": len(cells) - na,
                                                  "LGU_CELLS": 0x6000 + UPL_CELLS})
    up = code + sig
    assert len(up) <= UPL_CELLS
    base = last * 0x2000
    blob2 = up + b"\xFF" * (UPL_CELLS - len(up)) + data
    assert all(x == 0xFF for x in b.rom[base:base + len(blob2)]), f"bank ${last:02X} is not free"
    b.write(base, blob2)
    code, _ = b.asm("logo_list_far.s", 0x6000, {"LGF_N": len(cells)})
    blob = code + ent
    assert len(blob) <= BG_DATA
    lb = first * 0x2000
    assert all(x == 0xFF for x in b.rom[lb:lb + len(blob)]), f"bank ${first:02X} is not free"
    b.write(lb, blob)
    b.patch(off_(1, 0xCA85), bytes.fromhex("20 34 CB"), b"\x20" + bytes([l_stub & 0xFF, l_stub >> 8]))
    rows = max(sum(1 for c in cells if c[1] == r) for r in {c[1] for c in cells})
    b.log(f"title-logo.png edited: {len(cells)} sprites 16x16 (grid offset {ox},{oy}, max {rows} per line), "
          f"upload code + {len(data)} bytes of cells in bank ${last:02X}, list {len(blob)} bytes in bank ${first:02X}")


def off_(bank, cpu):
    return bank * 0x2000 + (cpu & 0x1FFF)


# ---- 3) title logo: 凄ノ王伝説 (sprites) -> "The Legend / SUSANO OH" -------------------------------------
# The logo is 11 sprites in sprite palette 12 (1 white, 3 red, 4 green, 7 yellow), patterns at VRAM words
# $6000-$673F (29 cells of 16x16, row-major inside a sprite). They come from the title image, so the stub
# rewrites them after it loads, from LOGO_BANK ($6000 when mapped at MPR3).
SPRITES = [  # x, y (screen), cells across, cells down, pattern number
    (144, 80, 2, 2, 0x300), (72, 63, 2, 2, 0x308), (72, 95, 2, 1, 0x310),
    (152, 40, 2, 1, 0x314), (152, 56, 2, 2, 0x318), (176, 80, 2, 2, 0x320),
    (104, 56, 2, 2, 0x328), (104, 88, 2, 1, 0x330), (136, 44, 1, 1, 0x334),
    (136, 60, 1, 1, 0x336), (136, 76, 1, 1, 0x338),
]
LOGO_X, LOGO_Y, LOGO_W, LOGO_H = 72, 40, 136, 88
# an edited title-logo.png is placed here instead (its ink, canvas x1-134, is
# centred on the 256-px screen at x60: 61 px free on both sides; y unchanged)
LOGO_EDIT_X, LOGO_EDIT_Y = 60, 40
VRAM_BASE, N_CELLS = 0x6000, 29

BIG = {  # 5x7 bold capitals, drawn 2x wide / 3x tall with a shear; "1" = ink
    "S": [".111.", "1...1", "1....", ".111.", "....1", "1...1", ".111."],
    "U": ["1...1", "1...1", "1...1", "1...1", "1...1", "1...1", ".111."],
    "A": ["..1..", ".1.1.", "1...1", "1...1", "11111", "1...1", "1...1"],
    "N": ["1...1", "11..1", "1.1.1", "1..11", "1...1", "1...1", "1...1"],
    "O": [".111.", "1...1", "1...1", "1...1", "1...1", "1...1", ".111."],
    "H": ["1...1", "1...1", "1...1", "11111", "1...1", "1...1", "1...1"],
}
SMALL = {  # 5x7 light capitals/lowercase for "The Legend"
    "T": ["11111", "..1..", "..1..", "..1..", "..1..", "..1..", "..1.."],
    "h": ["1....", "1....", "1.11.", "11..1", "1...1", "1...1", "1...1"],
    "e": [".....", ".....", ".111.", "1...1", "11111", "1....", ".111."],
    "L": ["1....", "1....", "1....", "1....", "1....", "1....", "11111"],
    "g": [".....", ".....", ".1111", "1...1", ".1111", "....1", ".111."],
    "n": [".....", ".....", "1.11.", "11..1", "1...1", "1...1", "1...1"],
    "d": ["....1", "....1", ".111.", "1...1", "1...1", "1...1", ".1111"],
    " ": ["..", "..", "..", "..", "..", "..", ".."],
}
RED, WHITE, GREEN = 3, 1, 4


def _text(px, font, text, x0, y0, colour, scale=1, shear=0, gap=1, sy=None):
    """Draw text; shear = pixels of rightward slant per 4 rows (the original logo leans right)."""
    sy = sy or scale
    x = x0
    for ch in text:
        g = font[ch]
        h = len(g) * sy
        for y, row in enumerate(g):
            for k, c in enumerate(row):
                if c != "1":
                    continue
                for dy in range(sy):
                    for dx in range(scale):
                        yy = y0 + y * sy + dy
                        sx = ((h - 1 - (y * sy + dy)) * shear) // 4
                        xx = x + k * scale + dx + sx
                        if 0 <= yy < len(px) and 0 <= xx < len(px[0]):
                            px[yy][xx] = colour
        x += len(g[0]) * scale + gap
    return x


def _width(font, text, scale=1, gap=1):
    return sum(len(font[c][0]) * scale + gap for c in text) - gap


def _outline(px, ink, colour):
    out = [row[:] for row in px]
    H, W = len(px), len(px[0])
    for y in range(H):
        for x in range(W):
            if px[y][x]:
                continue
            if any(0 <= y+dy < H and 0 <= x+dx < W and px[y+dy][x+dx] == ink
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                out[y][x] = colour
    return out


def logo_mask():
    """Pixels the 11 logo sprites actually show: a diagonal band plus the lower-right block."""
    m = [[0] * LOGO_W for _ in range(LOGO_H)]
    for sx, sy, nx, ny, _pat in SPRITES:
        for y in range(sy - LOGO_Y, sy - LOGO_Y + ny * 16):
            for x in range(sx - LOGO_X, sx - LOGO_X + nx * 16):
                if 0 <= y < LOGO_H and 0 <= x < LOGO_W:
                    m[y][x] = 1
    return m


def logo_canvas():
    """"SUSANO OH" in red along the diagonal band (where 凄ノ王 was), "The Legend" in green in the
    lower-right block (where 伝説 was)."""
    px = [[0] * LOGO_W for _ in range(LOGO_H)]
    big, scale, sy, shear, gap = "SUSANO OH", 2, 3, 1, 2
    x = 2
    for ch in big:
        if ch == " ":
            x += 6
            continue
        y = 27 - (x * 22) // 112          # the band rises to the right
        nx = _text(px, BIG, ch, x, y, RED, scale, shear, gap, sy)
        x = nx
    px = _outline(px, RED, WHITE)
    small, bx, by, bw = "The Legend", 72, 40, 64
    sw = _width(SMALL, small)
    _text(px, SMALL, small, bx + (bw - sw) // 2, by + 12, GREEN)
    return px


def logo_cells(px):
    cells = [[[0] * 16 for _ in range(16)] for _ in range(N_CELLS)]
    for sx, sy, nx, ny, pat in SPRITES:
        base = (pat * 32 - VRAM_BASE) // 64
        for cy in range(ny):
            for cx in range(nx):
                c = cells[base + cy * nx + cx]
                for y in range(16):
                    for x in range(16):
                        py, qx = sy - LOGO_Y + cy * 16 + y, sx - LOGO_X + cx * 16 + x
                        if 0 <= py < LOGO_H and 0 <= qx < LOGO_W:
                            c[y][x] = px[py][qx]
    out = bytearray()
    for c in cells:
        for k in range(4):
            for y in range(16):
                v = sum(((c[y][x] >> k) & 1) << (15 - x) for x in range(16))
                out += bytes([v & 0xFF, v >> 8])
    return bytes(out)
