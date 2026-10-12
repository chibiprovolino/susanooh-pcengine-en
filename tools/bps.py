#!/usr/bin/env python3
"""Minimal BPS patch creator/applier (spec: byuu/beat). Pure Python, no deps.

  bps.py create SOURCE TARGET PATCH
  bps.py apply  SOURCE PATCH OUTPUT
"""
import sys, zlib

SOURCE_READ, TARGET_READ, SOURCE_COPY, TARGET_COPY = range(4)


def enc_num(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return out
        out.append(x)
        n -= 1


def dec_num(buf, pos):
    data, shift = 0, 1
    while True:
        x = buf[pos]; pos += 1
        data += (x & 0x7F) * shift
        if x & 0x80:
            return data, pos
        shift <<= 7
        data += shift


def enc_signed(n):
    return enc_num((abs(n) << 1) | (1 if n < 0 else 0))


def create(src, tgt, meta=b""):
    out = bytearray(b"BPS1")
    out += enc_num(len(src)) + enc_num(len(tgt)) + enc_num(len(meta)) + meta
    # index source by 4-byte keys for SourceCopy of moved data
    MINLEN = 4
    index = {}
    for i in range(len(src) - MINLEN + 1):
        index.setdefault(src[i:i + MINLEN], []).append(i)
    pos, pending, src_rel = 0, 0, 0

    def flush():
        nonlocal pending
        if pending:
            out.extend(enc_num(((pending - 1) << 2) | TARGET_READ))
            out.extend(tgt[pos - pending:pos])
            pending = 0

    while pos < len(tgt):
        # SourceRead: same offset match
        n = 0
        while pos + n < len(tgt) and pos + n < len(src) and src[pos + n] == tgt[pos + n]:
            n += 1
        best_len, best_off = 0, 0
        key = tgt[pos:pos + MINLEN]
        if len(key) == MINLEN and n < 16:
            for cand in index.get(key, [])[:64]:
                m = 0
                while pos + m < len(tgt) and cand + m < len(src) and src[cand + m] == tgt[pos + m]:
                    m += 1
                if m > best_len:
                    best_len, best_off = m, cand
        if n >= MINLEN and n >= best_len:
            flush()
            out.extend(enc_num(((n - 1) << 2) | SOURCE_READ))
            pos += n
        elif best_len >= 8:
            flush()
            out.extend(enc_num(((best_len - 1) << 2) | SOURCE_COPY))
            out.extend(enc_signed(best_off - src_rel))
            src_rel = best_off + best_len
            pos += best_len
        else:
            pending += 1
            pos += 1
    flush()
    out += zlib.crc32(src).to_bytes(4, "little")
    out += zlib.crc32(tgt).to_bytes(4, "little")
    out += zlib.crc32(out).to_bytes(4, "little")
    return bytes(out)


def apply(src, patch):
    if patch[:4] != b"BPS1":
        raise ValueError("not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise ValueError("patch checksum mismatch")
    p = 4
    ssize, p = dec_num(patch, p)
    tsize, p = dec_num(patch, p)
    msize, p = dec_num(patch, p)
    p += msize
    if len(src) != ssize or zlib.crc32(src) != int.from_bytes(patch[-12:-8], "little"):
        raise ValueError("source file does not match the patch (wrong ROM / header?)")
    tgt = bytearray(tsize)
    o = s_rel = t_rel = 0
    end = len(patch) - 12
    while p < end:
        d, p = dec_num(patch, p)
        cmd, ln = d & 3, (d >> 2) + 1
        if cmd == SOURCE_READ:
            tgt[o:o + ln] = src[o:o + ln]; o += ln
        elif cmd == TARGET_READ:
            tgt[o:o + ln] = patch[p:p + ln]; p += ln; o += ln
        else:
            v, p = dec_num(patch, p)
            v = -(v >> 1) if v & 1 else v >> 1
            if cmd == SOURCE_COPY:
                s_rel += v
                tgt[o:o + ln] = src[s_rel:s_rel + ln]; s_rel += ln; o += ln
            else:
                t_rel += v
                for _ in range(ln):
                    tgt[o] = tgt[t_rel]; o += 1; t_rel += 1
    if zlib.crc32(tgt) != int.from_bytes(patch[-8:-4], "little"):
        raise ValueError("output checksum mismatch")
    return bytes(tgt)


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] not in ("create", "apply"):
        sys.exit(__doc__)
    a, b = open(sys.argv[2], "rb").read(), open(sys.argv[3], "rb").read()
    res = create(a, b) if sys.argv[1] == "create" else apply(a, b)
    open(sys.argv[4], "wb").write(res)
    print(f"wrote {sys.argv[4]} ({len(res)} bytes)")
