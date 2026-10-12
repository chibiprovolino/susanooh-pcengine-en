#!/usr/bin/env python3
"""Walk the event scripts (bank 2 VM, scripts in bank $0A at $4000) and the town people table;
list which text strings can be printed (docs/unused-lines.md)."""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script  # noqa: E402
r = script.load()
L = {0x00:2,0x02:2,0x04:2,0x06:2,0x08:4,0x0A:4,0x0C:2,0x0E:2,0x10:3,0x12:2,0x14:3,0x16:2,0x18:5,0x1A:2,
     0x1C:3,0x1E:3,0x20:3,0x22:3,0x24:3,0x26:3,0x2A:6,0x2C:3,0x2E:2,0x30:1,0x32:1,0x34:1,0x36:2,0x38:2,
     0x3A:4,0x3C:1,0x3E:2,0x40:3,0x42:1,0x44:2,0x46:3,0x48:3,0x4A:5,0x4C:6,0x4E:1,0x50:2,0x52:4,0x54:4,
     0x56:5,0x58:6,0x5A:2,0x5C:3,0x5E:1,0x60:1,0x62:6,0x64:3,0x66:2,0x68:1,0x6A:3,0x6C:2,0x6E:6,0x70:6,
     0x72:5,0x74:4,0x78:2,0x7A:2,0x7C:3,0x7E:4,0x80:2,0x82:3,0x84:1,0x86:2,0x88:2,0x8A:8}
TEXT1 = {0x10, 0x3E, 0x40, 0x46, 0x80}   # string = arg1
TEXT2 = {0x52, 0x54, 0x82}               # string = arg2 (arg1 = portrait)
BASE = 0x0A * 0x2000 - 0x4000            # file = cpu + BASE

def walk(entry, prints, errs):
    todo = [(entry, None)]; seen = set()
    while todo:
        pc, blk = todo.pop()
        while True:
            if (pc, blk) in seen: break
            seen.add((pc, blk))
            if not 0x4000 <= pc < 0x6000: errs.append((entry, pc, "pc out of bank")); break
            op = r[pc + BASE]
            a = r[pc + BASE + 1:pc + BASE + 8]
            if op == 0xFF or op == 0x76 or op == 0x28: break
            if op not in L: errs.append((entry, pc, "bad op %02X" % op)); break
            if op == 0x0E: blk = a[0]
            if op in TEXT1: prints.append((blk, a[0], entry, pc))
            if op in TEXT2: prints.append((blk, a[1], entry, pc))
            tgt = a[0] | a[1] << 8
            if op == 0x20: pc = tgt; continue
            if op in (0x1C, 0x1E, 0x22, 0x24, 0x26): todo.append((tgt, blk))
            if op == 0x26: pass  # call returns to pc+3
            pc += L[op]

def events():
    lo = r[0x45F2:0x45F2 + 0xFF]; hi = r[0x46F1:0x46F1 + 0xFF]
    return [l | h << 8 for l, h in zip(lo, hi)]

def people():
    out = []
    f = 0x6E51C
    for i in range(256):
        c, b, s = r[f + 3 * i:f + 3 * i + 3]
        if (c, b, s) != (0, 0, 0):
            out += [(b, s, i), (b, s + 1, i)]
    return out

if __name__ == "__main__":
    prints, errs = [], []
    for e in sorted(set(events())):
        walk(e, prints, errs)
    print("prints", len(prints), "errors", len(errs))
    for x in errs[:30]: print("ERR entry %04X pc %04X %s" % x)
    c = collections.Counter(p[0] for p in prints)
    print({("%02X" % k if k is not None else "AREA"): v for k, v in c.items()})

def area_block(ev_index):
    """Area block an event prints from when it never sets one (b02:$C0AA picks it by story progress);
    inferred from the explicit blocks of neighbouring events."""
    i = ev_index
    if i <= 0x18 or 0x50 <= i <= 0x57 or i >= 0xF0: return 0x1C
    if i <= 0x31: return 0x1D
    if i <= 0x63: return 0x1E
    if i <= 0xA9: return 0x1F
    return 0x20

def used():
    """{block: {string: [sources]}} from town people and event scripts."""
    u = collections.defaultdict(lambda: collections.defaultdict(list))
    for b, s, i in people():
        u[b][s].append("person %02X" % i)
    ev = events()
    for i, e in enumerate(ev):
        p, er = [], []
        walk(e, p, er)
        for b, s, _, pc in p:
            u[b if b is not None else area_block(i)][s].append("event %02X @%04X" % (i, pc))
    return u
