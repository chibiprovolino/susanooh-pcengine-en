# Susano-O Densetsu English patch: design

ROM, RAM and free-space map, text encoding and the interfaces between the build modules
(script format: text-format.md). Addresses: "b38:$C687" = bank $38 at CPU $C687; file offset =
bank*0x2000 + (cpu & 0x1FFF). Zero page is $2000 ("$7F" = $207F).

## 1. ROM layout (1 MiB, banks $00-$7F)
| Banks | Use | Owner |
|---|---|---|
| $00-$3F | original, patched in place | all (see 4) |
| $40-$47 | copy of the FINAL $00-$07 (insurance against mirror reads; made last) | build |
| $48 | string index: directory (0x23 x 3 bytes) + 3-byte entries (bank, lo, hi) per string | text |
| $49-$57 | English strings, plain bytes, packed; a string may cross one bank boundary | text |
| $58-$5F | relocated UI strings + reorder code reached by far call | ui |
| $62 | "gfx.far", MPR3: edited-logo sprite list, code asm/logo_list_far.s + 4-byte entries at +$0000 ($6000; or the old 29-cell stab when LOGO_ENABLED); edited title-bg tile patches, code asm/title_bg_far.s + data at +$1000 ($7000) | gfx |
| $63 | "gfx.far": edited title logo cells (16x16, 4 planes, 128 bytes each, in upload order), uploaded by asm/logo_b04.s to VRAM $6000 (cells 0-28) and $6C00 (cells 48-63) | gfx |
| $60 | VWF code (mapped at MPR2 $4000 by the bank 3 trampoline) | vwf |
| $61 | VWF font (mapped at MPR3 $6000): widths at $6000 (128 bytes, index = code), glyphs at $6080 + code*16 (16 rows, MSB = left); bold set: widths at $6880, glyphs at $6900 + code*16 (row \| row>>1, advance +1) | font |
| $64-$7F | spare, 0xFF | |
Title hooks (gfx): b01 $C299 credit line + BG patches (always); b04 $C2AD logo upload; b01 $CA85 `jsr $CB34` -> L_STUB (asm/title_b01.s): logo list table $D83B -> new layout. Title VRAM: cell 29 ($6740) = START cursor, $6780-$6BFF unknown data (left alone), $6C00-$6FFF free, SAT at $7000.
Old Huffman text (0x4833E-0x51DF4) stays as dead data.

## 2. RAM
| Range | Use | Owner |
|---|---|---|
| $2604-$263F | VWF state (pen px, open slot, cur[16], next[16], mode depth, flags; $2638 bold) | vwf |
| $2640-$264F | continuation (saved $71-$73) | text |
| $2650-$265F | UI reorder scratch | ui |
| $3200-$3275 | VWF slot recount / spill / unspill scratch only (the game's window/scroll row buffer, refilled before every use) | vwf |
| $2660-$26BC | VWF extension slots (refcounts $2660, codes $2687), spill group ($26AE-$26B7), statistics | vwf |
| VRAM $5B2-$5FF | VWF extension slots: 39 two-tile cells, field mode only (cache base $20A); zero and unreferenced in 208 states (sprites end $597, portrait $598-$5B0) | vwf |
| VRAM above the save stack ($75/$76, < $7C00) | VWF spill records (8 words per cell) while a top window hides spilled cells; markers $780-$7FF in save-stack words only | vwf |
| $26BD | vwf_keep: vwf_winreset keeps the pen/cell while set (ui PANELKEEP around b07 $C081) | vwf/ui |
| $26C0 | text skip flag: bit7 skippable battle message, bit4 fast, bit5 battle message in Normal, bit3 field page being completed (skip_b00.s) | skip |
$2604-$26C7 is unused by the original game.

## 3. Free space in original banks (claimed regions; assert 0xFF before writing)
| Region | Owner |
|---|---|
| b00 $FE30-$FEBF | text (CHK continuation in the $EF39 loop) |
| b00 $FEC0-$FF5F | ui (PSTR relocated-string printer, far-call helpers) |
| b00 $FF60-$FFF5 | skip (D_STUB, W_STUB, F_STUB, P_STUB, E_STUB, X_STUB, Y_STUB; vectors start at $FFF6) |
| b01 $DDD4-$DE2F | text (B1CHK for the cutscene loop) |
| b01 $DE30-$DFFF | gfx (title credit line, T_STUB + tile data) |
| b04 $DED1-$DFFF | gfx (title logo upload G_STUB) |
| b03 $DE63-$DFFF | vwf (putc hook + trampoline) |
| b06 $DC89-$DC9E | skip (gate) ; b06 $DC9F-$DFFF ui |
| b07 $DEBD-$DFFF | ui (time-of-day tables, inn wake-up table + INN_TOD etc.) |
| b09 $DFB4-$DFFF | ui (short-name stubs for the menu name printers) |
| b38 $DE73-$DFFF | text (new FETCH) |
Every module asserts the original bytes at each hook site before patching.

## 4. Text encoding (English byte table)
- 0x00 end. Control codes as in the Japanese: 01/02, 06, 07, 0B, 0C, 0D, 0E, 0F; 10-14 + argument.
- New codes:
  - `03 n`: continue with string n of block $21 (inserter-made pieces; handled in the print loops).
  - `04` VWF on / `05` VWF off (single byte; original putc treats both as no-ops). Depth counter: 04 +1, 05 -1,
    reset to 0 on window open/close. Glyphs 0x20-0x7F draw proportionally while depth > 0.
  - `15 n`: set the pen to pixel x = n - 0x20 on the current line (n in 0x20-0xFF, never 00/1F). For centering.
  - `09` bold on / `0A` bold off (original no-ops at $CB26; VWF only, reset on window open and when the VWF depth
    returns to 0). Made by the encoder from "quoted" spans classed bold in translation/bold-spans.tsv: the
    quotes are dropped and trailing punctuation stays regular. `08` stays the filler no-op used by ui padding.
- Characters: 0x20-0x5A = ASCII (space, punctuation, digits, A-Z) except as below; 0x61-0x7A = a-z (VWF only).
  0x22 = “, 0x7C = ”, 0x27 = ’ (apostrophe), 0x60 = ‘, 0x7B = … (inserter turns "..." into it), 0x7D = — (em dash).
  0x28/0x29 redrawn as ( ). Keep: 0x23 (END key), 0x24/0x25 (『 』), 0x3C/0x3E arrows, 0x40, 0x5B-0x5F
  (cursor/placeholder bytes: [ = attacker, ] = target, ^ = number in battle, _ = number in shops).
- TSV markup: `|` = 0D; `▼` = 0B, plus 0D when more text follows (JP pattern [0B][0D][07] / [0B][0D] scroll);
  `»` = 20 0C (option indent + cursor stop; the 『 』 brackets are dropped in English), `%` = nothing;
  `{ATK}` 5B, `{TGT}` 5D, `{N}` = 5E in block 22 and 5F elsewhere; `[XX]` verbatim; after a 10-1F code the next
  character is its argument (a kanji there = its code, e.g. [13]村 = 13 7A).
- Rule: every string that contains lowercase or is prose is wrapped 04 … 05. Uppercase-only labels and
  tables (HP, EXP, GOLD, LVL…) stay fixed so the original dedup path and layout apply.
- Kana kept verbatim where the data is Japanese: the bonus password in 20:128 (bytes exactly as the original),
  the password kana grid. These print in fixed mode.

## 5. Storage and fetch (module: text)
Plain bytes + per-string pointer table; b38:$C687 → jmp FETCH ($DE73+);
block table b38:$C75C rewritten as block numbers; strings > 111 bytes split at page breaks into pieces ending
in `03 n` (block $21), handled by CHK (b00, $EF46 hook), CHKS (b07:$C192 shop loop hook, for the two 0E strings
over 111 bytes) and B1CHK (b01, $C86A hook). Limits enforced by the
build: ≤ 111 bytes per fetch, block 22 ≤ 62 (battle copy), block 0E ≤ 111 with 0x5F at index ≥ 4, no 00/1F
inside a string or as an argument.

## 6. Wrap, pages, centering (module: text, using the font width table)
- Dialogue blocks: 184 px per line (portrait-safe), 4 lines per page; auto page break `0B 0D 07`
  (`0B 0D 06` if the string itself clears with 06). Lines since the last wait never exceed the box height.
- Battle (22): 224 px x 2 lines with the longest names substituted (party 7-cell field names, enemy names).
- Cutscene (17 and other bank-1 captions): 160 px x 4 lines (screen x 56-215), wrapped at 144 px and each line's ink
  centred on the screen centre (pen 0-143 = x 56-199) with `15 n`. The opening (17) uses 3 lines per page: the 4th sits in the overscan on 224-line displays.
- Item/gold messages: 224 x 3. Menus and fields: per-field widths in tools/textenc.py.
- The build writes a report of every string's pages and a PNG proof sheet rendered with the real font.

## 7. VWF (module: vwf)
Hook b03:$CC62 → trampoline → VWF core in bank $60 at MPR2. Pen = $7F/$80 cells +
sub-cell px; each VWF cell takes its own slot (marked so dedup never matches) and gets 16 rows (glyph rows 1-14
usable). Snap to the next cell (finish the open cell) on 0C, 0D, 06, 07, 0B, 0E, 11, 12, window open/close, any
external change of $7F/$80, and before a fixed-mode glyph. Never BRK on slot exhaustion: skip drawing and set an
error flag in VWF RAM; patch the original BRK at b03:$CD37 to a safe path too. $CEC7 once per glyph.

## 8. Font (module: font)
Original design. Source: tools/font/font.txt (one block per glyph: code, advance, 16 rows of '.'/'#').
Metrics: cap height 8-9, x-height 6, descenders 2-3 within cell rows 1-14 (line pitch 16); 1 px spacing in the
advance; digits one shared advance. Two compiled outputs: VWF glyphs + width table (bank $61, layout in §1) and fixed 8x12
versions of 0x20-0x5A for the original path (font bank $35 at 0x6B7A0, cell rows 2-13), same design.
tools/font/widths.json is the width table the inserter reads.

## 9. UI strings and reorders (module: ui)
en_inline.tsv strings in place when they fit, else relocated with `jsr PSTR; .dw ptr` .
Reorders in code: level-up ("Susa's Level rose by 1."), password prompt ("Please enter X."), teleport
("teleported to X"), damage taken, "<N> EXP gained". Fixed templates keep byte positions. Time-of-day table
repointed. Password labels ≤ 6 cells. Menu-only short names (translation/short-names.tsv, blocks 14/11) are used by
the equipment slots, the single-member equip window, the item bag and the teleport list; shops, dialogue and
messages keep the full names. Item/place/enemy names are checked against their field widths.

## 10. Battle text skip and speed (module: skip)
Option always listed, 3 settings Normal / Press to skip / Off ($2784 0/1/2; 13:017). Normal = the original
pacing (a press only ends the [0F] pause). Press to skip: in a gated battle message a press of I/II (or holding
it) prints the rest instantly and the pause becomes 16 frames with no release wait; a second press ends it.
Off = the original Hide. Default at power-on: Press to skip; the setting is kept in backup memory.
The message speed table b00:$FE1D and the cutscene speed argument are retuned for English (tools/mod_speed.py).
All other messages (field, events, shops, inns, menus; not cutscenes, not gated battle messages): always-on text
skip, a fresh I/II press while a page prints with a delay completes the page; the next press works as usual
(cleared at every 0B/0E wait and menu via $CA8F, at EED3 window open and window close).

## 11. Build (tools/build.py)
`python3 tools/build.py` → build/susanoo-en.pce (1 MiB), build/susanoo-en.bps (tools/bps.py, source = the
original), build/report.txt (bytes per bank, free space, overflow errors, warnings), build/proof/*.png.
Modules are tools/mod_<name>.py with `apply(b)`; `b` gives the ROM bytearray, `b.asm(file, defines)`
(ca65/ld65 → bytes), `b.expect(off, bytes)`, `b.claim(region)`, `b.log()`. Order: text, font, vwf, ui, skip, speed,
gfx, then the bank $40-$47 copy.
