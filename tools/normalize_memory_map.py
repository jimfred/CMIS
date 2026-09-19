#!/usr/bin/env python3
"""Normalize raw PDF rows (extract_memory_map.py) into canonical Memory Map records.

Usage: python3 normalize_memory_map.py data/pdf_memory_map_raw.json data/memory_map.json
"""
import json, re, sys
import conversions

# Tables that describe templates / relative structures or page ranges rather than fixed
# addresses. Kept out of the canonical map (same scope as the legacy sheet).
OUT_OF_SCOPE = {
    "8-22": "Application Descriptor format template (instances are listed in Tables 8-23/8-24/8-47)",
    "8-163": "NAD structure template (offsets relative to each NAD)",
    "8-169": "VDM instance descriptor format template",
    "8-173": "VDM TC flag byte format template",
    "8-168": "VDM configuration, page range 20h-23h (per-instance descriptors)",
    "8-171": "VDM real-time values, page range 24h-27h",
    "8-172": "VDM thresholds, page range 28h-2Bh",
    "8-180": "CDB message body, generic LPL",
    "8-181": "EPL segments, page range A0h-AFh",
}
TYPE_TOKEN = re.compile(r"^(U8|U16|S16|U32|S32|U64|F16|S8|ASCII\[\d+\])\b", re.I)


def clean(v):
    return None if v is None else re.sub(r"[ \t]*\n[ \t]*", " ", v).strip()


def parse_type(t):
    t = re.sub(r"\s+", "", t or "")
    acc = next((a for a in ("RWW", "RW", "RO", "WO") if t.startswith(a)), None)
    beh = "ClearOnRead" if "COR" in t else "SelfClearing" if "/SC" in t or "SC" in t.split("/")[1:2] else ("Normal" if acc else None)
    req = next((r for r in ("Rqd", "Opt", "Cnd", "Adv") if r in t), None)
    return acc, beh, req


def bank_scope(page):
    if page in ("Lwr", None):
        return None
    p = int(page, 16)
    if p < 0x10:
        return None
    if p == 0x1C:
        return "Application-banked"
    if 0x9F <= p <= 0xAF:
        return "CDB-instance"
    return "Lane-banked"


def value_type(desc, width_bits, nbytes):
    m = TYPE_TOKEN.match(desc or "") or re.search(r"\b(U8|U16|S16|U32|S32|U64|F16|S8)\b", desc or "")
    if m:
        return m.group(1).lower()
    if re.search(r"\bASCII\b", desc or "") and nbytes > 1:
        return f"ascii[{nbytes}]"
    if nbytes == 1 and width_bits == 1:
        return "bool"
    if nbytes == 1 and width_bits < 8:
        return f"bitfield{width_bits}"
    if nbytes == 1:
        return "u8"
    return "unspecified"


def main(src, dst):
    raw = json.load(open(src))
    # Some tables put one field over two grid rows. Fold such tail rows (no name, no bits)
    # into the row above: byte-range tails ("152-" + "167"), Type tails ("RO/COR" + "Rqd."),
    # and description text continued on the next PDF page.
    ws = lambda v: re.sub(r"\s+", "", v or "")
    merged = []
    for r in raw:
        b, nm, bits = ws(r["byte"]), ws(r["name"]), ws(r["bits"])
        prev = merged[-1] if merged and merged[-1]["table"] == r["table"] else None
        if prev is not None and not nm and not bits and (not b or re.fullmatch(r"\d+", b)):
            pb = ws(prev["byte"])
            if b and re.fullmatch(r"\d+-", pb):
                prev["byte"] = pb + b
            if r["type"]:
                prev["type"] = ((prev["type"] or "") + " " + r["type"]).strip()
            if r["desc"]:
                prev["desc"] = ((prev["desc"] or "") + " " + r["desc"]).strip()
            continue
        merged.append(dict(r))
    raw = merged
    recs, issues = [], []
    prev = {}  # per table: last byte text, type, desc, selector
    overview = []
    for r in raw:
        t = r["table"]
        if t in OUT_OF_SCOPE:
            continue
        if r.get("overview"):
            overview.append(r)
            continue
        st = prev.setdefault(t, {"byte": None, "type": "", "desc": "", "sel": None})
        byte_txt = re.sub(r"\s+", "", r["byte"] or "")
        toks = (r["name"] or "").split()
        if len(toks) > 1 and re.fullmatch(r"[a-z]", toks[-1]):
            toks = toks[:-1]          # trailing math symbol, e.g. "ModSelWaitTimeExponent e"
        name = re.sub(r"\[\d+\]$", "", "".join(toks)) if not "".join(toks).startswith("Reserved") else "".join(toks)
        bits = re.sub(r"\s+", "", r["bits"] or "")
        desc = clean(r["desc"])
        if r.get("selector"):
            st["sel"] = clean(r["selector"])
        # continuation row (description text carried onto a new PDF page)
        if not byte_txt and not name and not bits:
            if desc and recs and recs[-1]["table"] == t:
                recs[-1]["desc"] = (recs[-1]["desc"] + " " + desc).strip()
            continue
        if byte_txt:
            st["byte"] = byte_txt
        byte_txt = st["byte"]
        # Type: None = covered by a merged cell above; '' = drawn as its own empty cell, which in
        # this PDF usually still means "same as the register above" for a named field.
        is_res = name in ("", "-") or name.lower().startswith("reserved")
        tv = clean(r["type"]) if r["type"] is not None else None
        if tv:
            st["type"] = st["last"] = tv
        elif tv == "":
            st["type"] = "" if is_res else st.get("last", "")
        else:
            st["type"] = st.get("last", "")
        if desc is not None:
            st["desc"] = desc
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", byte_txt or "")
        if not m and not name and not bits:
            continue  # section label row inside a table (e.g. "Advertisement")
        if not m:
            issues.append({"table": t, "pdf_page": r["pdf_page"], "issue": f"unparsed byte '{byte_txt}'", "name": name})
            continue
        a, e = int(m.group(1)), int(m.group(2) or m.group(1))
        n = e - a + 1
        reserved = name in ("", "-") or name.lower().startswith("reserved")
        mb = re.fullmatch(r"(\d+)(?:-(\d+))?", bits)
        hi = lo = None
        if mb:
            hi, lo = int(mb.group(1)), int(mb.group(2) or mb.group(1))
            if hi < lo:
                hi, lo = lo, hi
        if mb and hi < 8:   # same bit range in every byte of the range (per-lane arrays)
            masks = [sum(1 << i for i in range(lo, hi + 1))] * n
            width = hi - lo + 1
        else:
            masks, width = [0xFF] * n, 8 * n
            if bits and not mb and bits not in ("All", "7-43-0"):
                issues.append({"table": t, "pdf_page": r["pdf_page"], "issue": f"bits '{bits}' treated as whole bytes", "name": name})
        # a lane series whose shared description cell started on the previous PDF page comes back ''
        if (desc == "" or (desc is None and not st["desc"])) and not is_res:
            stem = re.sub(r"\d+$", "", name)
            for pr in reversed(recs[-24:]):
                if pr["table"] == t and pr["desc"] and re.sub(r"\d+$", "", pr["name"]) == stem:
                    desc = st["desc"] = pr["desc"]
                    break
        acc, beh, req = parse_type(st["type"])
        if t == "8-129" and not acc:        # diagnostics data table has no Type column; page 14h data is RO
            acc, beh = "RO", "Normal"
        rec = {"table": t, "title": r["title"], "pdf_page": r["pdf_page"],
               "page": r["page"], "byte": a, "len": n, "masks": masks,
               "name": "Reserved" if reserved else name,
               "access": acc, "behavior": beh, "requirement": None if reserved else req,
               "condition": f"DiagnosticsSelector={st['sel']}" if st["sel"] and r["page"] == "14" else None,
               "desc": desc if desc is not None else st["desc"],
               "value_type": None if reserved else value_type(desc if desc is not None else st["desc"], width, n if width < 8 or n > 1 else 1),
               "bank": bank_scope(r["page"])}
        if rec["page"] is None:
            issues.append({"table": t, "pdf_page": r["pdf_page"], "issue": "page not determined from title", "name": name})
            continue
        # per-lane arrays: Name<n>/<i> over 8 equal slots -> one record per lane
        lane = re.search(r"<[ni]>", rec["name"])
        if lane and n % 8 == 0 and n >= 8:
            w = n // 8
            for k in range(8):
                recs.append(dict(rec, name=rec["name"].replace(lane.group(0), str(k + 1)), byte=a + k * w, len=w,
                                 masks=rec["masks"][:w]))
            continue
        if lane and n == 1 and rec["masks"] == [0xFF]:
            for k in range(8):
                recs.append(dict(rec, name=rec["name"].replace(lane.group(0), str(k + 1)), masks=[1 << k],
                                 value_type="bool"))
            continue
        recs.append(rec)
    # Overview tables duplicate detail tables, except a few fields defined only there
    # (e.g. PageChecksum of pages 00h-02h). Keep overview rows whose bits no detail row covers.
    covered = {(r["page"], r["byte"] + i) for r in recs for i in range(r["len"])}
    for r in overview:
        nm = (r["name"] or "").strip()
        if nm == "Page Checksum":
            nm = "PageChecksum"
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", re.sub(r"\s+", "", r["byte"] or ""))
        if not m or not re.fullmatch(r"[A-Z][A-Za-z0-9]+", nm) or r["page"] is None:
            continue
        a, e = int(m.group(1)), int(m.group(2) or m.group(1))
        if any((r["page"], b) in covered for b in range(a, e + 1)):
            continue
        acc, beh, req = parse_type(r.get("type"))
        recs.append({"table": r["table"], "title": r["title"], "pdf_page": r["pdf_page"], "page": r["page"],
                     "byte": a, "len": e - a + 1, "masks": [0xFF] * (e - a + 1), "name": nm,
                     "access": acc or "RO", "behavior": beh or "Normal", "requirement": req, "condition": None,
                     "desc": clean(r["desc"]) or "", "value_type": None, "bank": bank_scope(r["page"])})
        issues.append({"table": r["table"], "pdf_page": r["pdf_page"], "issue": "field only in page-overview table; Access assumed RO", "name": nm})
    for r in recs:  # value type and conversion from the final (post lane-expansion) geometry
        if r["name"] != "Reserved":
            w = bin(r["masks"][0]).count("1") if r["len"] == 1 else 8 * r["len"]
            r["value_type"] = value_type(r["desc"], w, r["len"])
        r.update(conversions.derive(r["desc"], r["value_type"], r["len"], r["name"])
                 if r["name"] != "Reserved" else {"unit": None, "scale": None, "byte_order": None, "conv_note": None})
    json.dump({"records": recs, "issues": issues, "out_of_scope": OUT_OF_SCOPE}, open(dst, "w"), indent=0)
    print(f"{len(recs)} records, {len(issues)} issues -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
