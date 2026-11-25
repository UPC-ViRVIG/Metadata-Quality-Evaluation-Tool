"""
Convert the IANA Language Subtag Registry text file into a compact JSON file.
Usage: python build_bcp47_json.py language-subtag-registry.txt bcp47_registry.json
"""
import json

TYPES = ("language", "extlang", "script", "region", "variant")


def parse_records(text):
    for block in text.split("\n%%\n"):
        record, last = {}, None
        for line in block.splitlines():
            if line.startswith("  ") and last:            # continuation line
                record[last][-1] += " " + line.strip()
            elif ":" in line:
                last, value = line.split(":", 1)
                record.setdefault(last.strip(), []).append(value.strip())
        if record:
            yield record


def build(text):
    out = {"file_date": None,
           **{t: [] for t in TYPES},
           "ranges": {t: [] for t in TYPES},       # e.g. qaa..qtz (private use)
           "whole_tags": [],                       # grandfathered + redundant
           "deprecated": {},                       # subtag/tag -> preferred value
           "suppress_script": {}}                  # language -> default script
    for rec in parse_records(text):
        if "File-Date" in rec:
            out["file_date"] = rec["File-Date"][0]
            continue
        rtype = rec["Type"][0]
        if rtype in ("grandfathered", "redundant"):
            key = rec["Tag"][0].lower()
            out["whole_tags"].append(key)
        else:
            key = rec["Subtag"][0].lower()
            if ".." in key:
                out["ranges"][rtype].append(key.split(".."))
            else:
                out[rtype].append(key)
            if "Suppress-Script" in rec:
                out["suppress_script"][key] = rec["Suppress-Script"][0].lower()
        if "Deprecated" in rec:
            out["deprecated"][key] = rec.get("Preferred-Value", [None])[0]
    for t in TYPES:
        out[t].sort()
    return out


SOURCE_FILE = "language-subtag-registry.txt"   # input: IANA registry
OUTPUT_FILE = "bcp47_registry.json"            # output: loaded by the tool


if __name__ == "__main__":
    with open(SOURCE_FILE, encoding="utf-8") as f:
        data = build(f.read())

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {OUTPUT_FILE} (registry File-Date: {data['file_date']})")