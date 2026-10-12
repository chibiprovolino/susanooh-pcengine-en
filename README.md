# Susano Oh Densetsu English translation

English translation patch for the 1989 RPG Susano Oh Densetsu, published by Hudson Soft for the PC-Engine.
Sequel to Go Nagai's manga Susano Oh. Names and terms follow the HappyScans! scanlation.

Hacking is 100% vibe coded. Translation had a first draft reviewed by a native speaker (who wishes to remain anonymous),
and rewritten using their notes by a non-native English speaker. There is some uncertainty about an enemy, who is a 
reference to an original character in Yasutaka Nagai's novels, so it was left as "Byakuojo". It's probably just a name.

Works on real hardware (Super SD System 3 ODE) and MiSTer (June 2026 stable core). Fully playtested.

Original game included a password system in kana (left as it is) and a backup ram option with three slots: be sure to 
have it on in your emulator/ODE of choice, though it usually is by default.

QoL fixes are press to complete for text boxes, optional for battle text (enabled by default). Preferences are saved.

Title text and two signs in kanji have been re-drawn (badly) by a human.

There's a nasty bug in the original game: just don't buy more than one Tape Recorder or you won't be able to reach
the ending.

Repo includes vibed notes on unused text.

Vibed technical notes:

## Applying the patch
Use a BPS patcher (Floating IPS, beat, or Rom Patcher JS) with `patch/susanoo-en-v1.0.bps` on the Japanese ROM:

    Headerless, 524,288 bytes
    CRC32 CF73D8FC
    MD5   bdb29558fea5b2e7550087ad79718a4a


Patched ROM: 1,048,576 bytes, CRC32 56D311CB, MD5 92cb5a00b728ea26e616f80fc514c9b3.


## Building from source
Requires Python 3 with Pillow, and cc65 (ca65/ld65).

1. Put the original ROM in `rom/` (see `rom/README.md`).
2. Run `python3 tools/build.py`.

It writes `build/susanoo-en.pce`, `build/susanoo-en.bps` and a report. The build stops if a line does not fit its window.

## Layout
- `translation/` the English script (`en_*.tsv`), menu short names, bold terms
- `asm/` 6502 (HuC6280) code added to the game
- `tools/` build scripts and modules, font source in `tools/font/`
- `gfx/` title logo and signs
- `docs/` how the patch works, the text format, and lines the original game never shows

The ROM is not included.
