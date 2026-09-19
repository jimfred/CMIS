# CMIS 5.3 Parameter Reference tools

Rebuild the Memory Map sheet from the spec PDF (run from this folder):

    python3 extract_memory_map.py ../OIF-CMIS-05.3.pdf data/pdf_memory_map_raw.json   # ~40 s, pdfplumber grid tables
    python3 normalize_memory_map.py data/pdf_memory_map_raw.json data/memory_map.json
    python3 rebuild_memory_map.py ../CMIS_5.3_Parameter_Reference.xlsx      # compares against the current version
    python3 extract_cdb_commands.py ../OIF-CMIS-05.3.pdf data/cdb_commands.json      # CDB command list
    python3 sonic_extract.py            # optional: refresh SONiC field map (pinned commit)
    python3 update_param_reference.py ../CMIS_5.3_Parameter_Reference.xlsx

Hand corrections: data/corrections.csv, keyed by extracted location (page, byte, mask, condition)
with an expected-name guard; actions set / add / delete. Column meanings are in corrections.py.
rebuild_memory_map.py writes ../Memory_Map_Rebuild_Changes.xlsx: changes vs the previous version and a
corrections log (a correction whose expected name no longer matches is reported "stale", not applied).
