"""
Combine chunked ContentVersion JSON files back into a single file.

Looks in --dir for files matching the pattern produced by
split_contentversions.py:
    contentversions.json, contentversions_1.json, contentversions_2.json, ...

and concatenates their records (in that order) into one output file.

Usage:
    python combine_contentversions.py
    python combine_contentversions.py --dir . --base contentversions.json -o contentversions_combined.json
"""

import argparse
import glob
import json
import os
import re


def find_chunks(dir_: str, base: str) -> list:
    name, ext = os.path.splitext(base)
    pattern = os.path.join(dir_, f"{name}_*{ext}")

    chunk_paths = []
    for path in glob.glob(pattern):
        match = re.fullmatch(re.escape(name) + r"_(\d+)" + re.escape(ext), os.path.basename(path))
        if match:
            chunk_paths.append((int(match.group(1)), path))
    chunk_paths.sort(key=lambda t: t[0])

    base_path = os.path.join(dir_, base)
    paths = []
    if os.path.exists(base_path):
        paths.append(base_path)
    paths.extend(p for _, p in chunk_paths)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=".", help="Directory containing the chunk files")
    parser.add_argument(
        "--base", default="contentversions.json", help="Base file name (chunk 0)"
    )
    parser.add_argument(
        "-o", "--output", default=None, help="Output file (default: overwrite --base)"
    )
    args = parser.parse_args()

    output_path = os.path.join(args.dir, args.output) if args.output else os.path.join(
        args.dir, args.base
    )

    paths = find_chunks(args.dir, args.base)
    if not paths:
        raise SystemExit(f"No chunk files found for base '{args.base}' in {args.dir}")

    combined = []
    seen_person_ids = set()
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        added = 0
        for r in records:
            pid = r.get("OpptlyPersonId")
            if pid and pid in seen_person_ids:
                continue
            if pid:
                seen_person_ids.add(pid)
            combined.append(r)
            added += 1
        print(f"{path}: {len(records)} records ({added} added, {len(records) - added} duplicate)")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print(f"Combined {len(paths)} files into {output_path} ({len(combined)} records)")


if __name__ == "__main__":
    main()
