#!/usr/bin/env python3
"""Proof sheets of every string, drawn with the real font (docs/design.md).

    python3 tools/proof.py [OUT_DIR]          (default build/proof; the build calls render_all())

The final bytes of each string (as the text module stores them, before the 03-n split, which is invisible
on screen) are run through a model of the game's printer: 04/05 VWF depth, 15 n pen, 0C cursor stop, 0D new
line (scrolls at the bottom of the window), 09/0A bold on/off (fontc.bold_glyph), 06/07 clear, 0B/0E wait (draws the ▼ at the pen), fixed 8-px cells
for codes outside VWF, kana/kanji from the original font for Japanese bytes. One panel = what the window shows
at a wait, a clear or the end. Glyphs come from tools/font/font.txt (VWF bitmaps and advances) and the fixed
8x12 versions fontc.py compiles; placeholders ({ATK} [, {TGT} ], {N} ^/_) and name prefixes are drawn as boxes
as wide as the longest value the layout reserved for them.
Panel header: string ID, page, policy (kind, width x lines), how the page ends ("end+code wait": the print code
adds a wait, its cursor is drawn grey). Red: pixels beyond the window width, a line count above the window height,
or a layout error; yellow: a layout note (shown under the panel). One PNG per block (split into
numbered sheets when long), 2x scale; index.txt lists the sheet of every string.
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "font"))
import fontc  # noqa: E402
import textenc as T  # noqa: E402

BG, FRAME, INK, DIM = (0, 0, 0), (90, 90, 120), (255, 255, 255), (110, 110, 110)
RED, YEL, HEAD_BG, HEAD_FG = (255, 60, 60), (240, 200, 60), (28, 28, 44), (200, 200, 220)
PH_COL = {0x5B: (240, 200, 60), 0x5D: (120, 220, 120), 0x5E: (110, 170, 255), 0x5F: (110, 170, 255)}
PH_NAME = {0x5B: "ATK", 0x5D: "TGT", 0x5E: "N", 0x5F: "N", 0x5C: "?"}
PITCH = 16
SHEET_W, SHEET_H, SCALE, GAP = 780, 1400, 2, 6

_G = None


def _font():
    global _G
    if _G is None:
        g = fontc.load()
        src = open(fontc.SRC_ROM, "rb").read()
        vwf = {c: (gl.advance, gl.bits()) for c, gl in g.items()}
        bold = {c: fontc.bold_glyph(gl) for c, gl in g.items()}
        fixed = {}
        for c in range(0x20, 0x60):
            if c in g:
                fixed[c] = list(fontc.fixed_glyph(g[c])) if not g[c].keep else g[c].bits()[2:14]
        _G = {'vwf': vwf, 'bold': bold, 'fixed': fixed, 'rom': src}
    return _G


def _jp_glyph(c, kata):
    """Original font: (width, rows of ints, row count 12); kana 8 px, kanji 16 px (bits 15..0)."""
    rom = _font()['rom']
    if T.is_kanji(c):
        i = c - 0x60 if c < 0xA0 else 64 + c - 0xE0
        o = 0x6BAA0 + i * 24
        return 16, [(rom[o + r] << 8) | rom[o + 12 + r] for r in range(12)]
    if 0xA0 <= c <= 0xDF:
        o = 0x6B1A0 + ((64 if kata else 0) + c - 0xA0) * 12
        return 8, [rom[o + r] << 8 for r in range(12)]
    return 8, None


class Window:
    def __init__(self, width, lines):
        self.width, self.lines = width, lines
        self.rows = [[]]               # per row: list of ops (x, kind, data)
        self.row = 0
        self.scrolled = 0
        self.maxrows = 1
        self.dirty = False

    def put(self, op):
        self.rows[self.row].append(op)
        self.dirty = True

    def newline(self):
        self.row += 1
        self.rows.append([])
        if len(self.rows) > self.lines:
            self.rows.pop(0)
            self.row -= 1
            self.scrolled += 1
        self.maxrows = max(self.maxrows, self.row + 1)

    def clear(self):
        self.rows, self.row, self.scrolled = [[]], 0, 0

    def empty(self):
        return not any(self.rows)


def simulate(b, pol, ph, prefix_px=0):
    """Bytes -> list of (rows snapshot, end label, lines used since last clear/wait)."""
    width = pol.width if pol.kind != 'name' else max(8, T.measure(b, vwf=False, ph=ph) + 8)
    lines = max(1, pol.lines)
    w = Window(width, lines)
    out = []
    depth, pen, kata, dak, bold = 0, 0, False, None, False
    seg = 1
    if prefix_px:
        w.put((0, 'box', (prefix_px, (150, 150, 150), 'prefix')))
        pen = prefix_px

    def snap_now(end):
        out.append(([list(r) for r in w.rows], end, seg, width, lines))
        w.dirty = False

    i = 0
    while i < len(b):
        c = b[i]
        if c == T.VWF_ON:
            depth += 1
        elif c == T.VWF_OFF:
            depth = max(0, depth - 1)
            bold = bold and depth > 0
        elif c == T.BOLD_ON:
            bold = True
        elif c == T.BOLD_OFF:
            bold = False
        elif c == 0x01:
            kata = True
        elif c == 0x02:
            kata = False
        elif 0x10 <= c <= 0x1F:
            if c == T.PEN and i + 1 < len(b):
                pen = b[i + 1] - 0x20
            i += 2
            continue
        elif c == T.NL:
            w.newline()
            pen = 0
            seg += 1
        elif c in (T.CLR, T.CLR_P):
            if not w.empty() and w.dirty:          # after a wait the page was already shown
                snap_now('clear %02X' % c)
            w.clear()
            pen, seg = 0, 1
        elif c in (T.WAIT, T.WAIT2):
            x = T.snap(pen)
            w.put((x, 'cursor', 0x5C))
            snap_now('wait')
            w.rows[w.row].pop()
            seg = 0
        elif c == T.PAUSE:
            pass
        elif c == T.STOP:
            x = T.snap(pen)
            w.put((x, 'stop', 0x5B))
            pen = x + 8
        elif c in ph and c in PH_NAME:
            w.put((pen, 'box', (ph[c], PH_COL.get(c, YEL), PH_NAME[c])))
            pen += ph[c]
        elif c in (0xDE, 0xDF):
            dak = c
        elif c >= 0x20:
            if depth > 0 and c < 0x80 and c in _font()['vwf']:
                adv, bits = _font()['bold' if bold else 'vwf'][c]
                w.put((pen, 'vwf', bits))
                pen += adv
            elif c < 0x60:
                x = T.snap(pen)
                w.put((x, 'fixed', _font()['fixed'].get(c)))
                pen = x + 8
            else:
                gw, rows = _jp_glyph(c, kata)
                x = T.snap(pen)
                if dak is not None:
                    _, drows = _jp_glyph(dak, False)
                    if rows and drows:
                        rows = [r | d for r, d in zip(rows, drows)]
                    dak = None
                w.put((x, 'jp', (gw, rows)))
                pen = x + gw
        i += 1
    if not w.empty() and (w.dirty or not out):
        if pol.final_wait and pol.kind == 'reflow':
            w.put((T.snap(pen), 'gcursor', 0x5C))      # the wait the print code adds after the string (grey)
            snap_now('end+code wait')
        else:
            snap_now('end')
    return out


def _draw_rows(im, ox, oy, rows, width):
    px = im.load()
    W, H = im.size

    def plot(x, y, col):
        if 0 <= ox + x < W and 0 <= oy + y < H:
            px[ox + x, oy + y] = RED if x >= width else col

    d = ImageDraw.Draw(im)
    for r, ops in enumerate(rows):
        y0 = r * PITCH
        for x, kind, data in ops:
            if kind == 'vwf':
                for yy, bits in enumerate(data):
                    for xx in range(8):
                        if bits & (0x80 >> xx):
                            plot(x + xx, y0 + yy, INK)
            elif kind in ('fixed', 'cursor', 'stop', 'gcursor'):
                rows12 = data if kind == 'fixed' else _font()['fixed'].get(data)
                col = INK if kind in ('fixed', 'cursor') else DIM
                if rows12 is None:
                    d.rectangle([ox + x + 1, oy + y0 + 3, ox + x + 6, oy + y0 + 12], outline=RED)
                    continue
                for yy, bits in enumerate(rows12):
                    for xx in range(8):
                        if bits & (0x80 >> xx):
                            plot(x + xx, y0 + 2 + yy, col)
            elif kind == 'jp':
                gw, rows12 = data
                if rows12 is None:
                    d.rectangle([ox + x + 1, oy + y0 + 3, ox + x + gw - 2, oy + y0 + 12], outline=DIM)
                    continue
                for yy, bits in enumerate(rows12):
                    for xx in range(16):
                        if bits & (0x8000 >> xx):
                            plot(x + xx, y0 + 2 + yy, INK)
            elif kind == 'box':
                bw, col, name = data
                x1 = ox + x + bw - 1
                d.rectangle([ox + x, oy + y0 + 2, x1, oy + y0 + 13], outline=col)
                d.text((ox + x + 2, oy + y0 + 3), name, fill=col, font=ImageFont.load_default())
                if x + bw > width:
                    d.line([ox + width, oy + y0 + 2, x1, oy + y0 + 2], fill=RED)


def panel(sid, pi, npages, page, pol, notes, bad):
    rows, end, seg, width, lines = page
    nrows = max(lines, len(rows))
    hdr = 12
    foot = 11 if notes else 0
    pw = max(width, max((x + 8 for r in rows for x, _, _ in r), default=0)) + 8
    ph_ = hdr + nrows * PITCH + 6 + foot
    im = Image.new("RGB", (max(pw, 150), ph_), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width - 1, hdr - 1], fill=HEAD_BG)
    label = f"{sid} {pi + 1}/{npages} {pol.kind} {width}x{lines} {end}"
    over = len(rows) > lines or seg > lines
    d.text((2, 1), label, fill=RED if (bad or over) else YEL if notes else HEAD_FG, font=ImageFont.load_default())
    d.rectangle([2, hdr + 1, 2 + width + 3, hdr + 2 + lines * PITCH + 2], outline=FRAME)
    _draw_rows(im, 4, hdr + 3, rows, width)
    if notes:
        d.text((2, ph_ - foot), notes[:120], fill=RED if bad else YEL, font=ImageFont.load_default())
    return im


def render_all(out_dir, r):
    """Write <out_dir>/<block>_<n>.png and index.txt from textenc.build_all()'s result. Returns the PNG count."""
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".png") or f == "index.txt":
            os.remove(os.path.join(out_dir, f))
    meta_ph = r['meta']['ph']
    by_block = {}
    for (blk, idx), b in sorted(r['strings'].items()):
        sid = f"{blk:02X}:{idx:03d}"
        rec = r['info'].get(sid)
        if rec is None:
            continue
        by_block.setdefault(blk, []).append((sid, b, rec))
    index, nfiles = [], 0
    for blk, items in sorted(by_block.items()):
        panels = []
        for sid, b, rec in items:
            pol = rec['policy']
            ph = rec.get('ph') or meta_ph
            pages = simulate(b, pol, ph, rec.get('prefix', 0)) if b else []
            bad = bool(rec['errors'] or rec['warnings'])
            if not pages:
                pages = [([[]], 'empty', 1, max(pol.width, 8), max(1, pol.lines))]
            msgs = rec['errors'] + rec['warnings']
            for pi, pg in enumerate(pages):
                note = msgs[0] if msgs and pi == 0 else None
                panels.append((sid, panel(sid, pi, len(pages), pg, pol, note, bool(rec['errors']))))
        # flow layout into sheets
        sheets, cur, x, y, rowh = [], [], 0, 0, 0
        for sid, im in panels:
            if x and x + im.width > SHEET_W:
                x, y, rowh = 0, y + rowh + GAP, 0
            if y and y + im.height > SHEET_H:
                sheets.append((cur, y + rowh))
                cur, x, y, rowh = [], 0, 0, 0
            cur.append((sid, im, x, y))
            x += im.width + GAP
            rowh = max(rowh, im.height)
        if cur:
            sheets.append((cur, y + rowh))
        for si, (items_, h) in enumerate(sheets):
            sh = Image.new("RGB", (SHEET_W, h), (60, 60, 70))
            for sid, im, x, y in items_:
                sh.paste(im, (x, y))
            name = f"block_{blk:02X}_{si + 1:02d}.png"
            sh.resize((sh.width * SCALE, sh.height * SCALE), Image.NEAREST).save(os.path.join(out_dir, name), optimize=True)
            nfiles += 1
            seen = []
            for sid, _, _, _ in items_:
                if sid not in seen:
                    seen.append(sid)
            index += [f"{sid} {name}" for sid in seen]
    open(os.path.join(out_dir, "index.txt"), "w").write("\n".join(index) + "\n")
    return nfiles


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "build", "proof")
    res = T.build_all()
    print(render_all(out, res), "sheets in", out)
