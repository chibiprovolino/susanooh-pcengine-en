# Susano-O Densetsu text format (original Japanese ROM)

ROM: headerless 512 KiB, CRC32 CF73D8FC. File offsets below; bank = offset / 0x2000.

## Font (bank $35)
- 8x12 1bpp, 12 bytes per glyph, MSB = leftmost pixel.
- Hiragana block at 0x6B1A0 (JIS X0201 order, code 0xA0 = first), katakana 64 glyphs later,
  ASCII glyph = 0x6B7A0 + (c-0x20)*12 ('/' at 0x6B854).
- Kanji: 16x12, 24 bytes each (left 8 columns x12 rows, then right 8 columns), code 0x60 at 0x6BAA0.
  0x60.. = 凄王魔獣朱紗瓜生雪代東西南北男女人町村城洞窟塔船飛行機武沼森林湖大陸川砂漠岬海山
           空朝昼夕方夜闇日年強弱倒苦恐退剣盾鎧兜器悪邪教長祖力話攻防青真悟美
- Line buffer in RAM $26FD (CPU, MPR1=$F8), up to $70 codes; renderer draws glyphs into BG
  tiles at VRAM tile $50A+ (pixel plotting at bank0 $F593, so a VWF is feasible).

## Script
- Block pointer table: bank $38 CPU $C75C (file 0x7075C), 0x23 words.
  ptr bits 15-13 = bank offset added to $24, bits 12-0 = offset (mapped at CPU $6000, MPR3-5).
  0xC7A2 = unused placeholder (blocks 03 04 06 18 21).
- Huffman tree: bank $24 (file 0x48000), root CPU $4000 (MPR2). Node: byte0 bit7 -> leaf,
  value byte1; else bit 0 -> node+2, bit 1 -> node at (byte0<<8|byte1). Bits MSB first.
- Decoder: bank0 $F5D9 (bitstream ptr $204D/4E, mask $204F). Setup $F55D, bank map $E52C (X=$0F).
- String fetch: bank $38 $C680, reached through the far call b00:$E566 with X=$0A, Y=block, A=string index; it skips Y strings by decoding them,
  so each string is found by linear decode from block start.
  $74 bit0 = Huffman on; otherwise plain bytes are read from ($08).
- Strings end 0x00. Codes: 0x01 katakana on, 0x02 off, 0x0D newline, 0x0B wait for a press,
  0x06/0x07 new page after a wait, 0x1F n = insert dictionary word n (block 0x19),
  0xDE/0xDF dakuten/handakuten placed BEFORE the kana. In battle text (block 0x22)
  '[' = attacker, ']' = target, '^' = number.
- Text data spans 0x4833E-0x51DE3 (blocks), 1879 strings. `python3 tools/script.py BLOCK [COUNT]` prints a block.
- Free 0xFF space: ~15 KiB scattered (largest 0x55F7-0x6000, 0xB50D-0xC000); ROM can also
  be expanded to 1 MiB.

## Uncompressed UI text
- Besides the Huffman blocks, menus and system screens print plain strings from program banks.
  Most follow `jsr $EF5F` inline; others sit in tables.
  All known ones are in translation/en_inline.tsv (ID = INL:file offset), including:
  time of day 0xE1D8-0xE1E3 (朝 昼 夕方 夜, pointer table just before), level-up stat names
  0xF37C-0xF3A6 (table at CPU $D37C), backup-memory messages 0x12400-0x124EE,
  password screen 0x12AA8-0x12B01, continue/load menu 0x135D5-0x13626.
- Leave untouched: "!BM FORMAT!" (0x123E6) and "SUSA.NO.OH" (0x123F4), the backup-memory
  signature and save name; the password character table at 0x12F60.
- Choice options: 0x24 / 0x25 draw as 『 』 around each option (manual screenshot of the hire menu:
  ▶『やとう』). In the bonus password line (20:128) the same bytes bracket the password.
  0x5F is the price placeholder elsewhere (0E:090 "_で" shows "1300GOLDで"), but inside that
  password it sits where the manual's password screenshots show a separator; the patch copies 20:128's bytes verbatim.

## Tools
- tools/script.py  decode blocks (all_blocks, render)
- tools/hudis.py   HuC6280 disassembler
- tools/evscan.py  event script walker (docs/unused-lines.md)
- tools/rominfo.py checks a ROM dump (header, CRC32/MD5/SHA-1)
