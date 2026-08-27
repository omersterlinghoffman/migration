"""
Repair a contentversions.json produced by scrape_opptly.py after a
JSONDecodeError, by rebuilding it from the .ndjson scratch file.

scrape_opptly.py writes contentversions.json as one giant single-line JSON
array (records joined by commas, no newlines) assembled from
contentversions.ndjson (one JSON object per line, appended durably as the
scrape ran). If the scrape process was killed/crashed mid-write, the last
line of the .ndjson can be a truncated partial record; finalize_json_array
includes it as-is, corrupting the whole array from that point on.

This script re-validates contentversions.ndjson line by line, drops any
line that isn't valid JSON (reporting which ones), and rewrites both the
.ndjson (bad lines removed) and the .json array from the surviving records.

Usage:
    python repair_contentversions.py --input contentversions.json
    python repair_contentversions.py --ndjson contentversions.ndjson
"""

import argparse
import json
import os
import shutil


def ndjson_path_for(output_path: str) -> str:
    root, _ext = os.path.splitext(output_path)
    return root + ".ndjson"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", default="contentversions.json", help="Target JSON array file to rebuild"
    )
    parser.add_argument(
        "--ndjson",
        default=None,
        help="Path to the .ndjson scratch file (default: derived from --input)",
    )
    args = parser.parse_args()

    ndjson_path = args.ndjson or ndjson_path_for(args.input)
    if not os.path.exists(ndjson_path):
        raise SystemExit(f"ndjson scratch file not found: {ndjson_path}")

    backup_path = ndjson_path + ".bak"
    shutil.copyfile(ndjson_path, backup_path)
    print(f"Backed up {ndjson_path} to {backup_path}")

    good_lines = []
    bad_line_numbers = []
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError as exc:
                bad_line_numbers.append(i)
                print(f"  !! dropping malformed line {i}: {exc}")
                continue
            good_lines.append(stripped)

    print(f"{len(good_lines)} valid records, {len(bad_line_numbers)} malformed line(s) dropped")

    if bad_line_numbers:
        with open(ndjson_path, "w", encoding="utf-8") as f:
            for line in good_lines:
                f.write(line)
                f.write("\n")
        print(f"Rewrote {ndjson_path} with only valid records")
    else:
        print(f"{ndjson_path} had no malformed lines; leaving it unchanged")

    with open(args.input, "w", encoding="utf-8") as f:
        f.write("[")
        f.write(",".join(good_lines))
        f.write("]")
    print(f"Rebuilt {args.input} with {len(good_lines)} records")


if __name__ == "__main__":
    main()
