"""Build module: battle text option (docs/design.md).

- asm/skip_b00.s -> region "skip.b00" (D_STUB, P_STUB, E_STUB), asm/skip_b06.s -> "skip.b06" (GATE).
- Option $2784 (13:014, choices 13:017): 0 Normal (the original behaviour and pacing), 1 Press to skip
  (normal speed; a fresh press of I/II finishes the current gated battle message at once and the battle goes
  on without its pause; holding I/II prints each message at once and shows it for 16 frames), 2 Off (the
  original Hide). The option is always listed and survives speed 4/5. Default at power-on: Press to skip.
- The English 13:017 needs three [0C] stops for the third choice.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BANK = 0x2000


def off(bank, cpu):
    return bank * BANK + (cpu & 0x1FFF)


def le(a):
    return bytes([a & 0xFF, a >> 8])


def apply(b):
    l0 = b.asm_region("skip_b00.s", "skip.b00")
    l6 = b.asm_region("skip_b06.s", "skip.b06")
    # b00:$F136 (speed set on window open) is no longer hooked: Press to skip keeps the normal speed.
    b.patch(off(0, 0xEECD), bytes.fromhex("A2 0A 20"), b"\x4C" + le(l0["E_STUB"]))
    b.patch(off(3, 0xCB90), bytes.fromhex("AC 83 27 BE 5E DE"), b"\x20" + le(l0["P_STUB"]) + b"\xEA" * 3)
    b.patch(off(3, 0xCEC7), bytes.fromhex("9F 98 15"), b"\x20" + le(l0["D_STUB"]))
    b.patch(off(6, 0xC8A4), bytes.fromhex("AD 84 27"), b"\x4C" + le(l6["GATE"]))
    # power-on defaults (b00 $EE6A): battle text starts as Press to skip; speed 3, HP display off
    b.patch(off(0, 0xEE6A), bytes.fromhex("A9 02 8D 70 27 A9 02 8D 83 27 9C 84 27 60"),
            bytes.fromhex("A9 02 8D 70 27 8D 83 27 A9 01 8D 84 27 60"))
    # text skip for all messages: page complete at every wait/menu, new EED3 window
    b.patch(off(3, 0xCA99), bytes.fromhex("97 98 60"), b"\x4C" + le(l0["W_STUB"]))
    b.patch(off(0, 0xF136), bytes.fromhex("AE 83 27"), b"\x20" + le(l0["F_STUB"]))
    # 0B/0E wait: page complete for the whole wait, so the cursor redraws never swallow a press
    b.patch(off(3, 0xCB5D), bytes.fromhex("20 8F CA"), b"\x20" + le(l0["X_STUB"]))
    b.patch(off(3, 0xCB78), bytes.fromhex("20 9C CA"), b"\x20" + le(l0["Y_STUB"]))
    # options menu (bank 5): always list "Battle Messages", keep it on speeds 4/5, accept a third choice
    b.patch(off(5, 0xC025), bytes.fromhex("93 02"), bytes.fromhex("80 0C"))
    b.patch(off(5, 0xC087), bytes.fromhex("9C 84 27"), bytes.fromhex("EA EA EA"))
    b.patch(off(5, 0xC0A4), bytes.fromhex("02"), bytes.fromhex("03"))
    # the third stop must exist in the English 13:017 (text module owns the string)
    try:
        import textenc as T
        t = T.load_tsv().get("13:017", ("", ""))[0]
        stops = t.count("[0C]") + t.count("»")
        if stops < 3:
            b.log(f"WARNING: 13:017 {t!r} has {stops} cursor stops; Off (third choice) needs 3, "
                  f"e.g. ' [0C]Normal [0C]Press to skip [0C]Off' (text/translation owner)")
    except Exception as e:  # pragma: no cover
        b.log(f"WARNING: could not check 13:017 ({e})")
    b.log("battle text option: $2784 0 Normal / 1 Press to skip / 2 Off; option always listed")
    b.log("text skip (all other messages): a fresh I/II press completes the page; hooks b03 $CA99, b00 $F136")
