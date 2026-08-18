"""
Sync candidates_existence_check.csv from a <base>.pushed.ndjson log.

Useful when a push_to_salesforce.py run recorded successful pushes (the
.pushed.ndjson log) but the CSV wasn't updated to match -- e.g. it was run
with a different --existence-csv path, or the CSV was reset/regenerated
afterwards.

For every OpptlyPersonId in the pushed log, the matching Person ID row(s)
in the CSV are set to:
    Exists              = Created
    Candidate_SF_Id     = <CandidateId from the log>
    Job_Submission_Exists = Created
    Error               = (cleared)

Usage:
    python sync_csv_from_pushed_log.py --pushed-log contentversions_no_resume.pushed.ndjson
    python sync_csv_from_pushed_log.py --pushed-log contentversions_no_resume.pushed.ndjson --csv candidates_existence_check.csv
"""

import argparse
import csv
import json
import sys


def load_pushed(path: str) -> dict:
    pushed = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            pid = entry.get("OpptlyPersonId")
            if pid:
                pushed[pid] = entry
    return pushed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pushed-log", required=True, help="<base>.pushed.ndjson file")
    parser.add_argument(
        "--csv", default="candidates_existence_check.csv", help="CSV file to update in place"
    )
    args = parser.parse_args()

    pushed = load_pushed(args.pushed_log)
    print(f"Loaded {len(pushed)} pushed candidate(s) from {args.pushed_log}", file=sys.stderr)

    with open(args.csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    if "Error" not in fieldnames:
        fieldnames.append("Error")
        for row in rows:
            row["Error"] = ""

    updated = 0
    for row in rows:
        entry = pushed.get(row.get("Person ID"))
        if not entry:
            continue
        row["Exists"] = "Created"
        row["Candidate_SF_Id"] = entry.get("CandidateId", row.get("Candidate_SF_Id", ""))
        row["Job_Submission_Exists"] = "Created"
        row["Error"] = ""
        updated += 1

    with open(args.csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {updated} row(s) in {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
