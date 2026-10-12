"""Build module: message speed for English (docs/design.md).

- b00:$FE1D message speed table ($2092 per menu setting 1-5; $20 = 1 frame per character):
  20 40 A0 B0 C0 (1/2/5/5.5/6 f per char) -> 10 20 60 70 80 (0.5/1/3/3.5/4). English has ~2x the
  characters of the kana text, so the default setting (3) keeps roughly the original time per message.
- b03:$DE5E [0F] pause table (frames per setting): kept (20 20 60 80 C0); English lines take longer to read.
- Block 1A captions (final bosses): the bank 1 script sets a 6-frame per-character wait (`20 06`) on top of
  the text speed; English captions are ~2x longer, so the wait becomes 3.
"""
BANK = 0x2000
SPEED = bytes([0x10, 0x20, 0x60, 0x70, 0x80])
CAPTION_WAIT = 0x03


def apply(b):
    b.patch(0x1E1D, bytes.fromhex("20 40 A0 B0 C0"), SPEED)
    b.expect(0x7E5E, bytes.fromhex("20 20 60 80 C0"))
    for o in (0x31DB, 0x3211, 0x3247, 0x327F, 0x32B7):
        b.patch(o, bytes.fromhex("20 06"), bytes([0x20, CAPTION_WAIT]))
    b.log("speed table b00:$FE1D = " + SPEED.hex(" ") + "; [0F] table b03:$DE5E kept; "
          f"block 1A caption wait 6 -> {CAPTION_WAIT} (bank 1 0x31DB/0x3211/0x3247/0x327F/0x32B7)")
