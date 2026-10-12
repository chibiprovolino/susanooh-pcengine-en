# How the patch works

Target: 凄ノ王伝説 (Hudson, 1989), Japanese HuCard, CRC32 CF73D8FC. Output: 1 MB ROM.

## Build
`python3 tools/build.py` reads the original ROM, the translation files and the assembly, and writes `build/susanoo-en.pce`. It needs Python 3 with Pillow, and cc65 (`apt-get install cc65`). It stops on any line that doesn't fit its box.

## Text
- Script: `translation/en_*.tsv`, one line per ID (block:index), same order as the Japanese.
- The original compresses text per block. The patch stores English in its own compressed format in the new ROM half and replaces the game's read routine (`asm/fetch.s`, `tools/mod_text.py`).
- Layout is done at build time (`tools/textenc.py`): word wrap, a new line after each sentence, page breaks, centred captions.

## Font
- Proportional font with bold (`tools/font/`, `asm/vwf_*.s`). Letters are drawn into tiles on the fly.
- Menus have room for few letter tiles; extra tiles go into unused video memory.

## Menus
- Labels and short strings in the program code: `translation/en_inline.tsv`, `tools/mod_ui.py`.
- Short menu names for long items and places: `translation/short-names.tsv`.

## Options and pacing
- Battle text: Normal / Press to skip / Off (`asm/skip_b06.s`).
- Press to finish everywhere else (`asm/skip_b00.s`).

## More
- `design.md`: ROM, RAM and free-space map, text encoding, module interfaces.
- `text-format.md`: the original script format.
- `unused-lines.md`: lines of the original game that are never shown.
