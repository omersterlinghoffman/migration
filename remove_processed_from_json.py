"""
Remove candidates already marked "Created" (by default) in
candidates_existence_check.csv from a ContentVersion JSON array file (e.g.
contentversions_combined.json), so what's left is only the not-yet-pushed
records.

Streams the input file and parses one top-level record at a time rather
than json.load-ing the whole array, so this stays memory-safe even on very
large combined files.

Usage:
    python remove_processed_from_json.py --json contentversions_combined.json --csv candidates_existence_check.csv
    python remove_processed_from_json.py --json contentversions_combined.json --csv candidates_existence_check.csv -o contentversions_remaining.json
    python remove_processed_from_json.py --json contentversions_combined.json --csv candidates_existence_check.csv --status Created Error
"""

import argparse
import csv
import json
import os
import shutil
import sys


def load_done_ids(csv_path: str, statuses) -> set:
    wanted = set(statuses)
    done = set()
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("Person ID")
            if pid and (row.get("Exists") or "") in wanted:
                done.add(pid)
    return done


def stream_filter(input_path: str, output_path: str, done_ids: set) -> tuple:
    """Parse the input file's top-level JSON array one record at a time
    (via repeated raw_decode calls) instead of json.load-ing it whole, so
    memory use stays bounded to one record at a time rather than the full
    record list."""
    decoder = json.JSONDecoder()
    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    idx = text.index("[") + 1
    n = len(text)

    kept = 0
    dropped = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("[")
        first = True
        while True:
            while idx < n and text[idx] in " \t\r\n,":
                idx += 1
            if idx >= n or text[idx] == "]":
                break
            obj, end = decoder.raw_decode(text, idx)
            idx = end

            pid = obj.get("OpptlyPersonId")
            if pid and pid in done_ids:
                dropped += 1
                continue

            if not first:
                out.write(",")
            json.dump(obj, out, separators=(",", ":"))
            first = False
            kept += 1

        out.write("]")

    return kept, dropped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", default="contentversions_combined.json", help="ContentVersion JSON array file to filter"
    )
    parser.add_argument(
        "--csv", default="candidates_existence_check.csv", help="candidates_existence_check.csv to read"
    )
    parser.add_argument(
        "--status",
        nargs="+",
        default=["Created"],
        help="Which Exists status value(s) count as already-processed (default: Created)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output file (default: overwrite --json in place, keeping a .bak backup)",
    )
    args = parser.parse_args()

    done_ids = load_done_ids(args.csv, args.status)
    print(f"Loaded {len(done_ids)} already-processed person id(s) from {args.csv}", file=sys.stderr)

    output_path = args.output or args.json
    tmp_path = output_path + ".tmp"

    kept, dropped = stream_filter(args.json, tmp_path, done_ids)

    if output_path == args.json:
        backup_path = args.json + ".bak"
        shutil.copyfile(args.json, backup_path)
        print(f"Backed up original to {backup_path}", file=sys.stderr)

    os.replace(tmp_path, output_path)

    print(f"Kept {kept} record(s), removed {dropped} already-processed record(s)", file=sys.stderr)
    print(f"Wrote {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
