"""
Split a large ContentVersion JSON file into fixed-size chunk files.

Looks for --input (default: contentversions.json) in the given directory,
and splits its records into groups of --chunk-size (default: 500).

Output naming:
    contentversions.json     (records 1-500)
    contentversions_1.json   (records 501-1000)
    contentversions_2.json   (records 1001-1500)
    ...

The original input file is backed up as <name>.full.json.bak before being
overwritten with just its first chunk.

Usage:
    python split_contentversions.py
    python split_contentversions.py --input contentversions.json --chunk-size 500
"""

import argparse
import json
import os
import shutil


def split_records(records: list, chunk_size: int) -> list:
    return [records[i : i + chunk_size] for i in range(0, len(records), chunk_size)]


def chunk_filename(base: str, index: int) -> str:
    if index == 0:
        return base
    name, ext = os.path.splitext(base)
    return f"{name}_{index}{ext}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", default=".", help="Directory to look in and write chunks to"
    )
    parser.add_argument(
        "--input", default="contentversions.json", help="Input JSON file name"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=500, help="Records per output file"
    )
    args = parser.parse_args()

    input_path = os.path.join(args.dir, args.input)
    if not os.path.exists(input_path):
        raise SystemExit(f"Input file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise SystemExit(f"Expected a JSON array of records in {input_path}")

    print(f"Loaded {len(records)} records from {input_path}")

    chunks = split_records(records, args.chunk_size)
    if not chunks:
        print("Nothing to split (0 records).")
        return

    backup_path = input_path + ".full.json.bak"
    shutil.copyfile(input_path, backup_path)
    print(f"Backed up original file to {backup_path}")

    for i, chunk in enumerate(chunks):
        out_name = chunk_filename(args.input, i)
        out_path = os.path.join(args.dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, indent=2)
        print(f"Wrote {len(chunk)} records to {out_path}")

    print(f"Done: {len(chunks)} files written.")


if __name__ == "__main__":
    main()
