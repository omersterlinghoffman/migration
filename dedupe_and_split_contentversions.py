"""
Dedupe a ContentVersion JSON file (keeping each candidate's LAST resume by
OpptlyPersonId) and split it into files of 200 records.

Output naming:
    contentversions.json     (records 1-200)
    contentversions_1.json   (records 201-400)
    contentversions_2.json   (records 401-600)
    ...

The original input file is backed up as <name>.full.json.bak before being
overwritten with just its first chunk.

Usage:
    python dedupe_and_split_contentversions.py
    python dedupe_and_split_contentversions.py --input contentversions.json --chunk-size 200
    python dedupe_and_split_contentversions.py --missing-only candidates_existence_check.json
"""

import argparse
import json
import os
import shutil


def keep_last_per_person(records: list) -> list:
    last_by_person = {}
    no_person_id = []
    order = []
    for record in records:
        pid = record.get("OpptlyPersonId")
        if not pid:
            no_person_id.append(record)
            continue
        if pid not in last_by_person:
            order.append(pid)
        last_by_person[pid] = record  # later records overwrite earlier ones

    return [last_by_person[pid] for pid in order] + no_person_id


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
        "--chunk-size", type=int, default=200, help="Records per output file"
    )
    parser.add_argument(
        "--missing-only",
        metavar="EXISTENCE_CHECK_JSON",
        default=None,
        help="Path to a candidates_existence_check.json file; only keep "
        "records whose OpptlyPersonId is listed under its 'missing' key",
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

    records = keep_last_per_person(records)
    print(f"{len(records)} records after keeping last resume per OpptlyPersonId")

    if args.missing_only:
        with open(args.missing_only, "r", encoding="utf-8") as f:
            missing_ids = set(json.load(f)["missing"])
        before = len(records)
        records = [r for r in records if r.get("OpptlyPersonId") in missing_ids]
        print(
            f"--missing-only: kept {len(records)}/{before} records present in "
            f"{args.missing_only}'s 'missing' list"
        )

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
