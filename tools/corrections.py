"""Apply data/corrections.csv to normalized Memory Map records.

One row per correction, keyed by LOCATION as extracted from the PDF (Key IDs are derived and can
change). Columns:
  page          2-digit hex page ('Lwr' = Lower Memory)
  byte          first byte (decimal) as extracted
  mask          0x mask(s) as in the sheet's Mask Bytes; blank = whole byte(s)
  condition     e.g. DiagnosticsSelector=01h; blank = none
  expected_name CMIS Name expected at that location. Guard: if the extraction has a different
                name there, the correction is NOT applied and is reported as stale.
                For 'add', the name of the new row.
  action        set | add | delete
  field         sheet column name(s) to set, '|' separated (set/add): CMIS Name, Byte, Byte Length,
                Mask Bytes, Access, Behavior, Requirement, Value Type, Condition, Description,
                Bank Scope, Reference Table
  new_value     value(s), '|' separated, same order as field
  reason, source, confirmed_by   free text (who confirmed it and how)
"""
import csv

FIELD = {"CMIS Name": "name", "Byte": "byte", "Byte Length": "len", "Mask Bytes": "masks",
         "Access": "access", "Behavior": "behavior", "Requirement": "requirement",
         "Value Type": "value_type", "Condition": "condition", "Description": "desc",
         "Bank Scope": "bank", "Reference Table": "table"}


def _masks(text, n):
    return [int(m, 16) for m in text.split()] if text and text.strip() else [0xFF] * n


def _setv(rec, col, val):
    key = FIELD[col]
    if key in ("byte", "len"):
        rec[key] = int(val)
    elif key == "masks":
        rec[key] = _masks(val, rec["len"])
    else:
        rec[key] = val or None


def apply(recs, path):
    """Returns (records, log). log rows: (status, correction dict, detail)."""
    rows = list(csv.DictReader(open(path, newline="")))
    log = []
    for c in rows:
        page, byte = c["page"].strip(), int(c["byte"])
        cond = c["condition"].strip() or None
        fields = [f.strip() for f in c["field"].split("|")] if c["field"].strip() else []
        vals = c["new_value"].split("|") if fields else []
        if c["action"] == "add":
            rec = {"table": c["source"], "title": "", "pdf_page": None, "page": page, "byte": byte, "len": 1,
                   "masks": [0xFF], "name": c["expected_name"], "access": None, "behavior": None,
                   "requirement": None, "condition": cond, "desc": "", "value_type": None, "bank": None}
            for f, v in zip(fields, vals):
                _setv(rec, f, v)
            rec["masks"] = _masks(c["mask"], rec["len"]) if "Mask Bytes" not in fields else rec["masks"]
            recs.append(rec)
            log.append(("applied", c, "added"))
            continue
        hits = [r for r in recs if r["page"] == page and r["byte"] == byte and (r["condition"] or None) == cond
                and r["masks"] == _masks(c["mask"], r["len"])]
        named = [r for r in hits if r["name"] == c["expected_name"]]
        if not named:
            found = ", ".join(sorted({r["name"] for r in hits})) or "nothing"
            log.append(("stale: not applied", c, f"expected {c['expected_name']}, extraction has {found}"))
            continue
        for r in named:
            if c["action"] == "delete":
                recs.remove(r)
            else:
                for f, v in zip(fields, vals):
                    _setv(r, f, v)
                if len(r["masks"]) != r["len"]:   # length changed without an explicit mask
                    r["masks"] = [0xFF] * r["len"] if set(r["masks"]) == {0xFF} else (r["masks"] + [0xFF] * r["len"])[:r["len"]]
        log.append(("applied", c, c["action"]))
    return recs, log
