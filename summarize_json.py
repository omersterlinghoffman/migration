"""
Print a quick summary of a ContentVersion JSON file (e.g. contentversions.json
or a chunk file produced by split_contentversions.py / push_to_salesforce.py).

Reports: total records, how many are still pending push (have an
OpptlyPersonId) vs already finalized (pushed, fields stripped), unique
candidates, unique job titles, and the total/average resume size.

Usage:
    python summarize_json.py contentversions.json
    python summarize_json.py contentversions_1.json
"""

import argparse
import json
import sys
from collections import Counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="ContentVersion JSON file to summarize")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise SystemExit(f"Expected a JSON array of records in {args.input}")

    total = len(records)
    pending = [r for r in records if r.get("OpptlyPersonId")]
    finalized = total - len(pending)

    person_ids = Counter(r.get("OpptlyPersonId") for r in records if r.get("OpptlyPersonId"))
    job_titles = Counter(r.get("JobTitle") for r in records if r.get("JobTitle"))

    sizes = [len(r.get("VersionData") or "") for r in records]
    total_size = sum(sizes)
    avg_size = total_size / total if total else 0

    print(f"=== {args.input} ===")
    print(f"Total records:            {total}")
    print(f"Pending (not yet pushed): {len(pending)}")
    print(f"Finalized (already pushed, fields stripped): {finalized}")
    print(f"Unique OpptlyPersonId:    {len(person_ids)}")
    duplicate_ids = sum(1 for c in person_ids.values() if c > 1)
    if duplicate_ids:
        print(f"  (person ids appearing >1 time: {duplicate_ids})")
    print()
    print(f"Total resume payload (base64 chars): {total_size:,}")
    print(f"Average resume payload (base64 chars): {avg_size:,.0f}")

    if job_titles:
        print()
        print(f"Top job titles ({len(job_titles)} unique):")
        for title, count in job_titles.most_common(10):
            print(f"  {count:>5}  {title}")


if __name__ == "__main__":
    main()
