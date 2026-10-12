#!/usr/bin/env python3
"""Build the English Susano-O Densetsu ROM and BPS patch from the clean dump.

  python3 tools/build.py [--only mod1,mod2] [--no-bps] [--out DIR]

--out writes the ROM/patch/report to DIR instead of build/ (use a scratch dir while developing,
so parallel work does not overwrite build/).

Steps: verify the source dump (SHA-1) -> expand to 1 MiB -> run the modules in order
(tools/mod_<name>.py, each with apply(b)) -> copy the final banks $00-$07 to $40-$47 ->
write build/susanoo-en.pce, build/susanoo-en.bps and build/report.txt.
The design and the region ownership are in docs/design.md.
"""
import hashlib, importlib, os, re, subprocess, sys, tempfile, zlib

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "rom", "Susanoo Densetsu (Japan).pce")
SRC_SHA1 = "43853c5622992dfdc6844376f61b8998e44e2eaf"
OUT_DIR = os.path.join(BASE, "build")
ASM_DIR = os.path.join(BASE, "asm")
MODULES = ["text", "font", "vwf", "ui", "skip", "speed", "gfx"]
BANK = 0x2000
SIZE = 0x100000

# Claimed free regions (docs/design.md): name -> (bank, cpu_start, cpu_end_inclusive)
REGIONS = {
    "text.chk":   (0x00, 0xFE30, 0xFEBF),
    "ui.b00":     (0x00, 0xFEC0, 0xFF5F),
    "skip.b00":   (0x00, 0xFF60, 0xFFF5),
    "text.b01":   (0x01, 0xDDD4, 0xDE2F),
    "gfx.b01":    (0x01, 0xDE30, 0xDFFF),   # title credit line
    "gfx.b04":    (0x04, 0xDED1, 0xDFFF),   # title logo upload
    "vwf.b03":    (0x03, 0xDE63, 0xDFFF),
    "skip.b06":   (0x06, 0xDC89, 0xDC9E),
    "ui.b06":     (0x06, 0xDC9F, 0xDFFF),
    "ui.b07":     (0x07, 0xDEBD, 0xDFFF),
    "ui.b09":     (0x09, 0xDFB4, 0xDFFF),
    "text.b38":   (0x38, 0xDE73, 0xDFFF),
}
# Expansion banks: name -> (first_bank, last_bank)
BANKS = {
    "text.index": (0x48, 0x48),
    "text.strings": (0x49, 0x57),
    "ui.far": (0x58, 0x5F),
    "vwf.far": (0x60, 0x60),
    "font.vwf": (0x61, 0x61),
    "gfx.far": (0x62, 0x63),
}


def off(bank, cpu):
    return bank * BANK + (cpu & 0x1FFF)


class Build:
    def __init__(self):
        src = open(SRC, "rb").read()
        if hashlib.sha1(src).hexdigest() != SRC_SHA1:
            sys.exit(f"source ROM does not match SHA-1 {SRC_SHA1} (headered or wrong dump?)")
        self.src = src
        self.rom = bytearray(src) + bytearray(b"\xFF" * (SIZE - len(src)))
        self.lines = []
        self.errors = []
        self.claimed = {}          # region name -> module that claimed it
        self.labels = {}           # global symbol table filled by asm()
        self.data = {}             # free-form data modules pass to each other (e.g. font widths)
        self.module = None

    # ---- logging -------------------------------------------------------------
    def log(self, msg):
        line = f"[{self.module or 'build'}] {msg}"
        self.lines.append(line)
        print(line)

    def error(self, msg):
        self.errors.append(f"[{self.module or 'build'}] {msg}")
        self.log("ERROR: " + msg)

    # ---- ROM access ----------------------------------------------------------
    def expect(self, offset, data):
        """Assert the ORIGINAL bytes at a file offset before patching it."""
        data = bytes(data)
        have = self.src[offset:offset + len(data)]
        if have != data:
            raise AssertionError(f"0x{offset:05X}: expected {data.hex(' ')}, original has {have.hex(' ')}")

    def write(self, offset, data):
        self.rom[offset:offset + len(data)] = data

    def patch(self, offset, old, new):
        """expect(old) then write(new); both at a file offset."""
        self.expect(offset, old)
        self.write(offset, new)

    def claim(self, name):
        """Return (bank, start, end) of a claimed region and check it is still 0xFF in the source."""
        owner = self.claimed.get(name)
        if owner and owner != self.module:
            raise AssertionError(f"region {name} already claimed by {owner}")
        self.claimed[name] = self.module
        if name in REGIONS:
            bank, a, z = REGIONS[name]
            o = off(bank, a)
            seg = self.src[o:o + z - a + 1]
            if any(x != 0xFF for x in seg):
                raise AssertionError(f"region {name} is not free (0xFF) in the source ROM")
            return bank, a, z
        return BANKS[name]

    # ---- assembler -------------------------------------------------------------
    def asm(self, src_file, org, defines=None, max_size=None):
        """Assemble asm/<src_file> (ca65 --cpu huc6280, .segment "CODE") at CPU address org.
        Returns (bytes, labels). Labels are also merged into self.labels."""
        path = src_file if os.path.isabs(src_file) else os.path.join(ASM_DIR, src_file)
        defs = dict(self.labels)
        defs.update(defines or {})
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "x.cfg")
            open(cfg, "w").write(
                f"MEMORY {{ M: start=${org:04X}, size=${0x10000 - org:X}, file=%O, fill=no; }}\n"
                "SEGMENTS { CODE: load=M, type=rw; }\n")
            obj, binf, lbl = (os.path.join(td, n) for n in ("x.o", "x.bin", "x.lbl"))
            cmd = ["ca65", "-g", "--cpu", "huc6280", "-I", ASM_DIR, "-o", obj, path]
            for k, v in defs.items():
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                    cmd += ["-D", f"{k}=${v:X}" if isinstance(v, int) else f"{k}={v}"]
            subprocess.run(cmd, check=True)
            subprocess.run(["ld65", "-C", cfg, "-o", binf, "-Ln", lbl, obj], check=True)
            data = open(binf, "rb").read()
            labels = {}
            for l in open(lbl):
                p = l.split()
                if len(p) >= 3 and p[0] == "al":
                    labels[p[2].lstrip(".")] = int(p[1], 16)
        if max_size is not None and len(data) > max_size:
            raise AssertionError(f"{src_file}: {len(data)} bytes, region holds {max_size}")
        self.labels.update(labels)
        return data, labels

    def asm_region(self, src_file, region, defines=None):
        """Assemble into a claimed bank-local region and write it. Returns labels."""
        bank, a, z = self.claim(region)
        data, labels = self.asm(src_file, a, defines, max_size=z - a + 1)
        self.write(off(bank, a), data)
        self.log(f"{src_file} -> {region} b{bank:02X}:${a:04X}, {len(data)}/{z - a + 1} bytes")
        return labels


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1].split(",")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    b = Build()
    out_dir = args[args.index("--out") + 1] if "--out" in args else OUT_DIR
    b.out_dir = out_dir                        # modules may write proofs/reports under b.out_dir
    for name in MODULES:
        if only and name not in only:
            continue
        try:
            mod = importlib.import_module(f"mod_{name}")
        except ModuleNotFoundError:
            b.log(f"module mod_{name}.py not present yet, skipped")
            continue
        b.module = name
        mod.apply(b)
        b.module = None
    for bank in range(8):                      # insurance copy (docs/design.md)
        b.rom[(0x40 + bank) * BANK:(0x41 + bank) * BANK] = b.rom[bank * BANK:(bank + 1) * BANK]
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "susanoo-en.pce")
    open(out, "wb").write(b.rom)
    rep = [f"source  {SRC} sha1 {SRC_SHA1}",
           f"output  {out} crc32 {zlib.crc32(b.rom):08X} sha1 {hashlib.sha1(b.rom).hexdigest()}"]
    if "--no-bps" not in args:
        import bps
        patch = bps.create(b.src, bytes(b.rom))
        assert bps.apply(b.src, patch) == bytes(b.rom)
        open(os.path.join(out_dir, "susanoo-en.bps"), "wb").write(patch)
        rep.append(f"patch   build/susanoo-en.bps {len(patch)} bytes (round-trip verified)")
    rep += [""] + b.lines + ([""] + ["ERRORS:"] + b.errors if b.errors else [])
    open(os.path.join(out_dir, "report.txt"), "w").write("\n".join(rep) + "\n")
    print("\n".join(rep[:3]))
    if b.errors:
        sys.exit(f"{len(b.errors)} error(s); see {out_dir}/report.txt")


if __name__ == "__main__":
    main()
