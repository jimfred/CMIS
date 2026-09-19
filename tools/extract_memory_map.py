#!/usr/bin/env python3
"""Extract CMIS Section 8 (Memory Map) field rows from OIF-CMIS-05.3.pdf.

Reads the PDF table grid with pdfplumber (not line-by-line text), so that
  * merged Type cells are recognised (cells covered by a merge come back as None
    and inherit the value above; '' means genuinely empty),
  * byte ranges that wrap in the PDF ("129-" / "130") stay whole,
  * description text never becomes a row of its own.
Superscript footnote markers (font size < 8 pt) are dropped before extraction.

Usage: python3 extract_memory_map.py ../OIF-CMIS-05.3.pdf data/pdf_memory_map.json
"""
import json, re, sys
import pdfplumber

FIRST_PDF_PAGE, LAST_PDF_PAGE = 120, 290           # Section 8 lies inside this range
TITLE = re.compile(r"Table (8-\d+)\s+(.+)")
SKIP_TABLES = {  # page-overview summaries duplicate the detail tables that follow them
    "8-4", "8-26", "8-42", "8-61", "8-64", "8-65", "8-67", "8-82", "8-98", "8-100",
    "8-125", "8-130", "8-132", "8-152", "8-155", "8-158", "8-162", "8-165", "8-177"}
HDR = {"byte": ("Byte", "Bytes", "Address"), "bits": ("Bit", "Bits"),
       "name": ("Field Name", "Register Name", "Diagnostics Field", "Subject Area or Field", "Subject Area", "Name"),
       "selector": ("Diag. Selector",),
       "desc": ("Field Description", "Register Description", "Field/Register Description", "Diagnostics Data Description", "Description"),
       "type": ("Type",)}


def page_of(title):
    if "Lower Memory" in title:
        return "Lwr"
    m = re.search(r"Pages?\s+([0-9A-F]{2})h", title) or re.search(r"Byte ([0-9A-F]{2})h:", title)
    return m.group(1) if m else None


def spans(header):
    """Map logical column -> (start, end) index span in the raw row."""
    idx = []
    for i, h in enumerate(header):
        h = re.sub(r"\s+", " ", (h or "")).replace("/ ", "/").strip()
        if not h:
            continue
        for k, names in HDR.items():
            if (any(h == n or h.startswith(n + " ") for n in names) or (k == "desc" and "Description" in h)) \
                    and k not in [x[0] for x in idx]:
                idx.append((k, i))
                break
        else:
            idx.append(("other", i))
    out = {}
    for j, (k, i) in enumerate(idx):
        end = idx[j + 1][1] if j + 1 < len(idx) else len(header)
        if k != "other":
            out[k] = (i, end)
    return out


def cell(row, sp):
    """First non-empty value in the span; None if every cell is None (merged)."""
    if sp is None:
        return ""
    vals = row[sp[0]:sp[1]]
    if all(v is None for v in vals):
        return None
    for v in vals:
        if v not in (None, ""):
            return v
    return ""


def main(pdf_path, out_path):
    pdf = pdfplumber.open(pdf_path)
    rows, cur = [], None
    for pno in range(FIRST_PDF_PAGE, LAST_PDF_PAGE):
        page = pdf.pages[pno].filter(lambda o: o.get("object_type") != "char" or o.get("size", 10) >= 8)
        titles = [(m["top"], m["text"]) for m in page.search(r"Table 8-\d+ [^\n]*")]
        for tb in page.find_tables():
            above = [t for y, t in titles if y < tb.bbox[1]]
            if above:
                m = TITLE.match(above[-1])
                cur = {"table": m.group(1), "title": m.group(2).strip(), "page": page_of(m.group(2)), "sp": None}
            if not cur:
                continue
            data = tb.extract()
            if not data or max(len(r) for r in data) < 3:
                continue  # stray fragments (e.g. a detached "RO / Rqd." box)
            sp = spans(data[0])
            if "byte" in sp and "name" in sp:
                cur["sp"], body = sp, data[1:]
            elif cur["sp"]:
                body = data                     # continuation of a table from the previous page
            else:
                continue
            sp = cur["sp"]
            for r in body:
                rec = {k: cell(r, sp.get(k)) for k in HDR}
                rec.update(table=cur["table"], title=cur["title"], page=cur["page"], pdf_page=pno + 1,
                           overview=cur["table"] in SKIP_TABLES)
                rows.append(rec)
    json.dump(rows, open(out_path, "w"), indent=0)
    print(len(rows), "raw rows ->", out_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
