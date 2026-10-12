#!/usr/bin/env python3
"""Module text: English script storage and fetch (docs/design.md).

apply(b):
- encodes and lays out translation/en_*.tsv with tools/textenc.py (every original (block, index) gets an entry:
  English, or the original Japanese bytes with the dictionary expanded);
- splits strings longer than 111 bytes into pieces chained with `03 n` (block $21);
- writes the index bank $48 ("text.index") and the strings from bank $49 ("text.strings");
- rewrites the block table b38:$C75C as (block, 0) words;
- assembles asm/fetch.s into "text.b38" and hooks b38:$C687 (jmp TEXT_FETCH);
- assembles asm/cont_b00.s into "text.chk" and hooks b00:$EF46 (print loop) and b07:$C192 (shop loop);
- assembles asm/cont_b01.s into "text.b01" and hooks b01:$C86A (cutscene/script loop);
- writes <out>/text-expected.json (bytes per fetch, for tests), <out>/text-pages.txt (layout report)
  and the proof sheets <out>/proof/*.png (tools/proof.py).
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textenc as T  # noqa: E402

NBLOCKS = 0x23
CONT = T.CONT_BLOCK
BANK = 0x2000
TABLE = 0x7075C                  # b38:$C75C block table, 0x23 words
HOOK_FETCH = 0x70687             # b38:$C687
HOOK_CHK = 0x0F46                # b00:$EF46
HOOK_B1 = 0x286A                 # b01:$C86A
HOOK_SHOP = 0xE192               # b07:$C192
INDEX_PAD = 64                   # empty entries after the last block's table
NO_SPLIT_BLOCKS = (0x22,)        # battle copy loop b06:$C8F7 is not patched (<= 62 bytes anyway)


def cpu_of(addr):
    return 0x6000 + (addr & 0x1FFF)


def apply(b):
    b.log(f"font widths: {T.widths() and T.WIDTHS_SOURCE}")
    r = T.build_all()
    strings, info = r['strings'], r['info']
    for e in r['errors']:
        b.error(e)
    for w in r['warnings']:
        b.log("warning: " + w)
    for sid, span, cls in T.BOLD_UNLISTED:     # quoted spans missing from translation/bold-spans.tsv
        b.log(f"warning: {sid} quoted span {span!r} not in bold-spans.tsv; drawn as {cls} (automatic rule)")
    nb = sum(1 for v in T.bold_spans().values() if v.rstrip('?') == 'bold')
    b.log(f"bold names/terms: translation/bold-spans.tsv {len(T.bold_spans())} spans, {nb} bold "
          f"(codes 09/0A, VWF only), {len(T.BOLD_UNLISTED)} unlisted")
    if r['missing']:
        b.log(f"warning: {len(r['missing'])} strings have no English, Japanese bytes kept: {' '.join(r['missing'])}")
    b.log("block 19 (dictionary) kept as Japanese bytes (expanded); nothing fetches it in this design")
    ev_err, ev_warn, ev = T.check_event_windows(r, b.src)
    for e in ev_err:
        b.error("event window: " + e)
    for w in ev_warn:
        b.log("warning: event window: " + w)
    b.log(f"event scripts (bank $0A): {ev['records']} print records ({ev['explicit']} with an explicit block), "
          f"{ev['continuations']} pages continuing another string's window and {ev['portrait']} portrait prints checked")

    # GOLD string printed by the shop loop over $26FD (en_inline INL:0E1A5): 0x5F must sit after it
    inline = T.load_tsv(os.path.join(T.TRANS, "en_inline.tsv"), include_inline=True)
    gold = inline.get("INL:0E1A5", ("GOLD", ""))[0]
    min_5f = len(T.encode_text(gold)) + 0

    # ---- pieces
    pieces = [b""]               # block $21 entry 0 stays empty (n is never 0)
    origin = {}                  # (CONT, n) -> block of the string it continues
    table = {}                   # (blk, idx) -> bytes stored for the fetch
    nsplit = 0
    for (blk, idx), s in sorted(strings.items()):
        sid = f"{blk:02X}:{idx:03d}"
        if len(s) <= T.LINEBUF_MAX:
            table[(blk, idx)] = s
            continue
        if blk in NO_SPLIT_BLOCKS or not info[sid]['policy'].split:
            b.error(f"{sid}: {len(s)} bytes > {T.LINEBUF_MAX} and its print loop has no continuation")
            table[(blk, idx)] = s[:T.LINEBUF_MAX]
            continue
        parts = T.split_pieces(s, min_5f=min_5f if blk == 0x0E else 0)
        nums = list(range(len(pieces), len(pieces) + len(parts) - 1))
        for k, p in enumerate(parts):
            body = p + (bytes([0x03, nums[k]]) if k < len(parts) - 1 else b"")
            if k == 0:
                table[(blk, idx)] = body
            else:
                origin[(CONT, len(pieces))] = blk
                pieces.append(body)
        nsplit += 1
        b.log(f"split {sid}: {len(s)} bytes -> {' + '.join(str(len(p)) for p in parts)} "
              f"(pieces 21:{', 21:'.join('%03d' % n for n in nums)})")
    if len(pieces) > 256:
        b.error(f"{len(pieces)} continuation pieces > 256")
    for n, p in enumerate(pieces):
        table[(CONT, n)] = p

    # ---- limits on what each fetch returns
    for (blk, idx), s in table.items():
        sid = f"{blk:02X}:{idx:03d}"
        if len(s) > T.LINEBUF_MAX:
            b.error(f"{sid}: fetch returns {len(s)} bytes > {T.LINEBUF_MAX}")
        if 0 in s:
            b.error(f"{sid}: 00 inside the string")
        if blk == 0x22 and len(s) > T.BATTLE_MAX:
            b.error(f"{sid}: battle message {len(s)} bytes > {T.BATTLE_MAX}")
        if 0x0E in (blk, origin.get((blk, idx))) and 0x5F in s and s.index(0x5F) < min_5f:
            b.error(f"{sid}: 0x5F at index {s.index(0x5F)} < {min_5f} (shop GOLD print overwrites it)")
        if blk == CONT and n_bad_start(s):
            b.error(f"{sid}: piece starts with 00/03")
        errs = []
        body = s[:-2] if len(s) >= 2 and s[-2] == 0x03 else s
        T.check_bytes(sid, body, errs)          # no 00/1F/03 inside, arguments never 00/03/1F
        for e in errs:
            b.error(f"{sid}: {e}")
        if len(s) >= 2 and s[-2] == 0x03 and not (1 <= s[-1] < len(pieces)):
            b.error(f"{sid}: 03 {s[-1]:02X} points outside block $21")

    # ---- string banks
    sb0, sb1 = b.claim("text.strings")
    ib0, ib1 = b.claim("text.index")
    for bank in range(sb0, sb1 + 1):
        if any(x != 0xFF for x in b.rom[bank * BANK:(bank + 1) * BANK]):
            b.error(f"bank ${bank:02X} is not free")
    for bank in range(ib0, ib1 + 1):
        if any(x != 0xFF for x in b.rom[bank * BANK:(bank + 1) * BANK]):
            b.error(f"bank ${bank:02X} is not free")
    blocks = {}
    for (blk, idx) in table:
        blocks.setdefault(blk, []).append(idx)
    pos = sb0 * BANK
    end = (sb1 + 1) * BANK
    addr = {}
    empty_addr = None
    order = sorted(table)
    per_block = {}
    for key in order:
        s = table[key] + b"\x00"
        if pos + len(s) > end:
            b.error("string banks full")
            break
        b.rom[pos:pos + len(s)] = s
        addr[key] = pos
        per_block[key[0]] = per_block.get(key[0], 0) + len(s)
        if empty_addr is None and s == b"\x00":
            empty_addr = pos
        pos += len(s)
    if empty_addr is None:
        empty_addr = pos
        b.rom[pos] = 0
        pos += 1
    used = pos - sb0 * BANK
    b.log(f"strings: {len(table)} entries ({sum(1 for k in table if k[0] != CONT)} originals + {len(pieces)} "
          f"block $21 entries), {used} bytes in banks ${sb0:02X}-${(pos - 1) // BANK:02X} "
          f"({end - pos} bytes free up to ${sb1:02X})")

    # ---- index bank
    ibase = ib0 * BANK
    dir_size = NBLOCKS * 3
    tpos = ibase + dir_size
    for blk in range(NBLOCKS):
        idxs = sorted(blocks.get(blk, []))
        n = (max(idxs) + 1) if idxs else 1
        tcpu = cpu_of(tpos)
        b.rom[ibase + 3 * blk:ibase + 3 * blk + 3] = bytes([ib0, tcpu & 0xFF, tcpu >> 8])
        for i in range(n):
            a = addr.get((blk, i), empty_addr)
            c = cpu_of(a)
            b.rom[tpos:tpos + 3] = bytes([a // BANK, c & 0xFF, c >> 8])
            tpos += 3
        if not idxs:
            b.log(f"block {blk:02X}: no strings (1 empty entry)")
    # insurance: an index past the end of the last block reads these (empty string), never 0xFF bytes
    c = cpu_of(empty_addr)
    for i in range(INDEX_PAD):
        b.rom[tpos:tpos + 3] = bytes([empty_addr // BANK, c & 0xFF, c >> 8])
        tpos += 3
    if tpos > (ib1 + 1) * BANK or (tpos - 1) // BANK != ib0:
        b.error("index does not fit in one bank")
    b.log(f"index: bank ${ib0:02X}, {tpos - ibase} bytes (directory {dir_size} + {(tpos - ibase - dir_size) // 3} entries"
          f" incl. {INDEX_PAD} padding)")
    for blk in sorted(per_block):
        cnt = len(blocks[blk])
        mx = max(len(table[(blk, i)]) for i in blocks[blk])
        if blk == CONT:
            b.log(f"block {blk:02X}: {cnt:3d} continuation pieces, {per_block[blk]:5d} bytes, longest {mx}")
            continue
        orig = max((len(strings[(blk, i)]) for i in blocks[blk] if (blk, i) in strings), default=0)
        b.log(f"block {blk:02X}: {cnt:3d} strings, {per_block[blk]:5d} bytes, longest {orig} (per fetch {mx})")

    # ---- block table b38:$C75C -> (block, 0)
    old = b.src[TABLE:TABLE + 2 * NBLOCKS]
    new = bytes(x for blk in range(NBLOCKS) for x in (blk, 0))
    b.patch(TABLE, old, new)

    # ---- code
    lab = b.asm_region("fetch.s", "text.b38", {"IDX_BANK": ib0})
    f = lab["TEXT_FETCH"]
    b.patch(HOOK_FETCH, bytes([0x48, 0x20, 0x53]), bytes([0x4C, f & 0xFF, f >> 8]))
    lab = b.asm_region("cont_b00.s", "text.chk")
    c, cs = lab["TEXT_CHK"], lab["TEXT_CHKS"]
    b.patch(HOOK_CHK, bytes.fromhex("FF 91 04 C9 00 F0 0B"), bytes([0x20, c & 0xFF, c >> 8, 0xB0, 0x0D, 0xEA, 0xEA]))
    b.patch(HOOK_SHOP, bytes.fromhex("C9 00 F0 27 C9 5F D0 18"),
            bytes([0x20, cs & 0xFF, cs >> 8, 0xB0, 0x26, 0xD0, 0x19, 0xEA]))
    lab = b.asm_region("cont_b01.s", "text.b01")
    c1 = lab["TEXT_B1CHK"]
    b.patch(HOOK_B1, bytes.fromhex("BD FD 26 D0 03 4C AC C6"), bytes([0x20, c1 & 0xFF, c1 >> 8, 0x90, 0x03, 0x4C, 0xAC, 0xC6]))

    # ---- outputs for tests, reviewers and other modules
    b.data['text'] = {'table': table, 'strings': strings, 'info': info, 'meta': r['meta'], 'pieces': len(pieces)}
    os.makedirs(b.out_dir, exist_ok=True)
    exp = {f"{k[0]:02X}:{k[1]:03d}": v.hex() for k, v in sorted(table.items())}
    exp["_labels"] = {k: b.labels[k] for k in ("TEXT_FETCH", "TEXT_CHK", "TEXT_CHKS", "TEXT_REFILL", "TEXT_B1CHK")}
    json.dump(exp, open(os.path.join(b.out_dir, "text-expected.json"), "w"), indent=0)
    write_pages(os.path.join(b.out_dir, "text-pages.txt"), r, table)
    import check_choices
    for e in check_choices.check(os.path.join(b.out_dir, "text-pages.txt")):
        b.error("choice box: " + e)
    b.log(f"{nsplit} strings split into continuation pieces; {sum(1 for v in info.values() if v['auto'])} "
          f"strings needed automatic page breaks ({sum(v['auto'] for v in info.values())} breaks)")
    for sid, v in sorted(info.items()):
        if v['auto']:
            b.log(f"auto page break: {sid} x{v['auto']}")
    if os.environ.get("SUSANOO_NO_PROOF") != "1":
        try:
            import proof
            n = proof.render_all(os.path.join(b.out_dir, "proof"), r)
            b.log(f"proof sheets: {n} PNG files in {os.path.join(b.out_dir, 'proof')}")
        except ImportError:
            b.log("proof.py not present, no proof sheets")


def n_bad_start(s):
    return len(s) > 0 and s[0] in (0x00, 0x03)


def write_pages(path, r, table):
    lines = [f"# Layout of every string (font widths: {r['meta']['widths']})",
             f"# placeholders px: {r['meta']['ph']} (longest name {r['meta']['longest_name']})", ""]
    for sid, v in sorted(r['info'].items()):
        pol = v['policy']
        blk, idx = int(sid[:2], 16), int(sid[3:])
        lines.append(f"{sid} [{pol.kind} {pol.width}px x{pol.lines}] {len(r['strings'][(blk, idx)])} bytes"
                     f"{' source=' + v['source'] if v['source'] != 'en' else ''}{' auto=%d' % v['auto'] if v['auto'] else ''}")
        for p in v['pages']:
            for px, text, width in p['lines']:
                lines.append(f"    {px:3d}|{text}")
            lines.append(f"    --- {p['end']}")
        for w in v['warnings']:
            lines.append(f"    ! {w}")
        for e in v['errors']:
            lines.append(f"    !! {e}")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
