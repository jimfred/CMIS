#!/usr/bin/env python3
"""Extract the CMIS field map implemented by SONiC (sonic-platform-common) as JSON.

Clones sonic-platform-common at a pinned commit, instantiates SONiC's own
CmisMemMap / CCmisMemMap objects (bank 0) and walks every field, recording
page, byte, size and bit mask.  Output feeds the "SONiC Cross-check" column.

Usage:
    python3 sonic_extract.py [--sha SHA] [--cache DIR] [--out data/sonic_cmis_fields.json]
"""
import argparse, json, os, re, subprocess, sys, types

REPO = "https://github.com/sonic-net/sonic-platform-common.git"
DEFAULT_SHA = "2f4aeafe1e42b0e6a6d1307c2132ab677739c910"  # master, 2026-09-18


def stub_sonic_py_common():
    """SONiC imports sonic_py_common (only available on a SONiC switch); stub it."""
    class _Log:
        def __init__(self, *a, **k): pass
        def __getattr__(self, n): return lambda *a, **k: None
    m = types.ModuleType("sonic_py_common")
    s = types.ModuleType("sonic_py_common.syslogger"); s.SysLogger = _Log
    l = types.ModuleType("sonic_py_common.logger"); l.Logger = _Log
    m.syslogger, m.logger = s, l
    sys.modules.update({"sonic_py_common": m, "sonic_py_common.syslogger": s,
                        "sonic_py_common.logger": l})


def checkout(sha, cache):
    repo = os.path.join(cache, "sonic-platform-common")
    if not os.path.isdir(os.path.join(repo, ".git")):
        os.makedirs(cache, exist_ok=True)
        subprocess.run(["git", "clone", "-q", REPO, repo], check=True)
    subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], check=False)
    subprocess.run(["git", "-C", repo, "checkout", "-q", sha], check=True)
    return repo


def linear_to_page_byte(off):
    """Invert CmisPage.linear_offset for bank 0: lower memory -> (None, byte)."""
    if off < 128:
        return None, off
    page = (off - 128) // 128
    return page % 256, off - page * 128


def extract(repo):
    sys.path.insert(0, repo)
    stub_sonic_py_common()
    from sonic_platform_base.sonic_xcvr.fields.xcvr_field import (
        RegGroupField, RegField, RegBitField, RegBitsField)
    from sonic_platform_base.sonic_xcvr.mem_maps.public.cmis.cmis import CmisMemMap
    from sonic_platform_base.sonic_xcvr.codes.public.cmis import CmisCodes
    maps = [CmisMemMap(CmisCodes)]
    try:
        from sonic_platform_base.sonic_xcvr.mem_maps.public.cmis.c_cmis import CCmisMemMap
        maps.append(CCmisMemMap(CmisCodes))
    except Exception as e:  # optional coherent-CMIS map
        print("CCmisMemMap unavailable:", e, file=sys.stderr)

    out = {}

    def add(name, first_byte_linear, bits):
        """bits: list of (byte_delta, bit) relative to first_byte_linear."""
        page, byte = linear_to_page_byte(first_byte_linear)
        cells = sorted({(byte + d, b) for d, b in bits})
        out[(name, page, byte)] = {"name": name, "page": page, "bits": cells}

    def walk(f):
        if isinstance(f, RegGroupField):
            for c in f.fields:
                walk(c)
        elif isinstance(f, RegField):
            subs = list(getattr(f, "fields", []))
            generic = [s for s in subs if re.fullmatch(r"Bit\d+", s.name)]
            named = [s for s in subs if s not in generic]
            if generic:
                add(f.name, f.offset, [(s.bitpos // 8, s.bitpos % 8) for s in generic])
            elif not subs:
                add(f.name, f.offset, [(d, b) for d in range(f.size) for b in range(8)])
            for s in named:
                if isinstance(s, RegBitField):
                    add(s.name, f.offset, [(s.bitpos // 8, s.bitpos % 8)])
                elif isinstance(s, RegBitsField):
                    add(s.name, f.offset, [(s.bitpos // 8, s.bitpos % 8 + i) for i in range(s.size)])

    for mm in maps:
        for v in vars(mm).values():
            if isinstance(v, (RegGroupField, RegField)):
                walk(v)
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=DEFAULT_SHA)
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/cmis_tools"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "data", "sonic_cmis_fields.json"))
    a = ap.parse_args()
    repo = checkout(a.sha, a.cache)
    fields = extract(repo)
    json.dump({"repo": REPO, "sha": a.sha, "bank": 0, "fields": fields}, open(a.out, "w"), indent=1)
    print(f"{len(fields)} SONiC fields -> {a.out}")


if __name__ == "__main__":
    main()
