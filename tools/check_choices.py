#!/usr/bin/env python3
"""Choice boxes must fit their window.

Some events print a line and then a question with choices in the same window. If the English needs more lines than the
window has, the window scrolls and the choice cursor lands on the wrong rows (hermit 1C:064/065, ship 1C:054/055).
A pair counts as sharing a window when, in the Japanese, the previous string's last page plus the choice string fit the
window. Usage: check_choices.py <build out dir>, or check(pages_path) from the build.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script as S  # noqa: E402

# Pairs seen working in play (the window is cleared between them): not checked.
OK_IN_PLAY = {"1C:016"}  # castle voice 1C:015 + 1C:016


def en_pages(path):
    en, H, cur = {}, {}, None
    for l in open(path, encoding="utf-8"):
        m = re.match(r"^(\S\S:\d{3}) \[\S+ \S+ x(\d+)\]", l)
        if m:
            cur = m.group(1); en[cur] = [[]]; H[cur] = int(m.group(2)); continue
        if cur is None:
            continue
        if l.strip() == "--- end":
            cur = None
        elif l.strip().startswith("--- "):
            en[cur].append([])
        elif re.match(r"^\s*\d+\|", l):
            en[cur][-1].append(l)
    return en, H


def clean_jp(s):
    s = s.replace("{ [0C]$}", "» ").replace("%", "")
    s = re.sub(r"\{(.*?)\}", r"\1", s)
    s = re.sub(r"\[1[34]\](\[[0-9A-F]{2}\]|.)", "", s)
    s = s.replace("[0D]", " / ").replace("[0B]", " ▼ ").replace("[0C]", "▸")
    s = re.sub(r"\[[0-9A-F]{2}\]", "", s)
    s = s.replace("[", "{ATK}").replace("]", "{TGT}").replace("^", "{N}").replace("_", "{N}")
    s = s.replace("*", "")
    return re.sub(r"\s+", " ", s).strip(" /")


def jp_pages():
    """{id: pages of lines} of the Japanese script, read from the original ROM."""
    B = S.all_blocks(S.load())
    jp = {}
    for b in sorted(B):
        for i, t in enumerate(B[b]):
            t = clean_jp(S.render(t, names=B[0x19]))
            jp[f"{b:02X}:{i:03d}"] = [[x for x in p.split(" / ") if x.strip()] for p in t.split("▼")]
    return jp


def check(pages_path):
    en, H = en_pages(pages_path)
    jp = jp_pages()
    ids, bad = list(jp), []
    for i, c in enumerate(ids):
        if c not in en or c in OK_IN_PLAY or "»" not in "".join(sum(jp[c], [])):
            continue
        n = len(en[c][-1])
        if n > H[c]:
            bad.append(f"{c}: question and choices need {n} lines, window has {H[c]}")
        p = ids[i - 1] if i else None
        if len(en[c]) == 1 and len(jp[c]) == 1 and p and p[:2] == c[:2] and p in en:
            if len(jp[p][-1]) + len(jp[c][0]) <= H[c] < len(en[p][-1]) + n:
                bad.append(f"{c}: shares the window with {p}, needs {len(en[p][-1]) + n} lines, window has {H[c]}")
    return bad


if __name__ == "__main__":
    bad = check(os.path.join(sys.argv[1], "text-pages.txt"))
    print("\n".join(bad) or "all choice boxes fit")
    sys.exit(1 if bad else 0)
