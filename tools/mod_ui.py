"""Build module: UI strings outside the script blocks (docs/design.md).

Input: translation/en_inline.tsv (ID = INL:<file offset of the JP string>), read fresh on every build,
plus 13:019 (teleport fragment) from the block tables. Encoding: tools/textenc.py (04/05 VWF wrapping).

What it writes:
- asm/ui_b00.s -> region "ui.b00": PSTR (relocated inline strings) and UIFAR (far call into bank $58).
- asm/ui_far.s -> bank $58 at $6000 ("ui.far"): the reordered sentences; their strings at $7000+.
- region "ui.b07": time-of-day strings + the level-up stat table (both repointed).
- in-place strings (padded with the no-op code 08, or spaces where a column layout needs the width),
  PSTR sites, UIFAR sites, the bank 9 password label block, the target-window HP=/OP= columns.
- backup memory saves keep the text options (speed $2783, battle text $2784) in spare bits of the slot byte $3318.
- OUT/ui-fields.txt: every name of blocks 11/12/14/15/16 measured against its fields (overflow list).
- menu-only short names (translation/short-names.tsv): tables + short_item/short_place in bank $58, stubs in
  region "ui.b09" (b09 $DFB4), patched into the narrow fields (status page 2 / equip window, item bag,
  teleport list). Dialogue, shops and messages keep the full names.
- inn wake-up line: its own lowercase time-of-day table + printer in "ui.b07", called from b07 $C604,
  when 0E:015 is written "When {TIME} comes, ..." (textenc.inn_time_texts).
Every patched byte is asserted against the original ROM first (b.patch).
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textenc as T  # noqa: E402

BANK = 0x2000
UI_BANK = 0x58
FAR_CODE = 0x6000
FAR_STR = 0x7000
INL_TSV = os.path.join(T.TRANS, "en_inline.tsv")
SHORT_TSV = os.path.join(T.TRANS, "short-names.tsv")
FILL = 0x08          # putc no-op (handler $CB26), also passed through by the VWF hook
NOP = 0xEA


def off(bank, cpu):
    return bank * BANK + (cpu & 0x1FFF)


def le(a):
    return bytes([a & 0xFF, a >> 8])


class UI:
    def __init__(self, b):
        self.b = b
        self.rows = T.load_tsv(INL_TSV, include_inline=True)
        self.used = set()
        self.far = bytearray()          # strings at FAR_STR
        self.far_syms = {}
        self.checks = []                # (what, px, limit)

    # ---- TSV access ----------------------------------------------------------------------------
    def text(self, sid):
        self.used.add(sid)
        if sid not in self.rows:
            self.b.error(f"{sid} missing from en_inline.tsv")
            return ""
        return self.rows[sid][0]

    def frag(self, sid, pattern):
        """Groups of a full match of the TSV text; a wording change that breaks a reorder fails loudly."""
        t = self.text(sid)
        m = re.fullmatch(pattern, t)
        if not m:
            self.b.error(f"{sid} {t!r} no longer matches the reorder pattern {pattern!r}; update mod_ui.py")
            return None
        return m.groups()

    def enc(self, text, vwf=True):
        return T.encode_text(text, vwf=vwf)

    # ---- far strings -----------------------------------------------------------------------------
    def far_str(self, sym, data):
        if len(data) > T.LINEBUF_MAX:
            self.b.error(f"{sym}: {len(data)} bytes > {T.LINEBUF_MAX}")
        for c in data:
            if c == 0:
                self.b.error(f"{sym}: 00 inside the string")
        addr = FAR_STR + len(self.far)
        self.far += bytes(data) + b"\x00"
        if sym:
            self.far_syms[sym] = addr
        return addr

    def far_data(self, sym, data):
        """Raw data (may contain 00) in the far bank at FAR_STR+; returns its address."""
        addr = FAR_STR + len(self.far)
        self.far += bytes(data)
        self.far_syms[sym] = addr
        return addr

    # ---- inline sites (jsr $EF5F / string / 00) ----------------------------------------------------
    def site(self, sid):
        o = int(sid[4:], 16)
        z = self.b.src.index(0, o)
        if self.b.src[o - 3:o] != b"\x20\x5F\xEF":
            raise AssertionError(f"{sid}: not an inline jsr $EF5F string")
        return o, z

    def inline(self, sid, data=None, pad=FILL, suffix=b""):
        """In place if it fits (padded to the original length), else relocated with PSTR."""
        if data is None:
            data = T.encode_text(self.text(sid))      # §5 rule: 04 ... 05 only with lowercase
        data = bytes(data) + suffix
        o, z = self.site(sid)
        n = z - o
        if data == self.b.src[o:z]:
            return "same"
        if len(data) <= n:
            self.b.patch(o, self.b.src[o:z], data + bytes([pad]) * (n - len(data)))
            return "in place"
        if n < 2:
            raise AssertionError(f"{sid}: 1-byte site needs UIFAR")
        addr = self.far_str("", data)
        self.b.patch(o - 3, self.b.src[o - 3:z],
                     b"\x20" + le(self.lab["PSTR"]) + le(addr) + bytes([NOP]) * (n - 2))
        return f"PSTR -> ${addr:04X}"

    def farsite(self, bank, cpu, length, target, tail=b""):
        """Replace `length` original bytes at bank:cpu with jsr UIFAR / .dw target / tail / nop..."""
        o = off(bank, cpu)
        new = b"\x20" + le(self.lab["UIFAR"]) + le(target) + tail
        assert len(new) <= length, (hex(cpu), len(new), length)
        self.b.patch(o, self.b.src[o:o + length], new + bytes([NOP]) * (length - len(new)))

    def check(self, what, data, limit, lines=1, ph=None):
        """Pixel width of each line of data (bytes, VWF depth tracked) against limit."""
        data = bytes(data)
        cur, out = bytearray(), []
        for i, c in enumerate(data):
            if c in (0x0D, 0x06) and not (i and 0x10 <= data[i - 1] <= 0x1F):
                out.append(bytes(cur))
                cur = bytearray()
                continue
            cur.append(c)
        out.append(bytes(cur))
        d = n = worst = 0
        for seg in out:
            px = T.measure(bytes([0x04]) * d + seg, vwf=False, ph=ph)
            for c in seg:
                if c == 0x04:
                    d += 1
                elif c == 0x05:
                    d = max(0, d - 1)
            if seg.strip(b"\x04\x05\x08 "):
                n += 1
            worst = max(worst, px)
        self.checks.append((what, worst, limit))
        if worst > limit:
            self.b.error(f"{what}: {worst} px > {limit} px")
        if n > lines:
            self.b.error(f"{what}: {n} lines > {lines}")
        return worst


def load_short_names(path=SHORT_TSV):
    """{ID: short name} from translation/short-names.tsv (columns ID, Japanese, Full name, Full px,
    Limit px, Short name); rows without a short name are left out (the full name is used)."""
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n").rstrip("\r")
        if not line or line.startswith("#") or line.startswith("ID\t"):
            continue
        p = line.split("\t")
        if len(p) >= 6 and p[5].strip() and re.fullmatch(r"(11|14):\d{3}", p[0]):
            d[p[0]] = p[5].strip()
    return d


def info_value_pen(word):
    """Pen x (px) that puts the word's last ink pixel on the last ink pixel of the gold amount
    (fixed digit cell 9 of the info window)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "font"))
    import fontc
    g = fontc.load()
    fx = fontc.fixed_glyphs(g)
    right = max(max(i for i in range(8) if (m := _or(fx[ord(d)])) & (0x80 >> i)) for d in "0123456789")
    target = 9 * 8 + right
    W = T.widths()
    codes = [ord(c) for c in word]
    return target - (sum(W[c] for c in codes[:-1]) + g[codes[-1]].ink_cols()[1])


def _or(rows):
    m = 0
    for r in rows:
        m |= r
    return m


def apply(b):
    u = UI(b)
    W = T.widths()
    lab = b.asm_region("ui_b00.s", "ui.b00", {"UI_BANK": UI_BANK})
    u.lab = lab
    rep = []

    # ================= plain inline strings (in place or PSTR) =================================
    plain = {
        "INL:0100E": {},                       # equip refusal b00 $EFFE: "<name>" + this + "<item>" + 13:041
        "INL:01DE0": {},                       # generic Yes/No
        "INL:0A846": {},                       # rations window
        "INL:0C929": {},                       # battle ^ number + " pts"
        "INL:0D82D": {}, "INL:0D863": {}, "INL:0D985": {}, "INL:0D9A3": {},
        "INL:0E0F7": {"pad": 0x20},            # "GOLD " + 5 digits (keeps the 10-cell row)
        "INL:0E112": {},                       # "| Time  " + time of day
        "INL:0E127": {"suffix": b"\x11\x07"},  # supplies: count at col 7 as in the JP
        "INL:0E13C": {"suffix": b"\x11\x07"},
        "INL:0E154": {"suffix": b"\x11\x07"},
        "INL:0E1A5": {}, "INL:05496": {}, "INL:0549F": {},
        "INL:0EB7C": {},                       # food shop " slices"
        "INL:0F371": {},                       # level-up "<name>'s "
        "INL:0F88F": {}, "INL:0F8A9": {}, "INL:0F8D3": {}, "INL:0F8EC": {},
        "INL:13683": {"suffix": b"\x11\x03"},  # status "Name": slots read $7F after it (col 3 as JP)
        "INL:13700": {"pad": 0x20},            # status "HP " (3 cells, slots at 3/12/21)
        "INL:1374B": {}, "INL:1378D": {}, "INL:137A6": {}, "INL:13824": {}, "INL:13868": {},
        "INL:1389A": {}, "INL:138CC": {}, "INL:138FE": {},
        "INL:13A38": {},                       # "None" in an 8-cell name field
    }
    for sid, kw in plain.items():
        r = u.inline(sid, None, kw.get("pad", FILL), kw.get("suffix", b""))
        rep.append(f"{sid} {r}")

    # 'が ' after the stat name (INL:0F3C4) prints nothing in English: branch over the call.
    t = u.text("INL:0F3C4")
    if t != "":
        b.error(f"INL:0F3C4 is {t!r}; mod_ui expects it empty (branch over)")
    o, z = u.site("INL:0F3C4")
    b.patch(o - 3, b.src[o - 3:z + 1], bytes([0x80, z - o + 2]) + bytes([NOP]) * (z - o + 2))
    rep.append("INL:0F3C4 empty: bra over")

    # Fixed templates (): byte positions kept, page digit / EXP digits poked by code.
    for sid, lead in (("INL:0E70E", b"\x0D\x20\x0C"), ("INL:135FD", b"\x0C")):
        t = u.text(sid)
        m = re.fullmatch(r"(\|? ?\[0C\])(\w+)  \((EXP)      \)(\|?)", t)
        if not m:
            b.error(f"{sid} {t!r}: template pattern changed")
            continue
        word = m.group(2)
        body = lead + b"\x04" + word.encode() + b"\x05"
        o = int(sid[4:], 16)
        jp = b.src[o:b.src.index(0, o)]
        # JP: lead + 6 bytes ページ, so the digit sits at len(lead)+6; English must put it at the same byte.
        if len(body) != len(lead) + 6:
            b.error(f"{sid}: '{word}' must encode in 4 letters to keep the digit at its byte")
            continue
        new = body + b"  (EXP      )"
        if sid == "INL:135FD":
            new += bytes([FILL, 0x0D])          # JP ends 02 0D
        assert len(new) == len(jp), (sid, len(new), len(jp))
        b.patch(o, jp, new)
        rep.append(f"{sid} template in place")

    # ================= time of day (b07 $C1D0 table) + level-up stat table -> ui.b07 =========
    bank7, a7, z7 = b.claim("ui.b07")
    blob7 = bytearray()
    ptrs = []
    inn = T.inn_time_texts()
    for sid in ("INL:0E1D8", "INL:0E1DC", "INL:0E1E0", "INL:0E1E3"):
        ptrs.append(a7 + len(blob7))
        # status window copy; the inn line has its own table below (with the old 0E:015 the inn shared
        # this one and needed a trailing space)
        s = u.enc(u.text(sid) + ("" if inn else " "))
        if inn and s[:1] == b"\x04":
            # right-align: last ink pixel on the last ink pixel of the 5th gold digit (cell 9)
            s = s[:1] + bytes([T.PEN, 0x20 + info_value_pen(u.text(sid))]) + s[1:]
        blob7 += s + b"\x00"
        u.check(f"{sid} info window ' Time  '+time", u.enc(u.text("INL:0E112")) + s, 80)
    b.patch(off(7, 0xC1D0), b.src[off(7, 0xC1D0):off(7, 0xC1D8)], b"".join(le(p) for p in ptrs))
    lvtab = a7 + len(blob7)
    names = [u.text("INL:0F37C"), u.text("INL:0F382"), u.text("INL:0F38C"), "STR", "DEX", "VIT", "MDX"]
    lvoff = []
    for nm in names:
        lvoff.append(len(blob7) - (lvtab - a7))
        blob7 += u.enc(nm, vwf=True) + b"\x00"
    if max(lvoff) > 0xFF:
        b.error("level-up table > 256 bytes")
    if len(blob7) > z7 - a7 + 1:
        b.error(f"ui.b07: {len(blob7)} bytes > {z7 - a7 + 1}")
    if inn:
        # inn wake-up line (b07 $C5FB: 0E:029 "*", jsr $C1BF with the next time, 0E:015): own table of
        # "When morning " etc. INN_TOD = and #3 / asl / tax / lda tab,x / sta $34 / lda tab+1,x / sta $35 /
        # jmp $EF41 (the $C1BF printer with another table).
        istr = []
        for txt in inn[0]:
            istr.append(a7 + len(blob7))
            blob7 += u.enc(txt) + b"\x00"
        itab = a7 + len(blob7)
        blob7 += b"".join(le(x) for x in istr)
        inn_tod = a7 + len(blob7)
        blob7 += bytes([0x29, 0x03, 0x0A, 0xAA, 0xBD]) + le(itab) + bytes([0x85, 0x34, 0xBD]) + le(itab + 1) + \
            bytes([0x85, 0x35, 0x4C, 0x41, 0xEF])
        b.patch(off(7, 0xC604), bytes.fromhex("20 BF C1"), b"\x20" + le(inn_tod))
        for txt in inn[0]:      # the line with 0E:015 is checked by the text layout (prefix of 0E:015)
            u.checks.append((f"inn '*{txt}' (144 px panel)", T.measure(T.encode_text("*" + txt), vwf=False), 144))
        rep.append(f"inn time of day: own table at b07:${itab:04X}, printer b07:${inn_tod:04X} (b07 $C604)")
    # PANELKEEP: b07 $C16A (print of a block 0E string) saves $7F/$80, re-selects the panel ($C081 -> $CAA9,
    # whose $CABA hook resets the VWF cell) and restores the pen. Between an item name and its fragment
    # ("Stick" + ", huh?") the reset made the fragment start a fresh cell on top of the name's last glyph
    # (shown "Stic, huh?"). vwf_keep ($26BD, asm/vwf_ram.inc) makes vwf_winreset skip the reset for this call.
    keep = a7 + len(blob7)
    blob7 += bytes([0xEE, 0xBD, 0x26, 0x20, 0x81, 0xC0, 0x9C, 0xBD, 0x26, 0x60])   # inc/jsr $C081/stz/rts
    b.patch(off(7, 0xC171), bytes.fromhex("20 81 C0"), b"\x20" + le(keep))
    rep.append(f"panel re-select keeps the VWF cell: PANELKEEP b07:${keep:04X} (b07 $C171)")
    if len(blob7) > z7 - a7 + 1:
        b.error(f"ui.b07: {len(blob7)} bytes > {z7 - a7 + 1}")
    b.write(off(7, a7), bytes(blob7))
    assert lvoff[0] == 0                      # D29C cly: Level at offset 0
    b.patch(off(7, 0xD3B6), b"\x7C", bytes([lvtab & 0xFF]))
    b.patch(off(7, 0xD3BB), b"\xD3", bytes([lvtab >> 8]))
    for cpu, old, k in ((0xD301, 0x06, 1), (0xD30D, 0x10, 2), (0xD319, 0x1B, 3), (0xD325, 0x1F, 4),
                        (0xD331, 0x23, 5), (0xD33D, 0x27, 6)):
        b.patch(off(7, cpu), bytes([old]), bytes([lvoff[k]]))
    rep.append(f"time of day + level table -> b07:${a7:04X} ({len(blob7)} bytes)")

    # ================= far strings for the reorders =============================================
    F = u.far_str
    F("S_AND_PARTY", u.enc(u.text("INL:0106A")))
    g = u.frag("INL:05470", r" (EXP) (\w+)\.(\[14\]\[10\])")
    g2 = u.frag("INL:05481", r" (GOLD) (\w+)\.(\[14\]\[10\])")
    if g and g2:
        F("S_GAINED", u.enc(f" {g[1]} "))
        F("S_EXP_END", u.enc(f" {g[0]}.{g[2]}"))
        F("S_GOLD_END", u.enc(f" {g2[0]}.{g2[2]}"))
    g = u.frag("INL:0DAC8", r" (EXP) (\w+)")
    g2 = u.frag("INL:0DAD7", r" (GOLD) (\w+)\.(\[0F\])")
    if g and g2:
        F("S_GAINED6", u.enc(f" {g2[1]} "))
        F("S_EXP_AND", u.enc(f" {g[0]} {g[1]} "))
        F("S_GOLD_END6", u.enc(f" {g2[0]}.{g2[2]}"))
    g = u.frag("INL:0F768", r" (GOLD)")
    g2 = u.frag("INL:0F77C", r" (\w+)\.(\[0E\])")
    if g and g2:
        F("S_FOUND", u.enc(f" {g2[0]} "))
        F("S_GOLD_FOUND", u.enc(f" {g[0]}."))
        F("S_FOUND_END", u.enc(g2[1], vwf=False))
    g = u.frag("INL:0F85E", r" (\w+)\.(\[0F\]\[0E\])")
    if g:
        F("S_OBTAINED", u.enc(f" {g[0]} "))
        F("S_OBTAIN_END", u.enc(f".{g[1]}"))
    t19 = T.load_tsv().get("13:019", ("", ""))[0]
    m = re.fullmatch(r"( \w+)( \w+ )\[0F\]", t19)
    if not m:
        b.error(f"13:019 {t19!r}: teleport pattern changed")
    else:
        F("S_TELE", u.enc(m.group(1) + m.group(2)))        # " teleported to " + vehicle / place
        F("S_TELE_O", u.enc(m.group(1) + " "))             # " teleported " + INL:0B1C6 ("outside")
    F("S_TELE_END", u.enc(".[0F]"))
    F("S_OUTSIDE", u.enc(u.text("INL:0B1C6")))
    g = u.frag("INL:0F3DE", r"( \w+ \w+ )\{N\}(\.)")
    g2 = u.frag("INL:0F3EB", r"( \w+ \w+ )\{N\}(\.)")
    if g and g2:
        F("S_ROSE", u.enc(g[0]))
        F("S_FELL", u.enc(g2[0]))
        F("S_LV_END", u.enc(g[1]))
    F("S_LEVEL", u.enc(u.text("INL:0F40C") + " "))   # space before the level digit
    F("S_LVSEP", u.enc(u.text("INL:0F41D")))
    F("S_CANUSE", u.enc(u.text("INL:0F428")))
    for sym, ids in (("S_WPN", ("INL:13935", "INL:139B6")), ("S_ARM", ("INL:13948", "INL:139CC")),
                     ("S_SHD", ("INL:1395B", "INL:139E2")), ("S_HLM", ("INL:1396E", "INL:139F8")),
                     ("S_STRL", ("INL:13A4A",))):
        ts = {u.text(i) for i in ids}
        if len(ts) != 1:
            b.error(f"{ids}: the two copies differ {ts}; one label per slot is printed by shared code")
        F(sym, u.enc(ts.pop()) + b"\x11\x03")    # labels start at col 0; slots read $7F after: col 3

    # backup memory / continue (CD-ROM2 only), with their windows (bank 9 table $C514)
    for sym, sid, w, n in (("S_BK_C400", "INL:12400", 176, 3), ("S_BK_C42C", "INL:1242C", 176, 3),
                           ("S_BK_C440", "INL:12440", 224, 12), ("S_BK_C47C", "INL:1247C", 208, 5),
                           ("S_BK_C4B5", "INL:124B5", 208, 5), ("S_BK_C4D4", "INL:124D4", 128, 2),
                           ("S_CO_D5D5", "INL:135D5", 112, 3), ("S_CO_D614", "INL:13614", 144, 4)):
        s = u.enc(u.text(sid))
        F(sym, s)
        u.check(f"{sid} window {w}px x{n}", s, w, n)

    # password screen: labels repacked in bank 9 ($CAA8-$CB0E), prompts precomposed in the far bank
    pw_ids = ["EXP", "GOLD", "INL:12AB7", "INL:12AC6", "INL:12ABE", "INL:12ACA"]
    # table order at $CA5A: EXP, GOLD, Rations, Grenades, Medicine (entries +4/+5); Password via immediates
    pw_order = [("EXP", None), ("GOLD", None), ("Rations", "INL:12AB7"), ("Grenades", "INL:12ABE"),
                ("Medicine", "INL:12AC6"), ("Password", "INL:12ACA")]
    del pw_ids
    reg_a, reg_z = 0xCAAA, b.src.index(0, off(9, 0xCAF3)) - off(9, 0) + 0xC000
    blob9 = bytearray()
    # $CAA8/$CAA9 are the last bytes of the field table (Medicine col/row); "なまえ" starts at $CAAA
    blob9 += u.enc(u.text("INL:12AA8")) + b"\x00"         # "Name" (no reference found; kept)
    pw_addr = []
    for name, sid in pw_order:
        txt = u.text(sid) if sid else name
        pw_addr.append(reg_a + len(blob9))
        lb = u.enc(txt)
        if T.measure(lb, vwf=False) > 48 and name != "Password":
            b.error(f"password label {txt!r} > 6 cells (value drawn at label col + 6)")
        u.checks.append((f"password label {txt!r} (6 cells)", T.measure(lb, vwf=False), 48))
        blob9 += lb + b"\x00"
    bad = reg_a + len(blob9)
    blob9 += u.enc(u.text("INL:12AF3")) + b"\x00"
    u.check("INL:12AF3 window 11 from col 2", u.enc(u.text("INL:12AF3")), 176 - 16)
    if reg_a + len(blob9) - 1 > reg_z:
        b.error(f"password strings {len(blob9)} bytes > region ${reg_a:04X}-${reg_z:04X}")
    o9 = off(9, reg_a)
    b.patch(o9, b.src[o9:off(9, reg_z) + 1], bytes(blob9) + b"\xFF" * (reg_z - reg_a + 1 - len(blob9)))
    for i in range(5):
        e = off(9, 0xCA5A) + 16 * i + 4
        b.patch(e, b.src[e:e + 2], le(pw_addr[i]))
    for lo_cpu in (0xC6D0, 0xC9D6):           # lda #<CACA / sta $34 / lda #>CACA
        b.patch(off(9, lo_cpu), b"\xCA", bytes([pw_addr[5] & 0xFF]))
        b.patch(off(9, lo_cpu + 4), b"\xCA", bytes([pw_addr[5] >> 8]))
    b.patch(off(9, 0xC72D), b"\xF3", bytes([bad & 0xFF]))
    b.patch(off(9, 0xC731), b"\xCA", bytes([bad >> 8]))
    defines = {f"PW_L{i}": a for i, a in enumerate(pw_addr)}
    tp = u.text("INL:12AD4")
    tl = u.text("INL:12AE4")
    if "{LABEL}" not in tp:
        b.error(f"INL:12AD4 {tp!r} has no {{LABEL}}")
    for i, (name, sid) in enumerate(pw_order):
        txt = u.text(sid) if sid else name
        for kind, tmpl, width in (("P", tp.replace("{LABEL}", txt), 192 if name == "Password" else 176),
                                  ("L", txt + tl, 176)):
            if kind == "L" and name == "Password":
                continue
            s = u.enc(tmpl, vwf=True)
            px = T.measure(s, vwf=False)
            x = max(0, (width - px) // 2)
            F(f"S_PW{kind}{i}", bytes([0x15, 0x20 + x]) + s)
            u.checks.append((f"password {kind} {tmpl!r} centred at x={x}", px, width))
            if px > width:
                b.error(f"password message {tmpl!r} {px} px > {width}")
    u.used.update({"INL:12AD4", "INL:12AE4"})

    # ================= menu-only short names (translation/short-names.tsv) ======================
    shorts = load_short_names()
    sn_tab = {}
    for blk, sym, n in ((0x14, "SHORT_I", 84), (0x11, "SHORT_P", 22)):
        ptr = [0] * n
        for sid, short in sorted(shorts.items()):
            if int(sid[:2], 16) != blk:
                continue
            k = int(sid[3:])
            if k >= n:
                b.error(f"short-names.tsv {sid}: index outside the block")
                continue
            ptr[k] = F(f"S_SHORT_{sid.replace(':', '_')}", T.encode_text(short, vwf=T.has_latin(short)))
        u.far_data(sym, b"".join(le(x) for x in ptr))
        sn_tab[blk] = sum(1 for x in ptr if x)
    defines.update({"NITEMS": 84, "NPLACES": 22})
    rep.append(f"short names: {sn_tab.get(0x14, 0)} items, {sn_tab.get(0x11, 0)} places")

    # ================= assemble the far code ====================================================
    first, last = b.claim("ui.far")
    assert first == UI_BANK
    defines.update(u.far_syms)
    code, fl = b.asm("ui_far.s", FAR_CODE, defines, max_size=FAR_STR - FAR_CODE)
    base = UI_BANK * BANK
    if any(x != 0xFF for x in b.rom[base:base + BANK]):
        b.error("bank $58 is not empty")
    b.write(base, code)
    if len(u.far) > 0x8000 - FAR_STR:
        b.error("far strings overflow bank $58")
    b.write(base + (FAR_STR - 0x6000), bytes(u.far))
    rep.append(f"far code {len(code)} bytes at ${FAR_CODE:04X}, strings {len(u.far)} bytes at ${FAR_STR:04X} (bank ${UI_BANK:02X})")

    # ================= UIFAR sites ===============================================================
    S = u.farsite
    S(2, 0xD3BD, 0xD3D3 - 0xD3BD, fl["gain2"], b"\x4C" + le(0xD3D3))           # GOLD/EXP gained
    S(6, 0xDABC, 0xDAE2 - 0xDABC, fl["victory"], b"\x4C" + le(0xDAE2))         # EXP and GOLD gained
    S(7, 0xD744, 0xD787 - 0xD744, fl["found"], b"\x60")                        # found <N> GOLD
    S(7, 0xD852, 0xD86A - 0xD852, fl["obtain"], b"\x4C" + le(0xD86A))          # obtained <item>
    S(5, 0xD18C, 0xD19D - 0xD18C, fl["tele_v"], b"\x4C" + le(0xD19D))          # teleported to <vehicle>
    S(5, 0xD1A6, 0xD1B7 - 0xD1A6, fl["tele_p"], b"\x4C" + le(0xD1B7))          # ... <place>
    S(5, 0xD1C0, 0xD1CF - 0xD1C0, fl["tele_o"], b"\x4C" + le(0xD1CF))          # ... Outside
    S(7, 0xD3D3, 0xD3D9 - 0xD3D3, fl["lvdiff"], b"\x60")                       # rose by / fell by
    S(7, 0xD3FF, 0xD405 - 0xD3FF, fl["esplearn"], b"\x60")                     # ESP can now be used
    for cpu, lbl in ((0xD932, "lbl_wpn"), (0xD945, "lbl_arm"), (0xD958, "lbl_shd"), (0xD96B, "lbl_hlm"),
                     (0xD9B3, "lbl_wpn"), (0xD9C9, "lbl_arm"), (0xD9DF, "lbl_shd"), (0xD9F5, "lbl_hlm"),
                     (0xDA47, "lbl_str")):
        o = off(9, cpu)
        assert b.src[o:o + 3] == b"\x20\x5F\xEF" and b.src[o + 4] == 0, hex(cpu)
        S(9, cpu, 5, fl[lbl])
    for cpu, lbl, ptr, prt in ((0xC1F5, "bk_c47c", 0xC47C, 0xEF41), (0xC21D, "bk_c4b5", 0xC4B5, 0xEF41),
                               (0xC25A, "bk_c400", 0xC400, 0xEF41), (0xC26D, "bk_c42c", 0xC42C, 0xEF41),
                               (0xC2AA, "bk_c440", 0xC440, 0xEF41), (0xC2D2, "bk_c4d4", 0xC4D4, 0xEF41),
                               (0xC589, "cont_d5d5", 0xD5D5, 0xD08D), (0xC612, "cont_d614", 0xD614, 0xD08D)):
        o = off(9, cpu)
        want = bytes([0xA9, ptr & 0xFF, 0x85, 0x34, 0xA9, ptr >> 8, 0x85, 0x35, 0x20]) + le(prt)
        b.expect(o, want)
        S(9, cpu, 11, fl[lbl])
    # backup memory: the save and load of a slot also store / restore the text options (ui_far.s opt_save/opt_load)
    S(9, 0xC1AA, 9, fl["opt_save"])                                            # lda $C195,x / ora / sta $3318
    S(9, 0xC16B, 5, fl["opt_load"])                                            # lda #$2E / jsr $E80F
    # original bug: with an empty slot before a used one, Load picked a stale index (blank game) -> load_pick
    S(9, 0xC5AE, 7, fl["load_pick"])                                           # tax / lda $32E3,x / sta $2797
    S(9, 0xC506, 6, fl["pwprompt"], b"\x60")                                   # label + "を にゅうりょく…"
    S(9, 0xC7DB, 0xC7E9 - 0xC7DB, fl["pwlarge"])                               # label + "のかずが大きすぎます."
    # menu-only short names: bank 9 stubs (jsr UIFAR / .dw short_* / rts) in region ui.b09
    bank9, a9, z9 = b.claim("ui.b09")
    stub = b""
    shorti = a9 + len(stub)
    stub += b"\x20" + le(lab["UIFAR"]) + le(fl["short_item"]) + b"\x60"
    shortp = a9 + len(stub)
    stub += b"\x20" + le(lab["UIFAR"]) + le(fl["short_place"]) + b"\x60"
    assert len(stub) <= z9 - a9 + 1
    b.write(off(9, a9), stub)
    b.patch(off(9, 0xDA44), bytes.fromhex("4C 52 F0"), b"\x4C" + le(shorti))   # status page 2 + equip window
    b.patch(off(9, 0xDB21), bytes.fromhex("20 52 F0"), b"\x20" + le(shorti))   # item bag, counted items
    b.patch(off(9, 0xDB31), bytes.fromhex("4C 52 F0"), b"\x4C" + le(shorti))   # item bag
    b.patch(off(9, 0xDE0D), bytes.fromhex("4C 3E F0"), b"\x4C" + le(shortp))   # teleport list
    rep.append(f"short-name stubs b09:${shorti:04X}/${shortp:04X}; sites b09 $DA44 $DB21 $DB31 $DE0D")

    # status page 2: with 3-cell labels the third slot starts at col 21; the empty-member placeholder
    # "--------" (8 fixed cells) would end at col 29 and the putc advance to col 30 wraps the line (seen in
    # the emulator: every row doubled). 7 dashes keep it inside the row.
    b.patch(off(9, 0xDA28), b"-" * 8, b"-" * 7 + bytes([FILL]))
    # b09 $DAA8: "<party>は" + 13:007 -> 13:007 alone ("You have no items.")
    b.patch(off(9, 0xDAA8), b"\x20\x5C\xF0", bytes([NOP] * 3))
    # backup-memory format question (b09 $C1F0): window x2 w12 -> x1 w14 (26 cells) for INL:1247C
    b.patch(off(9, 0xC1F3), b"\x25\xC6", b"\x15\xE6")
    # password screen setup (b09 $C66B jsr $D063): the original pins 89 glyphs (the kana of the grid, the
    # digits, EXP/GOLD) for the whole screen, leaving 29 cache slots; the English labels and prompts are VWF
    # (about 30 cells), so the data page ran out (prompt cut, ( ) missing; seen in the emulator). Without
    # the pin the grid's glyphs are cached on demand like any text (refcounts saturate at $3F, never wrap).
    # The character table at 0x12F60 and the pin list at $CFD5 are unchanged.
    b.patch(off(9, 0xC66B), b"\x20\x63\xD0", bytes([NOP] * 3))
    # shop buy list (b07 $C9D7): item name through SHOPNAME (ui_b00.s), so a name whose last pixel column is
    # the blank gap after its last letter (81 px advance, 80 px of ink: Brainwave Helmet, Demonbane Armor)
    # does not push the price at col 12 one cell right.
    b.patch(off(7, 0xC9D7), bytes.fromhex("20 52 F0"), b"\x20" + le(lab["SHOPNAME"]))
    # shop buy list (b07 $C9DA): the price column stays at 12. Moving it to 13 was tried: the 5-digit price
    # then ends in the panel's last column, putc wraps and every item takes two rows (seen in the emulator).
    # target window (b06 $CEA1): HP= col 10 -> 14, OP= col 18 -> 22: enemy names get 13 cells (+1 gap)
    b.patch(off(6, 0xCEBD), b"\x11\x0A", b"\x11\x0E")
    b.patch(off(6, 0xCECE), b"\x11\x12", b"\x11\x16")
    u.used.update({"INL:05470", "INL:05481", "INL:0DAC8", "INL:0DAD7", "INL:0F768", "INL:0F77C",
                   "INL:0F85E", "INL:0B1C6", "INL:0F3DE", "INL:0F3EB", "INL:0F40C", "INL:0F41D",
                   "INL:0F428", "INL:0106A"})

    # ================= sentence width checks (worst-case names and numbers) =====================
    rows = T.load_tsv()
    def name(sid):           # names carry their own 04 ... 05 when they have any Latin letter (text module)
        if sid not in rows:
            return b""
        t = rows[sid][0]
        return T.encode_text(t, vwf=T.has_latin(t))
    def widest(ids):
        return max(((T.measure(name(i), vwf=False), i) for i in ids if i in rows), default=(0, None))
    party = [f"15:{i:03d}" for i in range(16)]
    vehicles = [f"15:{i:03d}" for i in range(27, 32)]
    items = [f"14:{i:03d}" for i in range(84)]
    places = [f"11:{i:03d}" for i in range(22)]
    esps = [f"12:{i:03d}" for i in range(8)]
    P = {}
    def ph(sym):
        return u.far[u.far_syms[sym] - FAR_STR:u.far.index(0, u.far_syms[sym] - FAR_STR)]
    lead = name("15:000") + ph("S_AND_PARTY")
    num5 = b"\x0465535\x05"
    num3 = b"\x04255\x05"
    u.check("b02 gained (224 px)", lead + ph("S_GAINED") + num5 + ph("S_GOLD_END"), 224)
    u.check("b06 victory line 2 (224 px)", lead + ph("S_GAINED6") + num3 + ph("S_EXP_AND") + num3 + ph("S_GOLD_END6"), 224)
    u.check("b07 found (240 px)", lead + ph("S_FOUND") + num5 + ph("S_GOLD_FOUND"), 240)
    wi = widest(items)
    u.check(f"b07 obtained + {wi[1]} (224 px)", lead + ph("S_OBTAINED") + name(wi[1]) + ph("S_OBTAIN_END"), 224)
    for ids in (vehicles, places):
        w = widest(ids)
        u.check(f"b05 teleported to {w[1]} (240 px)", lead + ph("S_TELE") + name(w[1]) + ph("S_TELE_END"), 240)
    u.check("b05 teleported outside (240 px)", lead + ph("S_TELE_O") + ph("S_OUTSIDE") + ph("S_TELE_END"), 240)
    wp = widest(party)
    t41 = rows.get("13:041", ("", ""))[0]                   # equip refusal b00 $EFFE: name, INL:0100E, item, 13:041
    u.check(f"b00 equip refusal {wp[1]} + {wi[1]} (240 px)",
            name(wp[1]) + u.enc(u.text("INL:0100E")) + name(wi[1]) + T.encode_text(t41), 240)
    poss = u.enc(u.text("INL:0F371"))
    for k, nm in enumerate(names):
        u.check(f"level-up {nm!r} (240 px)", name(wp[1]) + poss + u.enc(nm, vwf=True) + ph("S_FELL") + num3 + ph("S_LV_END"), 240)
    we = widest(esps)
    u.check(f"ESP learned {we[1]} (240 px)", name(wp[1]) + poss + ph("S_LEVEL") + b"\x049\x05" + ph("S_LVSEP") + name(we[1]) + ph("S_CANUSE"), 240)
    u.check("bag full line (224 px)", u.enc(u.text("INL:0F8EC")), 224, 2)
    for sid in ("INL:0D82D", "INL:0D863", "INL:0D985"):
        wn = widest([f"16:{i:03d}" for i in range(100)] + party)
        u.check(f"{sid} after {wn[1]} (224 px)", name(wn[1]) + u.enc(u.text(sid)), 224, 2)
    u.check("INL:0D9A3 after 3 digits (224 px)", b"255" + u.enc(u.text("INL:0D9A3")), 224)
    u.check("INL:0A846 rations window (96 px)", u.enc(u.text("INL:0A846")) + b"999", 96)
    for sid in ("INL:0E127", "INL:0E13C", "INL:0E154"):
        u.check(f"{sid} label before col 7 (56 px)", u.enc(u.text(sid)), 56, 3)
    u.check("INL:0EB7C 3 digits + slices before col 12 (cells 2..11)", b"999" + u.enc(u.text("INL:0EB7C")), 80)

    # ================= field widths of the name blocks (report for the translator) ================
    def menu_name(i):        # what the narrow menus print: the short name when there is one
        sh = shorts.get(i)
        return T.encode_text(sh, vwf=T.has_latin(sh)) if sh else name(i)
    fields = [
        ("15", party, 56, "party name: battle status line (b06 $CAE5, cols 1-7) and status page 1 (7 cells)"),
        ("15", vehicles, 72, "vehicle: teleport list first entry (b09 $DE10, [0C] + 9 cells)"),
        ("16", [f"16:{i:03d}" for i in range(100)], 104, "enemy: target window (HP= moved to col 14: 13 cells + gap)"),
        ("14", items, 64, "item: status page 2 equipment (8 cells after [0C]; labels 3 cells) [short names]"),
        ("14", items, 64, "item: single-member equip window b09 $D92D (12 cells - 3 label - [0C] = 8) [short names]"),
        ("14", items, 72, "item: item bag column ([0C] + 9 cells) [short names]"),
        ("14", items[:3], 48, "counted item: item bag ([0C] + name + space + 2 digits in 10 cells) [short names]"),
        ("14", items, 81, "item: shop buy list (cols 2-11, price at col 12; advance 81 = 80 px of ink + the gap after the last letter (SHOPNAME); a name past that pushes the price one cell right, it wraps and leaves an empty row)"),
        ("11", places, 72, "place: teleport list ([0C] + 9 cells) [short names]"),
        ("12", esps, 40, "ESP: ESP list (cols 0-4, level pips from col 5)"),
    ]
    over = []
    lines = ["Field widths (real font, VWF names; px = advance sum, limit = cells*8)", ""]
    for blk, ids, lim, desc in fields:
        nm = menu_name if "[short names]" in desc else name
        bad = [(T.measure(nm(i), vwf=False), i, shorts.get(i) if nm is menu_name and i in shorts else rows[i][0])
               for i in ids if i in rows and rows[i][0] and T.measure(nm(i), vwf=False) > lim]
        lines.append(f"{desc}: limit {lim} px, {len(bad)} over")
        for px, i, t in sorted(bad, reverse=True):
            lines.append(f"    {i} {t!r} {px} px (+{px - lim})")
            over.append((i, t, px, lim, desc))
    lines += ["", "Menu-only short names (translation/short-names.tsv; full name in dialogue, shops, messages):"]
    for i, sh in sorted(shorts.items()):
        lim = 72 if i.startswith("11:") else 64
        px = T.measure(T.encode_text(sh, vwf=T.has_latin(sh)), vwf=False)
        lines.append(f"    {i} {sh!r} {px}/{lim} px (full {rows.get(i, ('', ''))[0]!r} {T.measure(name(i), vwf=False)} px)")
        if px > lim:
            b.error(f"short name {i} {sh!r} {px} px > {lim}")
    lines += ["", "Sentence/line checks:"] + [f"    {w:4d}/{l:4d} px  {what}" for what, w, l in u.checks]
    os.makedirs(b.out_dir, exist_ok=True)
    open(os.path.join(b.out_dir, "ui-fields.txt"), "w").write("\n".join(lines) + "\n")
    b.data["ui_overflow"] = over
    b.log(f"field widths: {len(over)} name/field overflows (see {os.path.join(b.out_dir, 'ui-fields.txt')}); "
          f"not errors: they go to the translator")

    missing = set(u.rows) - u.used
    if missing:
        b.error(f"en_inline.tsv rows not handled by mod_ui: {sorted(missing)}")
    for r in rep:
        b.log(r)
