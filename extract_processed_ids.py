"""
Read candidates_existence_check.csv and write a CSV containing just the
Person ID column for rows that have already been processed (Exists ==
"Created" by default).

Usage:
    python extract_processed_ids.py candidates_existence_check.csv -o processed_person_ids.csv
    python extract_processed_ids.py candidates_existence_check.csv -o processed_person_ids.csv --status Created Error
"""

import argparse
import csv
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="candidates_existence_check.csv to read")
    parser.add_argument(
        "-o", "--output", default="processed_person_ids.csv", help="Output CSV file"
    )
    parser.add_argument(
        "--status",
        nargs="+",
        default=["Created"],
        help="Which Exists status value(s) count as 'processed' (default: Created)",
    )
    args = parser.parse_args()

    wanted = set(args.status)

    with open(args.csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        person_ids = [
            row.get("Person ID")
            for row in reader
            if (row.get("Exists") or "") in wanted and row.get("Person ID")
        ]

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Person ID"])
        for pid in person_ids:
            writer.writerow([pid])

    print(f"Wrote {len(person_ids)} processed person id(s) to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
