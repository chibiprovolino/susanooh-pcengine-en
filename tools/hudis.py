#!/usr/bin/env python3
"""HuC6280 disassembler.  dis.py ROM FILE_OFFSET CPU_ADDR [COUNT]"""
import sys

M = {}
def op(code, mn, mode): M[code] = (mn, mode)
# modes: imp imm zp zpx zpy zpi(ind) izx izy abs abx aby ind iax rel zrel(bbr) tst(imm,zp..) blk
tbl = """
00 brk imp;01 ora izx;02 sxy imp;03 st0 imm;04 tsb zp;05 ora zp;06 asl zp;07 rmb0 zp;08 php imp;09 ora imm;0a asl imp;0c tsb abs;0d ora abs;0e asl abs;0f bbr0 zrel
10 bpl rel;11 ora izy;12 ora zpi;13 st1 imm;14 trb zp;15 ora zpx;16 asl zpx;17 rmb1 zp;18 clc imp;19 ora aby;1a inc imp;1c trb abs;1d ora abx;1e asl abx;1f bbr1 zrel
20 jsr abs;21 and izx;22 sax imp;23 st2 imm;24 bit zp;25 and zp;26 rol zp;27 rmb2 zp;28 plp imp;29 and imm;2a rol imp;2c bit abs;2d and abs;2e rol abs;2f bbr2 zrel
30 bmi rel;31 and izy;32 and zpi;34 bit zpx;35 and zpx;36 rol zpx;37 rmb3 zp;38 sec imp;39 and aby;3a dec imp;3c bit abx;3d and abx;3e rol abx;3f bbr3 zrel
40 rti imp;41 eor izx;42 say imp;43 tma imm;44 bsr rel;45 eor zp;46 lsr zp;47 rmb4 zp;48 pha imp;49 eor imm;4a lsr imp;4c jmp abs;4d eor abs;4e lsr abs;4f bbr4 zrel
50 bvc rel;51 eor izy;52 eor zpi;53 tam imm;54 csl imp;55 eor zpx;56 lsr zpx;57 rmb5 zp;58 cli imp;59 eor aby;5a phy imp;5d eor abx;5e lsr abx;5f bbr5 zrel
60 rts imp;61 adc izx;62 cla imp;64 stz zp;65 adc zp;66 ror zp;67 rmb6 zp;68 pla imp;69 adc imm;6a ror imp;6c jmp ind;6d adc abs;6e ror abs;6f bbr6 zrel
70 bvs rel;71 adc izy;72 adc zpi;73 tii blk;74 stz zpx;75 adc zpx;76 ror zpx;77 rmb7 zp;78 sei imp;79 adc aby;7a ply imp;7c jmp iax;7d adc abx;7e ror abx;7f bbr7 zrel
80 bra rel;81 sta izx;82 clx imp;83 tst tzp;84 sty zp;85 sta zp;86 stx zp;87 smb0 zp;88 dey imp;89 bit imm;8a txa imp;8c sty abs;8d sta abs;8e stx abs;8f bbs0 zrel
90 bcc rel;91 sta izy;92 sta zpi;93 tst tabs;94 sty zpx;95 sta zpx;96 stx zpy;97 smb1 zp;98 tya imp;99 sta aby;9a txs imp;9c stz abs;9d sta abx;9e stz abx;9f bbs1 zrel
a0 ldy imm;a1 lda izx;a2 ldx imm;a3 tst tzpx;a4 ldy zp;a5 lda zp;a6 ldx zp;a7 smb2 zp;a8 tay imp;a9 lda imm;aa tax imp;ac ldy abs;ad lda abs;ae ldx abs;af bbs2 zrel
b0 bcs rel;b1 lda izy;b2 lda zpi;b3 tst tabx;b4 ldy zpx;b5 lda zpx;b6 ldx zpy;b7 smb3 zp;b8 clv imp;b9 lda aby;ba tsx imp;bc ldy abx;bd lda abx;be ldx aby;bf bbs3 zrel
c0 cpy imm;c1 cmp izx;c2 cly imp;c3 tdd blk;c4 cpy zp;c5 cmp zp;c6 dec zp;c7 smb4 zp;c8 iny imp;c9 cmp imm;ca dex imp;cc cpy abs;cd cmp abs;ce dec abs;cf bbs4 zrel
d0 bne rel;d1 cmp izy;d2 cmp zpi;d3 tin blk;d4 csh imp;d5 cmp zpx;d6 dec zpx;d7 smb5 zp;d8 cld imp;d9 cmp aby;da phx imp;dd cmp abx;de dec abx;df bbs5 zrel
e0 cpx imm;e1 sbc izx;e3 tia blk;e4 cpx zp;e5 sbc zp;e6 inc zp;e7 smb6 zp;e8 inx imp;e9 sbc imm;ea nop imp;ec cpx abs;ed sbc abs;ee inc abs;ef bbs6 zrel
f0 beq rel;f1 sbc izy;f2 sbc zpi;f3 tai blk;f4 set imp;f5 sbc zpx;f6 inc zpx;f7 smb7 zp;f8 sed imp;f9 sbc aby;fa plx imp;fd sbc abx;fe inc abx;ff bbs7 zrel
"""
for line in tbl.strip().splitlines():
    for ent in line.split(";"):
        c, mn, md = ent.split()
        op(int(c, 16), mn, md)
SIZE = {"imp": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "zpi": 2, "izx": 2, "izy": 2,
        "abs": 3, "abx": 3, "aby": 3, "ind": 3, "iax": 3, "rel": 2, "zrel": 3,
        "tzp": 3, "tzpx": 3, "tabs": 4, "tabx": 4, "blk": 7}


def dis1(b, pc):
    c = b[0]
    if c not in M:
        return 1, f".db ${c:02X}"
    mn, md = M[c]
    n = SIZE[md]
    a = b[1] if n > 1 else 0
    w = b[1] | (b[2] << 8) if n > 2 else 0
    f = {"imp": "", "imm": f"#${a:02X}", "zp": f"${a:02X}", "zpx": f"${a:02X},x",
         "zpy": f"${a:02X},y", "zpi": f"(${a:02X})", "izx": f"(${a:02X},x)",
         "izy": f"(${a:02X}),y", "abs": f"${w:04X}", "abx": f"${w:04X},x",
         "aby": f"${w:04X},y", "ind": f"(${w:04X})", "iax": f"(${w:04X},x)",
         "rel": f"${(pc + 2 + (a - 256 if a > 127 else a)) & 0xFFFF:04X}",
         "zrel": f"${a:02X},${(pc + 3 + (b[2] - 256 if b[2] > 127 else b[2])) & 0xFFFF:04X}",
         "tzp": f"#${a:02X},${b[2]:02X}", "tzpx": f"#${a:02X},${b[2]:02X},x",
         "tabs": f"#${a:02X},${b[2] | b[3] << 8:04X}", "tabx": f"#${a:02X},${b[2] | b[3] << 8:04X},x",
         "blk": f"${w:04X},${b[3] | b[4] << 8:04X},${b[5] | b[6] << 8:04X}"}[md]
    return n, f"{mn} {f}".strip()


def disasm(rom, off, pc, count):
    out = []
    for _ in range(count):
        n, s = dis1(rom[off:off + 7], pc)
        out.append(f"{pc:04X}  {rom[off:off + n].hex(' '):20s} {s}")
        off += n; pc += n
    return "\n".join(out)


if __name__ == "__main__":
    rom = open(sys.argv[1], "rb").read()
    print(disasm(rom, int(sys.argv[2], 16), int(sys.argv[3], 16),
                 int(sys.argv[4]) if len(sys.argv) > 4 else 40))
