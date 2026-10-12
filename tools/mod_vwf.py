"""Build module: the variable-width font renderer (docs/design.md).

- asm/vwf_far.s  -> bank $60 (claimed "vwf.far"), assembled at $4000 (MPR2): the VWF core.
- asm/vwf_b03.s  -> b03:$DE63+ (claimed "vwf.b03"): putc hook, trampoline (maps bank $60 at MPR2
  and the font bank $61 at MPR3), cursor bypass, window reset, slot-exhaustion handler.
- Slot pool (118 cells, shared with the original glyph cache): a new VWF cell releases the slot the
  cell showed before; when no slot is free, the reference counts are rebuilt from the BAT and the
  window save stack (vwf_gc) once, then the cell is skipped with an error flag (never BRK).
- Hooks in bank 3 (original bytes asserted): $CC62 putc dispatch, $CA68/$CA8C cursor draws,
  $CABA window open/close reset, $CD37 the BRK on a full glyph cache.
RAM: $2604-$2638 (asm/vwf_ram.inc). Codes handled: 04 VWF on, 05 VWF off, 09 bold on, 0A bold off
(bold set in bank $61 at $6880/$6900), 15 n pen x = n-0x20 px.

"""
BANK = 0x2000


def off(bank, cpu):
    return bank * BANK + (cpu & 0x1FFF)


def jmp(addr):
    return bytes([0x4C, addr & 0xFF, addr >> 8])


def jsr(addr):
    return bytes([0x20, addr & 0xFF, addr >> 8])


def apply(b):
    font_bank = b.data.get("font_vwf_bank")
    if font_bank is None:
        font_bank = 0x61
        b.log("font module did not run: assuming the VWF font in bank $61 (nothing will draw without it)")
    first, last = b.claim("vwf.far")
    base = first * BANK
    if any(x != 0xFF for x in b.rom[base:base + BANK]):
        b.error(f"bank ${first:02X} is not empty (0xFF) before the VWF core is written")
        return
    core, far = b.asm("vwf_far.s", 0x4000, {"VWF_FONT_BANK": font_bank}, max_size=BANK)
    b.write(base, core)
    b.log(f"vwf_far.s -> bank ${first:02X} $4000 (file 0x{base:05X}), {len(core)}/{BANK} bytes")

    entries = ("vwf_core", "vwf_reclaim", "vwf_finalize", "vwf_unspill")     # vwf_far X = 0, 2, 4, 6
    if core[:8] != b"".join(far[n].to_bytes(2, "little") for n in entries):
        b.error("vwf_far.s must start with the word table " + ", ".join(entries))
    lab = b.asm_region("vwf_b03.s", "vwf.b03", {"VWF_CODE_BANK": first, "VWF_FONT_BANK": font_bank})

    # hooks in bank 3 (MPR6 $C000)
    b.patch(off(3, 0xCC62), bytes.fromhex("FF 91 FA"), jmp(lab["vwf_hook"]))
    b.patch(off(3, 0xCA68), bytes.fromhex("4C 50 CC"), jmp(lab["vwf_cursor_putc"]))
    b.patch(off(3, 0xCA8C), bytes.fromhex("4C 50 CC"), jmp(lab["vwf_cursor_putc"]))
    b.patch(off(3, 0xCABA), bytes.fromhex("64 92 64 93"), jsr(lab["vwf_winreset"]) + b"\xEA")
    b.patch(off(3, 0xCD37), bytes.fromhex("00 4C C6 CD"), jmp(lab["vwf_exhaust"]) + b"\xEA")
    # $CFD9 release loop: ldy $8E / cpy #$76 / bcs $D00F -> jsr vwf_relx / bcs $D00F / nop
    b.patch(off(3, 0xCFF8), bytes.fromhex("A4 8E C0 76 B0 11"), jsr(lab["vwf_relx"]) + bytes.fromhex("B0 12 EA"))
    # window close $C3F9: jsr $C295 (BAT back from the save stack) -> jsr vwf_wclose (unspill first)
    b.patch(off(3, 0xC406), bytes.fromhex("20 95 C2"), jsr(lab["vwf_wclose"]))
    b.log("hooks: b03:$CC62 putc -> $%04X, $CA68/$CA8C cursor -> $%04X, $CABA window reset -> $%04X, "
          "$CD37 BRK -> $%04X, $CFF8 release -> $%04X, $C406 close -> $%04X; RAM $2604-$263F, $2660-$26BC"
          % (lab["vwf_hook"], lab["vwf_cursor_putc"], lab["vwf_winreset"], lab["vwf_exhaust"], lab["vwf_relx"],
             lab["vwf_wclose"]))
    b.data["vwf_ram"] = {"depth": 0x2604, "px": 0x2605, "open": 0x2606, "err": 0x260B, "errcnt": 0x260C,
                         "used": 0x2612, "gcoff": 0x2634, "gccnt": 0x2635,
                         "gcfree": 0x2636, "relcnt": 0x2637, "bold": 0x2638, "ext_ref": 0x2660,
                         "dedup": 0x26B8, "extused": 0x26B9, "extpk": 0x26BA}
