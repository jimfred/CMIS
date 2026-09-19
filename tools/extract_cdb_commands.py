#!/usr/bin/env python3
"""Extract the CDB command list (OIF-CMIS-05.3 Section 9) into data/cdb_commands.json.

Sources, all read from the PDF table grid / text:
  * Table 9-1  command groups (ID ranges)          -> Group, group requirement
  * Section 9 overview tables (header 'ID | Command Title | Description | Type | Section')
                                                    -> one row per defined command ID
  * detail table titles 'Table 9-n CDB Command XXXXh: ...' -> Detail Table
  * section headings '9.x.y CMD XXXXh: ...'          -> Section, when the overview leaves it blank
Commands that have a detail table but are missing from every overview table are added and flagged.
Reserved IDs are not listed.

Usage: python3 extract_cdb_commands.py ../OIF-CMIS-05.3.pdf data/cdb_commands.json
"""
import json, re, sys
import pdfplumber

FIRST, LAST = 285, 352


def clean(v):
    return re.sub(r"\s+", " ", v or "").strip()


def ids_of(txt):
    """'0210h/0211h' or '0216/0217h' -> ['0210h','0211h']"""
    parts = re.findall(r"([0-9A-F]{4})h?", txt.upper())
    return [p + "h" for p in parts]


def main(pdf_path, out):
    pdf = pdfplumber.open(pdf_path)
    groups, cmds, detail, sections = [], {}, {}, {}
    cur_title = None
    for pno in range(FIRST, min(LAST, len(pdf.pages))):
        page = pdf.pages[pno].filter(lambda o: o.get("object_type") != "char" or o.get("size", 10) >= 8)
        text = page.extract_text() or ""
        for m in re.finditer(r"Table (9-\d+) CDB Command ([0-9A-Fh/]+):\s*([^\n]+)", text):
            for i in ids_of(m.group(2)):
                detail.setdefault(i, m.group(1))
        for m in re.finditer(r"^\s*(?:\d+\s+)?(9\.\d+\.\d+)\s+CMD\s+([0-9A-Fh/]+)", text, re.M):
            for i in ids_of(m.group(2)):
                sections.setdefault(i, m.group(1))
        titles = [(m["top"], m["text"]) for m in page.search(r"Table 9-\d+ [^\n]*")]
        for tb in page.find_tables():
            rows = tb.extract()
            if not rows or not rows[0]:
                continue
            above = [t for y, t in titles if y < tb.bbox[1]]
            if above:
                cur_title = re.match(r"Table (9-\d+)", above[-1]).group(1)
            h0 = clean(rows[0][0])
            if h0 == "CMD IDs":                       # Table 9-1
                for r in rows[2:]:
                    if re.fullmatch(r"[0-9A-F]{4}h", clean(r[0])) and clean(r[2]) not in ("", "-"):
                        groups.append({"from": int(clean(r[0])[:4], 16), "to": int(clean(r[1])[:4], 16),
                                       "group": clean(r[2]), "req": clean(r[4]).rstrip(".")})
            elif h0 == "ID":                          # overview tables
                for r in rows[1:]:
                    cid, title = clean(r[0]), clean(r[1])
                    if not re.fullmatch(r"[0-9A-F]{4}h", cid) or title in ("", "-"):
                        continue                      # reserved IDs and ranges
                    cmds[cid] = {"cmd_id": cid, "title": title, "description": clean(r[2]),
                                 "requirement": clean(r[3]).rstrip(".") or None,
                                 "section": clean(r[4]) or None, "overview_table": cur_title, "note": None}
    for cid, t in detail.items():
        if cid not in cmds:
            cmds[cid] = {"cmd_id": cid, "title": None, "description": "", "requirement": None,
                         "section": sections.get(cid), "overview_table": None,
                         "note": "Has a detail table but is not listed in any overview table (overview marks its ID range reserved)"}
    for cid, c in cmds.items():
        n = int(cid[:4], 16)
        g = next((g for g in groups if g["from"] <= n <= g["to"]), None)
        c["group"] = g["group"] if g else None
        c["detail_table"] = detail.get(cid)
        if not c["section"]:
            c["section"] = sections.get(cid)
    # titles for commands only found via detail tables
    for pno in range(FIRST, min(LAST, len(pdf.pages))):
        text = pdf.pages[pno].extract_text() or ""
        for m in re.finditer(r"Table (9-\d+) CDB Command ([0-9A-Fh/]+):\s*([^\n]+)", text):
            for i in ids_of(m.group(2)):
                if cmds[i]["title"] is None:
                    cmds[i]["title"] = clean(m.group(3))
    out_rows = sorted(cmds.values(), key=lambda c: int(c["cmd_id"][:4], 16))
    json.dump({"commands": out_rows, "groups": groups}, open(out, "w"), indent=1)
    print(len(out_rows), "commands ->", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
