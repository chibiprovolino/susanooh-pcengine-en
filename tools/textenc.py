#!/usr/bin/env python3
"""English text encoder, measurer and layout engine (module: text).

Turns translation/en_*.tsv into the byte strings of docs/design.md and lays them out
(word wrap, pagination, centering) per §7. Used by tools/mod_text.py (Huffman blocks) and reusable
by the ui module for translation/en_inline.tsv:

    import textenc as T
    W = T.widths()                       # 128 advance widths (index = byte code), font widths.json
    atoms = T.tokenize(text, block=None) # TSV markup -> atoms
    T.encode(atoms, vwf=True)            # atoms -> bytes (04 ... 05 added when vwf)
    T.encode_text(text, block=None)      # convenience: markup -> bytes, VWF decided by T.wants_vwf
    T.measure(atoms or bytes, vwf=True)  # pen position in px after printing (single line)
    T.wrap(text, width_px, ...)          # greedy pixel word wrap of plain prose -> list of lines
    T.build_all()                        # every (block, index) -> bytes, plus warnings/report

Byte table (docs/design.md §4): 00 end, 01/02 kana mode, 03 n continuation (made by mod_text),
04/05 VWF on/off, 06/07 clear, 0B wait, 0C cursor stop, 0D newline, 0E wait (I/II), 0F timed pause,
10-1F + argument, 15 n pen x = n-0x20. 0x20-0x5A ASCII, 0x61-0x7A a-z, 0x22 “ 0x7C ” 0x27 ’ 0x60 ‘
0x7B … 0x7D —. 0x5B {ATK}, 0x5D {TGT}, 0x5E {N} (block 22), 0x5F {N} (elsewhere), 0x5C {LABEL}.
09/0A bold on/off (VWF only): a double-quoted name or term ("Tech City") is drawn bold without its quote marks,
punctuation at the end of the span moves outside the bold run; quoted speech keeps its quotes. The choice per
span is translation/bold-spans.tsv. Glyph atoms of a bold run are ('G', code, 'b').
"""
import glob, json, os, re, sys, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script  # noqa: E402

TRANS = os.path.join(BASE, "translation")
WIDTHS_JSON = os.path.join(BASE, "tools", "font", "widths.json")

# ---------------------------------------------------------------------------------------------
# Constants
CUTSCENE_SPEED = 0x3C        # [13 64] in the cutscene blocks becomes [13 3C]
LINEBUF_MAX = 111            # bytes per fetch (line buffer $26FD-$276C, terminator at index <= 111)
BATTLE_MAX = 62              # battle copy $221F (63 allowed by code, 62 = margin)
CONT_BLOCK = 0x21            # continuation pieces (03 n)
CAPTION_BLOCKS = (0x17, 0x1A)  # printed by the bank 1 cutscene loop in window x3 y10 w11 h5 (b01 script 0x2FFD/0x31C5..)

VWF_ON, VWF_OFF = 0x04, 0x05
BOLD_ON, BOLD_OFF = 0x09, 0x0A   # no-ops in the original putc ($CB26); the VWF hook switches the bold set
NL, WAIT, WAIT2, PAUSE, CLR, CLR_P, STOP = 0x0D, 0x0B, 0x0E, 0x0F, 0x06, 0x07, 0x0C
PEN = 0x15
OPEN_DQ, CLOSE_DQ, APOS, OPEN_SQ, ELLIPSIS, EMDASH = 0x22, 0x7C, 0x27, 0x60, 0x7B, 0x7D

# PROVISIONAL width table (advance in px incl. 1 px spacing), used only while tools/font/widths.json
# (font module) does not exist. Shape: 5-6 px average, digits one shared advance (6).
_PROV = {' ': 4, '!': 2, '"': 4, '#': 8, '$': 8, '%': 8, '&': 6, "'": 2, '(': 3, ')': 3, '*': 6, '+': 6,
         ',': 3, '-': 5, '.': 2, '/': 6, ':': 2, ';': 3, '<': 6, '=': 6, '>': 6, '?': 6, '@': 8,
         'I': 4, 'M': 8, 'N': 7, 'W': 8, 'L': 5, 'T': 6, 'J': 5,
         'f': 4, 'i': 2, 'j': 3, 'l': 2, 'm': 8, 'r': 4, 't': 4, 'v': 6, 'w': 8, 'x': 6,
         '[': 8, '\\': 8, ']': 8, '^': 8, '_': 8}
PROVISIONAL_WIDTHS = [0] * 128
for _c in range(0x20, 0x80):
    _ch = chr(_c)
    if _ch in _PROV:
        _w = _PROV[_ch]
    elif _ch.isdigit():
        _w = 6
    elif 'A' <= _ch <= 'Z':
        _w = 6
    elif 'a' <= _ch <= 'z':
        _w = 5
    else:
        _w = 6
    PROVISIONAL_WIDTHS[_c] = _w
PROVISIONAL_WIDTHS[OPEN_DQ] = PROVISIONAL_WIDTHS[CLOSE_DQ] = 4
PROVISIONAL_WIDTHS[OPEN_SQ] = 2
PROVISIONAL_WIDTHS[ELLIPSIS] = 8
PROVISIONAL_WIDTHS[EMDASH] = 8

_WIDTHS = None
WIDTHS_SOURCE = None


def widths(path=WIDTHS_JSON, reload=False):
    """128 advance widths indexed by byte code. Reads tools/font/widths.json when present
    (list of 128, or dict code->width with keys as int, '0x41', '65' or a 1-char string,
    optionally under a 'widths' key); otherwise the PROVISIONAL table above."""
    global _WIDTHS, WIDTHS_SOURCE
    if _WIDTHS is not None and not reload:
        return _WIDTHS
    w = list(PROVISIONAL_WIDTHS)
    src = "PROVISIONAL (tools/font/widths.json missing)"
    if os.path.exists(path):
        d = json.load(open(path))
        if isinstance(d, dict) and "widths" in d:
            d = d["widths"]
        if isinstance(d, list):
            for i, v in enumerate(d[:128]):
                if v is not None:
                    w[i] = int(v)
        elif isinstance(d, dict):
            for k, v in d.items():
                if isinstance(k, str) and len(k) == 1 and not k.isdigit():
                    c = ord(k)
                elif isinstance(k, str) and k.lower().startswith("0x"):
                    c = int(k, 16)
                else:
                    try:
                        c = int(k)
                    except ValueError:
                        c = ord(k[0])
                if 0 <= c < 128 and v is not None:
                    w[c] = int(v if not isinstance(v, dict) else v.get("advance", v.get("width")))
        src = path
    _WIDTHS, WIDTHS_SOURCE = w, src
    return w


_BWIDTHS = None


def bold_widths(reload=False):
    """128 advances of the bold set (tools/font/fontc.bold_glyph: regular + 1 for glyphs with ink)."""
    global _BWIDTHS
    if _BWIDTHS is not None and not reload:
        return _BWIDTHS
    W = widths(reload=reload)
    try:
        sys.path.insert(0, os.path.join(BASE, "tools", "font"))
        import fontc
        bw = list(W)
        for c, a in fontc.bold_widths(fontc.load()).items():
            if 0 <= c < 128:
                bw[c] = a
    except Exception:                                       # no font source: same rule from the widths
        bw = [w + 1 if w and c != 0x20 else w for c, w in enumerate(W)]
    _BWIDTHS = bw
    return bw


# ---------------------------------------------------------------------------------------------
# Bold names and terms (translation/bold-spans.tsv: ID, span, class bold|speech|bold?|speech?, note)
BOLD_TSV = os.path.join(TRANS, "bold-spans.tsv")
_BOLD = None
BOLD_UNLISTED = []            # (sid, span, class used) of quoted spans missing from the file (build warns)


def bold_spans(path=BOLD_TSV, reload=False):
    global _BOLD
    if _BOLD is not None and not reload:
        return _BOLD
    d = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith("#") or line.startswith("ID\t"):
                continue
            p = line.split("\t")
            if len(p) >= 3:
                d[(p[0], p[1])] = p[2].strip()
    _BOLD = d
    return d


def auto_bold(span):
    """Rule of thumb for a span missing from bold-spans.tsv: speech when it has an ellipsis, sentence
    punctuation inside, a final ! or ?, or more than 5 words; otherwise a name/term (bold)."""
    if "..." in span or "\u2026" in span:
        return False
    core = re.sub(r"[.,!?;:]$", "", span)
    if re.search(r"[.!?]", core) or re.search(r"[!?]$", span):
        return False
    return len(core.replace("|", " ").split()) <= 5


def is_bold_span(sid, span):
    span = span.replace(NBSP, " ")
    cls = bold_spans().get((sid, span))
    if cls is None:
        b = auto_bold(span)
        if (sid, span) not in [(a, s_) for a, s_, _ in BOLD_UNLISTED]:
            BOLD_UNLISTED.append((sid, span, "bold" if b else "speech"))
        return b
    return cls.rstrip("?").strip().lower() == "bold"


# ---------------------------------------------------------------------------------------------
# Japanese source (original ROM), dictionary expanded
_JP = None


def jp_blocks():
    """{block: [bytes]} of the original script with 0x1F n expanded from block 0x19."""
    global _JP
    if _JP is None:
        rom = script.load(os.path.join(BASE, "rom", "Susanoo Densetsu (Japan).pce"))
        B = script.all_blocks(rom)
        names = B[0x19]

        def expand(s):
            o, i = [], 0
            while i < len(s):
                if s[i] == 0x1F:
                    o += expand(names[s[i + 1]])
                    i += 2
                else:
                    o.append(s[i])
                    i += 1
            return o
        _JP = {b: [bytes(expand(s)) for s in v] for b, v in B.items()}
    return _JP


# ---------------------------------------------------------------------------------------------
# TSV input
def load_tsv(pattern=None, include_inline=False):
    """{id: (english, note)} from translation/en_*.tsv (comment lines skipped; review files are not inputs)."""
    rows = {}
    files = sorted(glob.glob(pattern or os.path.join(TRANS, "en_*.tsv")))
    for f in files:
        if not include_inline and os.path.basename(f) == "en_inline.tsv":
            continue
        for line in open(f, encoding="utf-8"):
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith("#"):
                continue
            p = line.split("\t")
            rows[p[0]] = (p[1] if len(p) > 1 else "", p[2] if len(p) > 2 else "")
    return rows


# ---------------------------------------------------------------------------------------------
# Characters
KANJI_CODE = {k: c for c, k in script.KANJI_MAP.items()}
HIRA_CODE = {ch: 0xA0 + i for i, ch in enumerate(script.HIRA) if i < 0x3E}


def kana_codes(ch):
    """Hiragana (password data) -> byte codes, dakuten/handakuten as DE/DF prefix."""
    if ch in HIRA_CODE and ch != '　':
        return [HIRA_CODE[ch]]
    d = unicodedata.normalize("NFD", ch)
    if len(d) == 2 and d[0] in HIRA_CODE and d[1] in "゙゚":
        return [0xDE if d[1] == "゙" else 0xDF, HIRA_CODE[d[0]]]
    raise ValueError(f"no code for {ch!r}")


def arg_code(ch):
    """A character written as the argument of a 10-1F code."""
    if ch in KANJI_CODE:
        return KANJI_CODE[ch]
    if 0x20 <= ord(ch) < 0x7F:
        return ord(ch)
    k = kana_codes(ch)
    if len(k) != 1:
        raise ValueError(f"argument {ch!r} needs 2 bytes")
    return k[0]


# ---------------------------------------------------------------------------------------------
# Atoms: ('G', code) glyph | ('S',) space | ('NL',) author '|' | ('W',) ▼ | ('C', code) control
#        ('A', code, arg) 2-byte code | ('P', code, name) placeholder | ('CH',) » choice
class EncodeError(Exception):
    pass


ELISIONS = ("cause", "em", "til", "tis", "n", "round", "bout", "twas", "s")   # "s": a possessive after a code-printed name (13:010, INL:0D863, INL:0F371)


def tokenize(text, block=None, sid=None):
    """TSV markup -> atoms. sid (e.g. '00:002') enables bold names: a double-quoted span that
    bold-spans.tsv marks bold becomes ('G', code, 'b') atoms without its quotes."""
    atoms = []
    i, n = 0, len(text)
    pending = None          # index of an 'A' atom waiting for its argument
    in_pw = False

    def prev_opens():
        if not atoms:
            return True
        k = atoms[-1][0]
        if k in ('S', 'NL', 'W', 'C', 'A', 'CH'):
            return True
        return k == 'G' and atoms[-1][1] in (OPEN_DQ, OPEN_SQ, 0x28)

    while i < n:
        c = text[i]
        m = re.match(r"\[([0-9A-Fa-f]{2})\]", text[i:i + 4])
        if m:
            code = int(m.group(1), 16)
            i += 4
            if pending is not None:
                atoms[pending] = ('A', atoms[pending][1], code)
                pending = None
            elif 0x10 <= code <= 0x1F:
                atoms.append(('A', code, None))
                pending = len(atoms) - 1
            else:
                atoms.append(('C', code))
            continue
        if pending is not None:
            atoms[pending] = ('A', atoms[pending][1], arg_code(c))
            pending = None
            i += 1
            continue
        if c == '{':
            j = text.index('}', i)
            name = text[i + 1:j]
            code = {'ATK': 0x5B, 'TGT': 0x5D, 'LABEL': 0x5C,
                    'N': 0x5E if block == 0x22 else 0x5F}.get(name)
            if code is None:
                raise EncodeError(f"unknown placeholder {{{name}}}")
            atoms.append(('P', code, name))
            i = j + 1
            continue
        if text.startswith("...", i):
            atoms.append(('G', ELLIPSIS))
            i += 3
            continue
        if c == '|':
            atoms.append(('NL',))
        elif c == '▼':
            atoms.append(('W',))
        elif c == '»':
            atoms.append(('CH',))
        elif c == '%':
            if in_pw:
                atoms.append(('G', 0x25))
                in_pw = False
            # else: end of a choice, nothing (the 』 is dropped in English)
        elif c == '$':
            # password data (20:128): '$ ... %' is copied as one fixed-width run (kana verbatim, 24 ... 25)
            j = text.index('%', i)
            raw = [0x24]
            for ch in text[i + 1:j]:
                raw += [0x20] if ch == ' ' else [0x5F] if ch == '_' else kana_codes(ch)
            atoms.append(('RAW', bytes(raw + [0x25])))
            i = j + 1
            continue
        elif c == ' ':
            atoms.append(('S',))
        elif c == NBSP:
            atoms.append(('G', 0x20))           # no-break space (layout glue): a space byte inside a word
        elif c == '"':
            j = text.find('"', i + 1) if sid else -1
            if j > i and prev_opens() and is_bold_span(sid, text[i + 1:j]):
                m = re.fullmatch(r"(.*?)([.,!?;:]*)", text[i + 1:j], re.S)
                for a in tokenize(m.group(1), block):
                    atoms.append(('G', a[1], 'b') if a[0] == 'G' else a)
                atoms += tokenize(m.group(2), block)
                i = j + 1
                continue
            atoms.append(('G', OPEN_DQ if prev_opens() else CLOSE_DQ))
        elif c == "'":
            nxt = text[i + 1:i + 8]
            if prev_opens() and nxt[:1].isalpha() and not any(
                    nxt.lower().startswith(e) and not nxt[len(e):len(e) + 1].isalpha() for e in ELISIONS):
                atoms.append(('G', OPEN_SQ))
            else:
                atoms.append(('G', APOS))
        elif c in '—':
            atoms.append(('G', EMDASH))
        elif c == '…':
            atoms.append(('G', ELLIPSIS))
        elif 'a' <= c <= 'z':
            atoms.append(('G', ord(c)))
        elif 0x20 < ord(c) <= 0x5A or c in '_':
            if c in '[]^\\':
                raise EncodeError(f"literal {c!r} is a reserved placeholder byte")
            atoms.append(('G', ord(c)))
        elif c in KANJI_CODE:
            atoms.append(('G', KANJI_CODE[c]))
        else:
            try:
                for k in kana_codes(c):
                    atoms.append(('G', k) if k < 0xDE else ('C', k))
            except ValueError:
                raise EncodeError(f"no byte for {c!r} (U+{ord(c):04X})")
        i += 1
    if pending is not None:
        raise EncodeError("code 10-1F at the end without its argument")
    for a in atoms:
        if a[0] == 'A' and a[2] in (0x00, 0x03, 0x1F):
            raise EncodeError(f"argument {a[2]:02X} of [{a[1]:02X}] is forbidden (00/03/1F)")
    return atoms


def has_lower(text):
    t = re.sub(r"\[[0-9A-Fa-f]{2}\]|\{[A-Z]+\}", "", text)
    return any('a' <= c <= 'z' for c in t)


def has_latin(text):
    """Any A-Z/a-z outside [XX] codes (a kanji argument such as [13]朱 is not text)."""
    t = re.sub(r"\[[0-9A-Fa-f]{2}\]|\{[A-Z]+\}", "", text)
    return any('a' <= c.lower() <= 'z' for c in t)


# Names that must not be split at a line end (layout only; the byte is still 0x20).
NBSP = '\u00a0'
NO_BREAK = ("Susano Oh", "Demon King")


def glue(text):
    for n in NO_BREAK:
        text = text.replace(n, n.replace(' ', NBSP))
    return text


def wants_vwf(text):
    """§5 rule: strings with lowercase or prose get 04 ... 05; uppercase-only labels stay fixed.
    A fragment that is only the closing '.', '!' or '?' of a sentence printed after a VWF name (13:041,
    the equip refusal) is VWF too, or the fixed glyph would start a cell later ("Sword of Power .")."""
    return has_lower(text) or re.fullmatch(r"[.!?](\[[0-9A-F]{2}\])*", text) is not None


# ---------------------------------------------------------------------------------------------
# Encoding and measuring
def atom_bytes(a):
    k = a[0]
    if k == 'G':
        return [a[1]]
    if k == 'S':
        return [0x20]
    if k == 'NL':
        return [NL]
    if k == 'W':
        return [WAIT]
    if k == 'C':
        return [a[1]]
    if k == 'A':
        return [a[1], a[2]]
    if k == 'P':
        return [a[1]]
    if k == 'CH':
        return [0x20, STOP]
    if k == 'RAW':
        return list(a[1])
    raise ValueError(a)


def is_bold(a):
    return a[0] == 'G' and len(a) > 2


def _nl_or_space(a):
    return a[0] in ('S', 'NL', 'NLH') or (a[0] == 'C' and a[1] == NL)


def atoms_bytes(atoms):
    """Bytes of a list of atoms, with 09 ... 0A around bold runs (a run stays bold across the spaces
    and newlines between its words)."""
    out, on, n = [], False, len(atoms)
    for i, a in enumerate(atoms):
        if is_bold(a):
            if not on:
                out.append(BOLD_ON)
                on = True
        elif on:
            keep = False
            if _nl_or_space(a):
                j = i + 1
                while j < n and _nl_or_space(atoms[j]):
                    j += 1
                keep = j < n and is_bold(atoms[j])
            if not keep:
                out.append(BOLD_OFF)
                on = False
        out += atom_bytes(a)
    if on:
        out.append(BOLD_OFF)
    return out


def encode(atoms, vwf=True):
    body = atoms_bytes(atoms)
    if vwf:
        body = [VWF_ON] + body + [VWF_OFF]
    return bytes(body)


def encode_text(text, block=None, vwf=None):
    """Markup -> bytes (no terminator, no layout). vwf=None decides by wants_vwf()."""
    atoms = tokenize(text, block)
    if vwf is None:
        vwf = wants_vwf(text)
    return encode(atoms, vwf)


def snap(px):
    return (px + 7) & ~7


def is_kanji(code):
    return 0x60 <= code <= 0x9F or 0xE0 <= code <= 0xE8


def glyph_adv(code, pen, vwf, W=None, bold=False):
    W = W or widths()
    if vwf and code < 0x80:
        return pen + (bold_widths()[code] if bold else W[code])
    if is_kanji(code) and not (vwf and code < 0x80):
        return snap(pen) + 16
    return snap(pen) + 8


def measure(seq, vwf=True, pen=0, ph=None):
    """Pen x in px after printing seq (atoms or bytes) on one line. ph: {placeholder code: px}."""
    W = widths()
    ph = ph or {}
    if isinstance(seq, (bytes, bytearray)):
        i, b = 0, seq
        depth = 1 if vwf else 0
        bold = False
        while i < len(b):
            c = b[i]
            if c == VWF_ON:
                depth += 1
            elif c == VWF_OFF:
                depth = max(0, depth - 1)
                bold = bold and depth > 0
            elif c == BOLD_ON:
                bold = True
            elif c == BOLD_OFF:
                bold = False
            elif 0x10 <= c <= 0x1F:
                if c == PEN:
                    pen = b[i + 1] - 0x20
                i += 2
                continue
            elif c == STOP:
                pen = snap(pen) + 8
            elif c in ph:
                pen += ph[c]
            elif c >= 0x20 and c not in (0xDE, 0xDF):
                pen = glyph_adv(c, pen, depth > 0, W, bold)
            i += 1
        return pen
    for a in seq:
        k = a[0]
        if k == 'G':
            pen = glyph_adv(a[1], pen, vwf, W, len(a) > 2)
        elif k == 'S':
            pen = pen + W[0x20] if vwf else snap(pen) + 8
        elif k == 'P':
            pen += ph.get(a[1], 0) if vwf else snap(pen) + 8
        elif k == 'CH':
            pen = (pen + W[0x20] if vwf else snap(pen) + 8)
            pen = snap(pen) + 8
        elif k == 'C' and a[1] == STOP:
            pen = snap(pen) + 8
        elif k == 'A' and a[1] == PEN:
            pen = a[2] - 0x20
        elif k == 'RAW':
            pen = measure(a[1], vwf=False, pen=snap(pen))
    return pen


def wrap(text, width, first_width=None, block=None):
    """Greedy pixel word wrap of plain prose (no codes): returns a list of line strings."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w) if cur else w
        lim = first_width if (first_width and not lines) else width
        if cur and measure(tokenize(t, block)) > lim:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def _text_of(atoms):
    """Readable text of layout atoms (for reports and proofs)."""
    s = []
    for a in atoms:
        if a[0] == 'G':
            c = a[1]
            s.append({OPEN_DQ: '\u201c', CLOSE_DQ: '\u201d', APOS: '\u2019', OPEN_SQ: '\u2018', ELLIPSIS: '\u2026',
                      EMDASH: '\u2014'}.get(c, chr(c) if c < 0x80 else script.code_name(c)))
        elif a[0] == 'S':
            s.append(' ')
        elif a[0] == 'P':
            s.append('{' + a[2] + '}')
        elif a[0] == 'CH':
            s.append(' \u25b6')
        elif a[0] == 'C' and a[1] == STOP:
            s.append('\u25b6')
    return "".join(s)


# ---------------------------------------------------------------------------------------------
# Layout (docs/design.md §6)
SENT_END = {ord('.'), ord('!'), ord('?'), ELLIPSIS, CLOSE_DQ}
WAIT_CURSOR = (WAIT, WAIT2)          # these draw a ▼ at the pen (needs one free cell)
BREAKS = (WAIT, WAIT2, PAUSE)
GLUE_CODES = (STOP, 0x01, 0x02, 0xDE, 0xDF)


class Policy:
    """How one string is laid out. kind: reflow (prose, auto pages), caption (centred prose),
    keep (author breaks kept, overflowing lines wrapped), battle, name (no layout)."""

    def __init__(self, kind, width=184, lines=4, clear=CLR_P, final_wait=True, center=False,
                 max_bytes=None, split=True, window="", area=None):
        self.kind, self.width, self.lines, self.clear = kind, width, lines, clear
        self.area = area or width               # printable px of the window (centred text may wrap narrower)
        self.final_wait, self.center, self.max_bytes, self.split = final_wait, center, max_bytes, split
        self.window = window

    def __repr__(self):
        return f"{self.kind} {self.width}px x {self.lines}"


def jp_page_cells(b):
    """Widest line (8-px cells) of a JP string and whether it uses the 07 clear."""
    mx, cur, i = 0, 0, 0
    while i < len(b):
        c = b[i]
        if 0x10 <= c <= 0x1F:
            i += 2
            continue
        if c in (NL, CLR, CLR_P):
            cur = 0
        elif c == STOP:
            cur += 1
        elif c >= 0x20 and c not in (0xDE, 0xDF):
            cur += 2 if is_kanji(c) else 1
        mx = max(mx, cur)
        i += 1
    return mx, CLR_P in b


# Portrait windows: the text area is 23 cells (184 px, x 24-207) and the portrait starts at x 208; 180 px keeps a
# 4 px gap so the last glyph never touches the portrait (seen in the emulator), at no cost in pages.
NPC_W = 180


MENU_13 = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0B, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x1A, 0x1B)
NAME_PREFIX_13 = (0x08, 0x0A, 0x13, 0x14, 0x15, 0x1C, 0x1D, 0x1E, 0x25)
# Battle sets whose attacker can only be a monster (beam of light, burning rock, crimson flames):
# their {TGT} is a party member, so the widest party name applies instead of the widest enemy name.
MONSTER_ONLY_22 = tuple(range(136, 148))


def policy(block, idx, en, jp):
    """Window and layout per string."""
    if block <= 0x0D:
        return Policy('reflow', NPC_W, 4, CLR_P, window="NPC: b05:D470 FDB8 x1 y9 w15 h5, portrait, code adds 0B")
    if block == 0x0E:
        return Policy('keep', 144, 13, CLR, final_wait=False,
                      window="inn/shop/tavern panel b07:C081 x6 y1 w10 h14 (18x13 cells), loop b07:C182 (+CHKS)")
    if block == 0x10:
        return Policy('keep', 144, 13, CLR, final_wait=False, window="item description, shop panel (b07:C884)")
    if block in (0x0F, 0x11, 0x12, 0x14, 0x15, 0x16):
        return Policy('name', 0, 1, None, final_wait=False, split=False, window="name field (ui module checks)")
    if block == 0x13:
        if idx in (0x20, 0x21, 0x22, 0x23):
            return Policy('keep', 176, 4, CLR, final_wait=False, window="save, b07:C67B x2 y3 w12 h6 (22 cells)")
        if idx in (0x2B, 0x2C, 0x2D, 0x2E):
            return Policy('reflow', NPC_W, 5, CLR_P, window="Kubira, b07:C7D6 x1 y3 w15 h6 (28x5), 07-safe")
        if idx in MENU_13:
            return Policy('keep', 240, 1, None, final_wait=False, split=False, window="menu line x0 y1 w16 h2")
        return Policy('keep', 224, 2, None, final_wait=False, window="message x1 y11/12 w15 (28 cells)")
    if block in CAPTION_BLOCKS:
        # The window's 160 px area is screen x 56-215, 8 px right of the screen centre (the JP centred its
        # captions on the screen with spaces). Wrap and centre on the first 144 px (x 56-199, symmetric about
        # the screen centre) so every line can be centred on the screen.
        # Block 17 (opening) pages hold 3 lines: the window's 4th line (screen y 218-233) sits in the bottom
        # overscan on TVs/emulators showing 224 lines. The window cannot move up: row 9
        # overlaps the picture.
        return Policy('caption', 144, 3 if block == 0x17 else 4, CLR, final_wait=False, center=True, area=160,
                      window="cutscene captions, bank 1 loop, script window x3 y10 w11 h5 (20x4)")
    if block == 0x22:
        return Policy('battle', 224, 2, None, final_wait=False, max_bytes=BATTLE_MAX, split=False,
                      window="battle b06 x1 y11 w15 h3 (28x2), copy to $221F")
    if block == 0x19:
        return Policy('name', 0, 1, None, final_wait=False, split=False, window="dictionary (JP kept)")
    if block in (0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20):
        jcells, j07 = jp_page_cells(jp) if jp is not None else (0, True)
        if jcells > 23 and not j07 and '[07]' not in en:
            return Policy('reflow', 224, 4, CLR, window="event, JP > 23 cells so no portrait: 224 px, clear 06")
        return Policy('reflow', NPC_W, 4, CLR_P, window="event: b02:C17E/C1BA FDB8 x1 y9 w15 h5, portrait-safe")
    return Policy('keep', 224, 4, None, final_wait=False, window="unknown")


def classify_newlines(atoms, reflow):
    """'|' -> ('NLH',) hard break, or a space (re-flowed prose).
    '▼|' / '▼ |' fold into the wait (the wait brings its own newline); spaces after the fold are an indent.
    '▼ text': the space is only a separator and is dropped. ' | ' (spaces around): hard break, spaces dropped.
    '|  text' (no space before): the spaces after it are an indent and stay."""
    out = []
    n = len(atoms)
    i = 0
    while i < n:
        a = atoms[i]
        if a[0] == 'W':
            out.append(a)
            j = i + 1
            while j < n and atoms[j][0] == 'S':
                j += 1
            if j < n and atoms[j][0] == 'NL':
                i = j + 1                        # fold; spaces after the '|' stay (indent)
            else:
                i = j                            # separator spaces dropped
            continue
        if a[0] != 'NL':
            out.append(a)
            i += 1
            continue
        prev = atoms[i - 1] if i > 0 else None
        nxt = atoms[i + 1] if i + 1 < n else None
        hard = True
        if reflow and prev is not None and nxt is not None:
            hard = (prev[0] in ('NL', 'C', 'A', 'W', 'CH', 'S', 'RAW') or nxt[0] in ('NL', 'C', 'A', 'W', 'CH', 'S', 'RAW')
                    or (nxt[0] == 'G' and nxt[1] in (OPEN_DQ, OPEN_SQ, 0x2A)))
        if not hard:
            out.append(('S',))
            i += 1
            continue
        spaced = prev is not None and prev[0] == 'S'
        while spaced and out and out[-1][0] == 'S':
            out.pop()
        out.append(('NLH',))
        i += 1
        if spaced:
            while i < n and atoms[i][0] == 'S':
                i += 1
    return out


def structure(atoms):
    """atoms -> nodes: ('para', words, lead_spaces) | ('nl',) | ('wait', code, marker) | ('clear', code) | ('ctl', atom).
    A word = {'a': atoms, 'sp': spaces before it}. Codes without layout effect stick to the next/previous word."""
    nodes, words, cur, sp, lead, pend = [], [], [], 0, 0, []

    def end_word():
        nonlocal cur, sp
        if cur:
            words.append({'a': pend_take() + cur, 'sp': sp})
            cur, sp = [], 0

    def pend_take():
        nonlocal pend
        p, pend = pend, []
        return p

    def end_para():
        nonlocal words, lead
        end_word()
        if pend and words:
            words[-1]['a'] += pend_take()
        if words or lead:
            nodes.append(('para', words, lead))
        for a in pend_take():
            nodes.append(('ctl', a))
        words, lead = [], 0

    for a in atoms:
        k = a[0]
        if k == 'S':
            if cur:
                end_word()
                sp = 1
            elif words:
                sp += 1
            else:
                lead += 1
        elif k in ('G', 'P', 'CH', 'RAW') or (k == 'C' and a[1] in GLUE_CODES):
            cur.append(a)
        elif k == 'A' and a[1] != PEN:
            if cur:
                cur.append(a)
            elif words and sp == 0:
                words[-1]['a'].append(a)
            else:
                pend.append(a)
        elif k == 'NLH':
            end_para()
            nodes.append(('nl',))
        elif k == 'W':
            end_para()
            nodes.append(('wait', WAIT, True))
        elif k == 'C' and a[1] in BREAKS:
            end_para()
            nodes.append(('wait', a[1], False))
        elif k == 'C' and a[1] in (CLR, CLR_P):
            end_para()
            nodes.append(('clear', a[1]))
        else:
            end_para()
            nodes.append(('ctl', a))
    end_para()
    return nodes


def _first_glyph(words):
    for w in words:
        for a in w['a']:
            if a[0] == 'G':
                return a[1]
            if a[0] in ('P', 'CH'):
                return None
    return None


SENT_STOP = {ord('.'), ord('!'), ord('?')}
NO_BREAK_AFTER = ('Mr', 'Mrs', 'Dr', 'St', 'Mt')


def _ends_sentence(w, nxt):
    """A word ends a sentence when its last glyph is . ! ? (optionally inside a closing quote)
    and the next word does not start in lowercase (so "...," or "Mr." do not break)."""
    g = [a[1] for a in w['a'] if a[0] == 'G']
    if not g:
        return False
    if g[-1] in (CLOSE_DQ, APOS) and len(g) > 1:
        g = g[:-1]
    if g[-1] not in SENT_STOP:
        return False
    if ''.join(chr(c) for c in g[:-1] if 0x20 < c < 0x7B) in NO_BREAK_AFTER:
        return False
    ng = _first_glyph([nxt])
    return ng is None or not (0x61 <= ng <= 0x7A)


def split_sentences(nodes):
    """In dialogue a new sentence starts on a new line (like the Japanese).
    Split each prose paragraph after . ! ? into separate paragraphs joined by a newline.
    A '*' speaker paragraph keeps its hanging indent on the following sentences."""
    out = []
    for node in nodes:
        if node[0] != 'para' or not node[1]:
            out.append(node)
            continue
        words, lead = node[1], node[2]
        star = _first_glyph(words) == 0x2A
        cur, first = [], True
        for i, w in enumerate(words):
            if not cur:
                w = dict(w, sp=0)
            cur.append(w)
            if i + 1 < len(words) and _ends_sentence(w, words[i + 1]):
                out.append(('para', cur, lead if first else (1 if star else 0)))
                out.append(('nl',))
                cur, first = [], False
        if cur:
            out.append(('para', cur, lead if first else (1 if star else 0)))
    return out


class Layouter:
    def __init__(self, sid, pol, ph, vwf=True, prefix_px=0):
        self.sid, self.pol, self.ph, self.vwf = sid, pol, ph, vwf
        self.W = widths()
        self.sp = self.W[0x20] if vwf else 8
        self.prefix_px = prefix_px
        self.out, self.pages, self.rows = [], [], []
        self.errors, self.warnings, self.auto = [], [], 0
        self.seg, self.pend, self.need_nl, self.row_empty = 1, 0, False, True
        self.paginate = pol.kind in ('reflow', 'caption')
        self.width = pol.width
        self.no_auto = False

    # -- measuring
    def m(self, atoms, pen=0):
        return measure(atoms, self.vwf, pen, self.ph)

    def wrap(self, words, lead, cont, width, keep_sp, first_pen=0):
        lines = []
        cur = {'a': list(lead), 'px': self.m(lead, first_pen), 'n': 0, 'w0': 0}
        for i, w in enumerate(words):
            ns = (max(1, w['sp']) if keep_sp else 1) if cur['n'] else 0
            sa = [('S',)] * ns
            px = self.m(sa + w['a'], cur['px'])
            if cur['n'] and px > width:
                lines.append(cur)
                cur = {'a': list(cont) + w['a'], 'px': self.m(w['a'], self.m(cont)), 'n': 1, 'w0': i}
            else:
                cur['a'] += sa + w['a']
                cur['px'] = px
                cur['n'] += 1
        lines.append(cur)
        return lines

    def wrap_last(self, words, lead, cont, width, keep_sp, last_limit, first_pen=0):
        """Wrap; the last line must leave room for the ▼ (last_limit). Captions are balanced
        (the narrowest width that keeps the same number of lines), since they are centred."""
        lines = self.wrap(words, lead, cont, width, keep_sp, first_pen)
        if self.pol.kind == 'caption' and len(lines) > 1:
            lo = max(self.m(w['a']) for w in words)
            hi = width
            while lo < hi:
                mid = (lo + hi) // 2
                if len(self.wrap(words, lead, cont, mid, keep_sp, first_pen)) <= len(lines):
                    hi = mid
                else:
                    lo = mid + 1
            bal = self.wrap(words, lead, cont, hi, keep_sp, first_pen)
            if len(bal) == len(lines) and (bal[-1]['px'] <= last_limit or lines[-1]['px'] > last_limit):
                lines = bal
        if last_limit < width and lines[-1]['px'] > last_limit and lines[-1]['n'] > 1:
            head = self.wrap(words[:-1], lead, cont, width, keep_sp, first_pen)
            w = words[-1]
            head.append({'a': list(cont) + w['a'], 'px': self.m(w['a'], self.m(cont)), 'n': 1,
                         'w0': len(words) - 1})
            lines = head
        return lines

    # -- emission
    def emit_break(self, allow_page=True):
        """Resolve pending newlines before text: 0D x n, or an automatic page break."""
        if self.pend:
            if self.paginate and allow_page and self.seg + self.pend > self.pol.lines and not self.no_auto:
                self.page_break()
            else:
                self.out += [('C', NL)] * self.pend
                self.seg += self.pend
                if self.seg > self.pol.lines and self.pol.kind not in ('name',):
                    self.warnings.append(f"{self.seg} lines since the last wait/clear (window {self.pol.lines})")
                for _ in range(self.pend - 1):
                    self.rows.append((0, '', self.width))
            self.pend = 0
            self.row_empty = True

    def page_break(self):
        self.out += [('C', WAIT), ('C', self.auto_clear)]
        self.close_page('auto %02X' % self.auto_clear)
        self.seg, self.pend, self.row_empty = 1, 0, True
        self.auto += 1
        self.width = self.pol.width

    def close_page(self, end):
        if self.rows:
            self.pages.append({'lines': self.rows, 'end': end})
        self.rows = []

    def emit_line(self, L, wait_after=False):
        self.emit_break()
        if self.seg == 0:
            self.seg = 1
        atoms = L['a']
        px = L['px'] + (self.prefix_px if not self.out_has_text() and not L.get('pre') else 0)
        area = self.pol.area if self.width == self.pol.width else self.width
        if self.pol.center:
            # centre the ink: the advance ends with the glyph's 1 px spacing, so the ink is px - 1 wide
            x = max(0, (self.width - (px - 1)) // 2)
            if wait_after:
                while x > 0 and snap(x + px) + 8 > area:
                    x -= 1
            atoms = [('A', PEN, 0x20 + x)] + atoms
            px += x
        self.out += atoms
        if self.pol.center and L['px'] > self.width:
            self.warnings.append(f"line {L['px']} px wider than the {self.width} px centring width: "
                                 f"{_text_of(L['a'])!r}")
        lim = area - 8 if wait_after else area
        if px > lim:
            what = "leaves no cell for the ▼" if px <= area else "is too wide"
            msg = f"line {px} px {what} ({area} px window): {_text_of(L['a'])!r}"
            (self.errors if px > area else self.warnings).append(msg)
        self.rows.append((px, _text_of(L['a']), area))
        self.row_empty = False
        self._has_text = True

    def out_has_text(self):
        return getattr(self, '_has_text', False)

    # -- main
    def run(self, nodes, clear_conv):
        pol = self.pol
        self.auto_clear = clear_conv
        star_hang = None
        if pol.kind in ('reflow', 'caption'):
            nodes = split_sentences(nodes)
        for ni, node in enumerate(nodes):
            nxt = nodes[ni + 1] if ni + 1 < len(nodes) else None
            kind = node[0]
            if kind in ('nl', 'clear', 'wait'):
                self.prefix_px = 0                  # the code-printed prefix is on a line above
            if kind == 'nl':
                self.pend += 1
                continue
            if kind == 'clear':
                self.pend = 0                       # a newline right before a clear only risks a scroll
                self.out.append(('C', node[1]))
                self.close_page('clear %02X' % node[1])
                self.seg, self.row_empty, self.need_nl = 1, True, False
                self.width = pol.width
                continue
            if kind == 'wait':
                code, marker = node[1], node[2]
                self.emit_break(allow_page=False)
                self.out.append(('C', code))
                if code in WAIT_CURSOR and self.rows and self.rows[-1][0] > self.rows[-1][2] - 8:
                    self.warnings.append(f"no cell left for the ▼ after {self.rows[-1][1]!r}")
                self.close_page({WAIT: 'wait', WAIT2: 'wait', PAUSE: 'pause'}[code])
                self.seg = 0
                follows_text = nxt is not None and nxt[0] == 'para'
                self.pend = 1 if (marker and follows_text) else 0
                continue
            if kind == 'ctl':
                self.emit_break(allow_page=False)
                self.out.append(node[1])
                continue
            # paragraph
            words, lead = node[1], node[2]
            if not words:
                if lead and pol.kind not in ('reflow', 'caption'):
                    self.emit_break()
                    self.out += [('S',)] * lead
                continue
            fg = _first_glyph(words)
            keep_sp = pol.kind not in ('reflow', 'caption')
            lead_a, cont_a = [], []
            if pol.kind == 'caption':
                lead = 0
            if fg == 0x2A:                         # '*' speaker line: hanging indent
                w0 = words[0]['a']
                star_only = len([a for a in w0 if a[0] == 'G']) == 1 and len(words) > 1
                star_px = self.m([a for a in w0 if a[0] == 'G'][:1])
                hang = (self.m(w0) + self.sp * max(1, words[1]['sp'])) if star_only else star_px
                star_hang = hang
                lead_a = [('S',)] * lead
                cont_a = [('A', PEN, 0x20 + hang + self.m(lead_a))]
            elif lead:
                if pol.kind == 'reflow' and star_hang is not None:
                    lead_a = [('A', PEN, 0x20 + star_hang)]
                else:
                    lead_a = [('S',)] * lead
                cont_a = list(lead_a) if lead_a[0][0] == 'S' else lead_a
                if cont_a and cont_a[0][0] == 'S':
                    cont_a = [('A', PEN, 0x20 + self.m(lead_a))]
            wait_after = (nxt is None and pol.final_wait) or (
                nxt is not None and nxt[0] == 'wait' and nxt[1] in WAIT_CURSOR)
            # a prefix printed by code before the string (name, item, time of day) shares the first line
            first_pen = self.prefix_px if (self.prefix_px and not self.out_has_text()) else 0
            if self.paginate and not self.no_auto:
                self.layout_paginated(words, lead_a, cont_a, keep_sp, wait_after)
            else:
                lines = self.wrap_last(words, lead_a, cont_a, self.width, keep_sp,
                                       self.width - 8 if wait_after else self.width, first_pen)
                if first_pen:
                    lines[0]['pre'] = True
                for li, L in enumerate(lines):
                    if li:
                        self.pend += 1
                    self.emit_line(L, wait_after and li == len(lines) - 1)
        # trailing newlines are meaningful (the next string continues below)
        if self.pend:
            self.out += [('C', NL)] * self.pend
            self.pend = 0
        self.close_page('end')
        return self.out

    def layout_paginated(self, words, lead_a, cont_a, keep_sp, wait_after):
        N, width = self.pol.lines, self.width
        ws = list(words)
        first = True
        while ws:
            lead = lead_a if first else cont_a
            # rows available on this page for this paragraph
            if self.pend:
                avail = N - self.seg - self.pend + 1
            elif self.seg == 0:
                avail = N
            else:
                avail = N - self.seg + (1 if self.row_empty else 0)
            has_content = self.seg > 1 or (self.seg == 1 and not self.row_empty) or (self.seg >= 1 and self.pend)
            last_lim = width - 8 if wait_after else width
            lines = self.wrap_last(ws, lead, cont_a, width, keep_sp, last_lim)
            if len(lines) <= avail:
                self.put_lines(lines, wait_after)
                return
            if avail <= 0 or (first and has_content and avail < N and (
                    len(lines) <= N or self.best_cut(ws, lead, cont_a, keep_sp, avail) is None)):
                # break the page before this paragraph
                if self.out_has_text():
                    self.pend = 0
                    self.page_break()
                    continue
            cap = max(1, avail)
            cut = self.best_cut(ws, lead, cont_a, keep_sp, cap)
            if cut is None:
                cut = self.hard_cut(ws, lead, cont_a, keep_sp, cap)
            chunk = self.wrap_last(ws[:cut], lead, cont_a, width, keep_sp, width - 8)
            self.put_lines(chunk, True)
            self.page_break()
            ws = ws[cut:]
            first = False

    def fits(self, ws, lead, cont, keep_sp, cap):
        L = self.wrap_last(ws, lead, cont, self.width, keep_sp, self.width - 8)
        return len(L) <= cap, L

    def best_cut(self, ws, lead, cont, keep_sp, cap):
        minline = self.pol.lines - 1 if self.pol.lines >= 3 else 1   # a sentence end, but keep pages full
        best = None
        for k in range(1, len(ws)):
            g = [a for a in ws[k - 1]['a'] if a[0] == 'G']
            if not g or g[-1][1] not in SENT_END:
                continue
            ok, L = self.fits(ws[:k], lead, cont, keep_sp, cap)
            if not ok:
                break
            if len(L) >= min(minline, cap):
                best = k
        return best

    def hard_cut(self, ws, lead, cont, keep_sp, cap):
        k = 1
        while k < len(ws) and self.fits(ws[:k + 1], lead, cont, keep_sp, cap)[0]:
            k += 1
        return k

    def put_lines(self, lines, wait_after):
        for li, L in enumerate(lines):
            if li:
                self.pend += 1
            self.emit_line(L, wait_after and li == len(lines) - 1)


def clear_convention(atoms, pol):
    """Clear code for automatic page breaks: the string's own 06/07, else the window default.
    224-px pages always clear with 06 (07 keeps columns 23-27)."""
    if pol.width > 184:
        return CLR
    codes = {a[1] for a in atoms if a[0] == 'C' and a[1] in (CLR, CLR_P)}
    if CLR_P in codes:
        return CLR_P
    if CLR in codes:
        return CLR
    return pol.clear if pol.clear is not None else CLR_P


# Strings whose author line breaks are a list and must not be re-flowed (markup-only | added in the TSV).
KEEP_BREAKS = {'20:127'}


def layout_text(sid, text, pol, ph, vwf=True, prefix_px=0):
    """TSV markup -> (body atoms, Layouter with pages/errors/warnings). Names in NO_BREAK are kept on one
    line unless that costs a line, a page or a fit (then the plain layout is used)."""
    if glue(text) == text:
        return _layout_text(sid, text, pol, ph, vwf, prefix_px)
    g = _layout_text(sid, glue(text), pol, ph, vwf, prefix_px)
    p = _layout_text(sid, text, pol, ph, vwf, prefix_px)

    def cost(r):
        L = r[1]
        return (len(L.errors), L.auto, len(L.warnings), sum(len(pg['lines']) for pg in L.pages), len(L.pages))
    return g if cost(g) <= cost(p) else p


def _layout_text(sid, text, pol, ph, vwf=True, prefix_px=0):
    block = int(sid.split(':')[0], 16)
    atoms = tokenize(text, block, sid=sid)
    if block in CAPTION_BLOCKS:
        atoms = [('A', 0x13, CUTSCENE_SPEED) if (a[0] == 'A' and a[1] == 0x13 and a[2] == 0x64) else a
                 for a in atoms]
    if pol.kind == 'caption' or sid in KEEP_BREAKS:
        # the translator's own line breaks first; re-flow only when they do not fit
        nodes = structure(classify_newlines(atoms, False))
        Lk = Layouter(sid, pol, ph, vwf, prefix_px)
        Lk.no_auto = True
        out = Lk.run(nodes, clear_convention(atoms, pol))
        if (not Lk.errors and not Lk.warnings and Lk.auto == 0) or sid in KEEP_BREAKS:
            return out, Lk
    reflow = pol.kind in ('reflow', 'caption') and not any(a[0] == 'CH' for a in atoms)
    eff = pol
    if pol.kind in ('reflow', 'caption') and not reflow:
        eff = Policy('keep', pol.area, pol.lines, pol.clear, pol.final_wait, False, pol.max_bytes, pol.split,
                     pol.window + " (choices: author breaks kept)")
    atoms = classify_newlines(atoms, reflow)
    nodes = structure(atoms)
    L = Layouter(sid, eff, ph, vwf, prefix_px)
    out = L.run(nodes, clear_convention(atoms, eff))
    return out, L


def body_bytes(atoms, vwf):
    """Layout atoms -> bytes with 04/05 (and 09/0A around bold runs); a password run (0x24..0x25) is
    printed fixed with 02 before it."""
    b = atoms_bytes(atoms)
    if not vwf:
        return bytes(b)
    if 0x24 in b and 0x25 in b:
        i = b.index(0x24)
        return bytes([VWF_ON] + b[:i] + [VWF_OFF, 0x02] + b[i:])
    return bytes([VWF_ON] + b + [VWF_OFF])


def check_bytes(sid, b, errors):
    """No 00 inside, no 1F, no 03 code, arguments never 00/03/1F."""
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x00:
            errors.append(f"00 inside the string at {i}")
        elif c in (0x1F, 0x03):
            errors.append(f"code {c:02X} at {i}")
        elif 0x10 <= c <= 0x1E:
            if i + 1 >= len(b):
                errors.append(f"[{c:02X}] without argument at the end")
            elif b[i + 1] in (0x00, 0x03, 0x1F):
                errors.append(f"[{c:02X}] argument {b[i + 1]:02X}")
            i += 2
            continue
        elif c in (0xDE, 0xDF) and (i + 1 >= len(b) or b[i + 1] < 0xA0):
            errors.append(f"dakuten prefix {c:02X} at {i} without kana")
        i += 1


# ---------------------------------------------------------------------------------------------
# Inn wake-up line (b07 $C5FB): 0E:029 "*", then the time of day of the next period, then 0E:015.
# 0E:015 is written "When {TIME} comes,|I'll call you." The text up to the first '|' after {TIME}, with
# the time word in lowercase (INL:0E1D8-0E1E3), forms the inn's own time table (mod_ui, region ui.b07);
# the rest (from the '|') is the string 0E:015 itself. 0E:015 is printed through b07 $C16A, which re-opens
# the panel ($C081 -> $CAA9) and so resets the VWF pen to a cell boundary: a sentence that went on
# mid-line would lose its sub-cell offset (seen: "When daycomes"), so the cut is at a line break.
INN_TIME_SID = "0E:015"
TIME_IDS = ("INL:0E1D8", "INL:0E1DC", "INL:0E1E0", "INL:0E1E3")
# The inn's copy only: 昼 (INL:0E1DC) is "Day" in the status window, but "When day comes," reads badly;
# the wake-up line says "When noon comes,".
INN_WORDS = {"day": "noon"}


def inn_time_texts(rows=None, inline=None):
    """(4 table texts, 0E:015 text) when 0E:015 uses {TIME}, else None."""
    rows = rows if rows is not None else load_tsv()
    inline = inline if inline is not None else load_tsv(os.path.join(TRANS, "en_inline.tsv"), include_inline=True)
    t = rows.get(INN_TIME_SID, ("", ""))[0]
    if "{TIME}" not in t:
        return None
    before, after = t.split("{TIME}", 1)
    cut = after.find("|")
    if cut < 0:                                   # no line break: the table string ends with the space
        cut = 1 if after.startswith(" ") else 0
    words = [inline[k][0].strip().lower() for k in TIME_IDS]
    words = [INN_WORDS.get(w, w) for w in words]
    return [before + w + after[:cut] for w in words], after[cut:]


# ---------------------------------------------------------------------------------------------
# Whole-script build
def name_px(b):
    return measure(b, vwf=False)


def build_all(rows=None, log=None):
    """Encode and lay out every original (block, index).
    Returns dict: strings {(blk, idx): bytes (no terminator)}, info {sid: {...}}, warnings, errors, missing."""
    rows = rows if rows is not None else load_tsv()
    inline = load_tsv(os.path.join(TRANS, "en_inline.tsv"), include_inline=True)
    jp = jp_blocks()
    W = widths()
    strings, info, warnings, errors, missing = {}, {}, [], [], []

    inn = inn_time_texts(rows, inline)

    def en_of(blk, idx):
        sid = f"{blk:02X}:{idx:03d}"
        if inn and sid == INN_TIME_SID:
            return inn[1]
        r = rows.get(sid)
        return r[0] if r else None

    # names first (their widths feed the placeholders)
    def enc_name(blk, idx):
        t = en_of(blk, idx)
        if t:
            return encode_text(t, blk)
        return jp[blk][idx]
    maxname = 0
    longest = ""
    for blk in (0x15, 0x16):
        for idx in range(len(jp[blk])):
            b = enc_name(blk, idx)
            px = measure(b, vwf=False)
            if px > maxname:
                maxname, longest = px, f"{blk:02X}:{idx:03d}"
    item_px = max(measure(enc_name(0x14, i), vwf=False) for i in range(len(jp[0x14])))
    party_px = max(measure(enc_name(0x15, i), vwf=False) for i in range(len(jp[0x15])))
    time_px = max(measure(encode_text(inline[k][0]), vwf=False) for k in
                  ("INL:0E1D8", "INL:0E1DC", "INL:0E1E0", "INL:0E1E3") if k in inline)
    pts = inline.get("INL:0C929", (" pts", ""))[0]
    gold = inline.get("INL:0E1A5", ("GOLD", ""))[0]          # shop price unit after 0x5F (b07 $C1A2)
    ph_common = {0x5B: maxname, 0x5D: maxname,
                 0x5E: 3 * W[ord('0')] + measure(tokenize(pts), True),
                 0x5F: 5 * W[ord('0')] + measure(tokenize(gold), True), 0x5C: 64}
    meta = {'maxname': maxname, 'longest_name': longest, 'item_px': item_px, 'party_px': party_px,
            'time_px': time_px, 'ph': ph_common,
            'widths': WIDTHS_SOURCE}

    for blk in sorted(jp):
        for idx, jb in enumerate(jp[blk]):
            sid = f"{blk:02X}:{idx:03d}"
            en = en_of(blk, idx)
            pol = policy(blk, idx, en or "", jb)
            rec = {'policy': pol, 'pages': [], 'auto': 0, 'source': 'en', 'warnings': [], 'errors': []}
            if en is None or (en == "" and len(jb) > 0):
                strings[(blk, idx)] = jb
                rec['source'] = 'jp' if len(jb) else 'empty'
                if len(jb) and blk != 0x19:
                    missing.append(sid)
                info[sid] = rec
                continue
            try:
                if pol.kind == 'name':
                    b = encode_text(en, blk)
                    rec['px'] = measure(b, vwf=False)
                else:
                    vwf = wants_vwf(en) or (blk not in (0x13,) and has_latin(en))
                    prefix = 0
                    ph = ph_common
                    if blk == 0x0E and en.startswith(','):
                        prefix = W[0x2A] + item_px                 # '*' + item name, then ", then?"
                    elif sid == INN_TIME_SID:                     # '*' + inn time of day, then "comes, ..."
                        prefix = W[0x2A] + (max(measure(encode_text(x)) for x in inn[0]) if inn else time_px)
                    elif blk == 0x13 and idx == 0x29:
                        prefix = item_px                           # item name + " can't be equipped."
                    elif blk == 0x13 and idx in NAME_PREFIX_13:
                        prefix = maxname                           # actor name + " is defending." etc.
                    if blk == 0x22 and idx in MONSTER_ONLY_22:
                        ph = dict(ph_common)
                        ph[0x5D] = party_px                        # monster-only attack: target is the party
                    atoms, L = layout_text(sid, en, pol, ph, vwf, prefix)
                    if pol.kind == 'battle' and L.errors:
                        # try a re-flow into 2 lines
                        p2 = Policy('reflow', 224, 2, None, final_wait=False)
                        atoms2, L2 = layout_text(sid, en.replace('|', ' '), p2, ph, vwf)
                        if not L2.errors and L2.auto == 0:
                            atoms, L = atoms2, L2
                            rec['warnings'].append("battle line re-flowed")
                    b = body_bytes(atoms, vwf)
                    rec.update(pages=L.pages, auto=L.auto, prefix=prefix, ph=ph, vwf=vwf)
                    rec['errors'] += L.errors
                    rec['warnings'] += L.warnings
                    if pol.kind == 'battle':
                        nl = sum(1 for p in L.pages for _ in p['lines'])
                        if nl > 2:
                            rec['errors'].append(f"{nl} lines in a 2-line battle window")
                check_bytes(sid, b, rec['errors'])
                if pol.max_bytes and len(b) > pol.max_bytes:
                    rec['errors'].append(f"{len(b)} bytes > {pol.max_bytes}")
                if blk == 0x0E and 0x5F in b and b.index(0x5F) < len(encode_text(gold)):
                    rec['errors'].append(f"0x5F at index < {len(encode_text(gold))} (the shop's GOLD print "
                                         f"overwrites $26FD+)")
                if 0x24 in b and 0x24 in jb:
                    seg_en = b[b.index(0x24):b.index(0x25) + 1]
                    seg_jp = jb[jb.index(0x24):jb.index(0x25) + 1]
                    rec['password'] = seg_en == seg_jp
                    if seg_en != seg_jp:
                        rec['errors'].append(f"password bytes differ: {seg_en.hex(' ')} vs JP {seg_jp.hex(' ')}")
            except EncodeError as ex:
                rec['errors'].append(str(ex))
                b = jb
            strings[(blk, idx)] = b
            info[sid] = rec
            for w in rec['warnings']:
                warnings.append(f"{sid}: {w}")
            for e in rec['errors']:
                errors.append(f"{sid}: {e}")
    # captions: a string without its own clear continues the previous page (17:011 -> 17:012)
    for blk in CAPTION_BLOCKS:
        for idx in range(1, len(jp[blk])):
            b = strings[(blk, idx)].lstrip(bytes([VWF_ON]))
            prev = strings[(blk, idx - 1)]
            pi, ci = info[f"{blk:02X}:{idx - 1:03d}"], info[f"{blk:02X}:{idx:03d}"]
            if not b or b[0] in (CLR, CLR_P) or not pi['pages'] or not ci['pages']:
                continue
            ends_nl = prev.rstrip(bytes([VWF_OFF])).endswith(bytes([NL]))
            rows_ = len(pi['pages'][-1]['lines']) - (0 if ends_nl else 1) + len(ci['pages'][0]['lines'])
            sid = f"{blk:02X}:{idx:03d}"
            cap = 3 if blk == 0x17 else 4
            if rows_ > cap:
                errors.append(f"{sid}: continues the previous caption page: {rows_} lines > {cap}")
            else:
                info[sid]['warnings'].append(f"continues {blk:02X}:{idx - 1:03d}'s page ({rows_} lines)")
    extra = sorted(k for k in rows if re.fullmatch(r"[0-9A-F]{2}:\d{3}", k) and
                   (int(k[:2], 16) not in jp or int(k[3:]) >= len(jp[int(k[:2], 16)])))
    for k in extra:
        warnings.append(f"{k}: English row has no original string (ignored)")
    return {'strings': strings, 'info': info, 'warnings': warnings, 'errors': errors, 'missing': missing,
            'meta': meta}


# ---------------------------------------------------------------------------------------------
# Event scripts (bank $0A, interpreter b02:$C0C4, op table b02:$C000): which strings share a window
# and which windows show a portrait. Used to check pages that continue another string's window.
# Print ops: 10 open+print+close, 40 open+print, 52 open+portrait+print (no portrait for 10/40);
# 46/80/3E print into the open window, 54/82 redraw the portrait and print. Op 0E sets the block ($2E6F);
# without it the block is the area default (b02:$C08C: 1C-20), unknown statically.
EV_LEN = {0x00: 2, 0x02: 2, 0x04: 2, 0x06: 2, 0x08: 4, 0x0A: 4, 0x0C: 2, 0x0E: 2, 0x10: 3, 0x12: 2, 0x14: 3,
          0x16: 2, 0x18: 5, 0x1A: 2, 0x2A: 6, 0x2E: 2, 0x30: 1, 0x32: 1, 0x34: 1, 0x36: 2, 0x38: 2, 0x3A: 4,
          0x3C: 1, 0x3E: 2, 0x40: 3, 0x42: 1, 0x44: 2, 0x46: 3, 0x48: 3, 0x4A: 5, 0x4C: 6, 0x4E: 1, 0x50: 2,
          0x52: 4, 0x54: 4, 0x56: 5, 0x58: 6, 0x5A: 2, 0x5C: 3, 0x5E: 1, 0x60: 1, 0x62: 6, 0x64: 3, 0x66: 2,
          0x68: 1, 0x6A: 3, 0x6C: 2, 0x6E: 6, 0x70: 6, 0x72: 5, 0x74: 4, 0x78: 2, 0x7A: 2, 0x7C: 3, 0x7E: 4,
          0x80: 2, 0x82: 3, 0x84: 1, 0x86: 2, 0x88: 2, 0x8A: 8}
EV_JUMP = (0x1C, 0x1E, 0x20, 0x22, 0x24, 0x26)        # 20 jump, 1C/1E branch, 22/24/26 call (28 return)
EV_END = (0xFF, 0x76, 0x2C)


def event_prints(rom=None):
    """Parse every event script; return (records, bad_ops). A record: block (None = area default), idx,
    portrait (drawn in this window), new (opened by this op), prev (idx printed before in the same window)."""
    rom = rom or open(os.path.join(BASE, "rom", "Susanoo Densetsu (Japan).pce"), "rb").read()
    bank = rom[0x14000:0x16000]
    rd = lambda a: bank[a - 0x4000]
    lo, hi = rom[0x45F2:0x45F2 + 0xFF], rom[0x46F1:0x46F1 + 0xFF]
    starts = sorted(set(lo[i] | hi[i] << 8 for i in range(0xFF)))
    ops, bad, work = {}, [], list(starts)
    while work:
        a = work.pop()
        while 0x4000 <= a < 0x6000 and a not in ops:
            op = rd(a)
            if op in EV_END or op == 0x28:
                ops[a] = (op, (), a + 1)
                break
            if op in EV_JUMP:
                t = rd(a + 1) | rd(a + 2) << 8
                ops[a] = (op, (t,), a + 3)
                work.append(t)
                if op == 0x20:
                    break
                a += 3
                continue
            if op not in EV_LEN:
                bad.append(a)
                break
            n = EV_LEN[op]
            ops[a] = (op, tuple(rd(a + i) for i in range(1, n)), a + n)
            a += n
    recs, seen = set(), set()
    stack = [(s, (False, False, None, None, ())) for s in starts]
    while stack:
        a, st = stack.pop()
        while a in ops and (a, st) not in seen:
            seen.add((a, st))
            op, args, nxt = ops[a]
            win, por, prev, blk, calls = st
            if op in EV_END:
                break
            if op == 0x28:
                if not calls:
                    break
                a, st = calls[-1], (win, por, prev, blk, calls[:-1])
                continue
            if op == 0x20:
                a = args[0]
                continue
            if op in (0x1C, 0x1E):
                stack.append((args[0], st))
                a = nxt
                continue
            if op in (0x22, 0x24, 0x26):
                if op != 0x26:
                    stack.append((nxt, st))
                a, st = args[0], (win, por, prev, blk, (calls + (nxt,))[-6:])
                continue
            if op == 0x0E:
                blk = args[0]
            elif op == 0x42:
                win, por, prev = False, False, None
            elif op in (0x10, 0x40, 0x52, 0x46, 0x54, 0x3E, 0x80, 0x82):
                new = op in (0x10, 0x40, 0x52)
                if op in (0x52, 0x54, 0x82):
                    por = True
                elif new:
                    por = False
                i = 1 if op in (0x52, 0x54, 0x82) else 0
                p = None if new or not win else prev
                recs.add((blk, args[i], por, new, p))
                win, prev = op != 0x10, args[i]
                if op == 0x10:
                    por, prev = False, None
            st = (win, por, prev, blk, calls)
            a = nxt
    out = [dict(block=b, idx=i, portrait=po, new=n, prev=p) for b, i, po, n, p in recs]
    return out, bad


def check_event_windows(r, rom=None):
    """Continuation pages (a string printed into a window that holds the previous string, after its wait)
    and portrait windows against the layout of build_all() result r. Returns (errors, warnings, stats).
    Records with the area-default block are checked in every block 1C-20 whose JP text continues there
    naturally (the JP string starts with 06/07/0D)."""
    recs, bad = event_prints(rom)
    J, S, I = jp_blocks(), r['strings'], r['info']
    errors, warnings = [], []
    if bad:
        warnings.append(f"event scripts: {len(bad)} unknown ops at " + " ".join(f"${a:04X}" for a in bad[:8]))

    def first(b):
        b = b.lstrip(bytes([VWF_ON]))
        return b[0] if b else None

    def rows(blk, idx, which):
        p = I[f"{blk:02X}:{idx:03d}"]['pages']
        return len(p[which]['lines']) if p else 0
    n_cont = n_por = 0
    for rec in recs:
        blks = [rec['block']] if rec['block'] is not None else [0x1C, 0x1D, 0x1E, 0x1F, 0x20]
        for blk in blks:
            if blk not in J or rec['idx'] >= len(J[blk]):
                continue
            jb = J[blk][rec['idx']]
            if rec['block'] is None and not rec['new'] and jb[:1] not in (b'\x06', b'\x07', b'\x0d'):
                continue                                   # the JP would not continue here: not this block
            sid = f"{blk:02X}:{rec['idx']:03d}"
            out = errors if rec['block'] is not None else warnings
            pol = I[sid]['policy']
            fc = first(S[(blk, rec['idx'])])
            por = rec['portrait']
            if por and rec['prev'] is not None and not rec['new'] and rec['prev'] < len(J[blk]) \
                    and CLR in S[(blk, rec['prev'])]:
                por = False                                # the previous string's 06 erased the portrait
            if por and rec['block'] is None and jp_page_cells(jb)[0] > 23:
                continue                                   # the JP would overlap a portrait: not this block
            if por and pol.width > 184 and fc != CLR and pol.kind == 'reflow':
                out.append(f"{sid}: printed in a portrait window but laid out at {pol.width} px")
            n_por += por
            if rec['prev'] is None or rec['new'] or rec['prev'] >= len(J[blk]) or fc in (CLR, CLR_P):
                continue
            n_cont += 1
            tot = rows(blk, rec['prev'], -1) + rows(blk, rec['idx'], 0) - (0 if fc == NL else 1)
            if tot > pol.lines:
                out.append(f"{sid}: continues {blk:02X}:{rec['prev']:03d}'s window: {tot} lines > {pol.lines}")
    stats = {'records': len(recs), 'explicit': sum(1 for x in recs if x['block'] is not None),
             'continuations': n_cont, 'portrait': n_por}
    return errors, warnings, stats


# ---------------------------------------------------------------------------------------------
# Splitting into continuation pieces (03 n)
def safe_cuts(b):
    """Indices i where b[:i] / b[i:] may be split (never inside a 2-byte code or after a dakuten prefix)."""
    ok = [True] * (len(b) + 1)
    i = 0
    while i < len(b):
        c = b[i]
        if 0x10 <= c <= 0x1F or c in (0xDE, 0xDF):
            ok[i + 1] = False
            i += 2
            continue
        i += 1
    ok[0] = False
    return ok


def split_pieces(b, first_limit=LINEBUF_MAX - 2, limit=LINEBUF_MAX - 2, last_limit=LINEBUF_MAX, min_5f=0):
    """Split a string body into pieces; every piece but the last is followed by 03 n (2 bytes).
    Preferred cut points: right after a page break (wait + clear), then after a wait, a newline, a space.
    min_5f: a 0x5F placeholder must sit at index >= min_5f of its piece (shop loop, block 0E)."""
    if len(b) <= last_limit:
        return [b]
    ok = safe_cuts(b)
    for i in range(len(b) + 1):
        if ok[i] and any(b[j] == 0x5F for j in range(i, min(i + min_5f, len(b)))):
            ok[i] = False
    def score(i):
        p = b[i - 1]
        pp = b[i - 2] if i >= 2 else None
        if p in (CLR, CLR_P) and pp in (WAIT, WAIT2):
            return 5
        return {WAIT: 4, WAIT2: 4, CLR: 3, CLR_P: 3, NL: 2, 0x20: 1}.get(p, 0)
    # fewest pieces first, then the best cut points (dynamic programming over cut positions)
    L = len(b)
    best = {0: (0, 0, None)}            # position -> (pieces, -score, previous cut)
    for c in range(1, L + 1):
        if c < L and not ok[c]:
            continue
        lim = last_limit if c == L else limit
        cand = None
        for a in best:
            if c - a > lim or c <= a:
                continue
            pc, ps, _ = best[a]
            v = (pc + 1, ps - (score(c) if c < L else 0), a)
            if cand is None or v[:2] < cand[:2]:
                cand = v
        if cand is not None:
            best[c] = cand
    if L not in best:
        raise EncodeError(f"cannot split {L} bytes")
    cuts, c = [], L
    while c:
        cuts.append(c)
        c = best[c][2]
    cuts.reverse()
    pieces, start = [], 0
    for c in cuts:
        pieces.append(b[start:c])
        start = c
    return pieces

if __name__ == "__main__":
    r = build_all()
    print("widths:", WIDTHS_SOURCE)
    print("strings:", len(r['strings']), "errors:", len(r['errors']), "warnings:", len(r['warnings']),
          "untranslated:", len(r['missing']))
    for e in r['errors'][:80]:
        print("E", e)
    for w in r['warnings'][:80]:
        print("W", w)
