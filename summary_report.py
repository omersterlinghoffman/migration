"""
Scrape an Opptly public candidate list and cross-check it against a
candidates_existence_check.csv to print a summary: total rows found on the
list, how many were duplicate OpptlyPersonId rows, and how many candidates
were successfully pushed to Salesforce ("Created" in the CSV).

Usage:
    python summary_report.py https://jobs.opptly.com/PublicLists/<list-id>
    python summary_report.py https://jobs.opptly.com/PublicLists/<list-id> --existence-csv candidates_existence_check.csv
"""

import argparse
import csv
import os
import sys
from collections import Counter

import requests

from scrape_opptly import fetch_html, parse_rows


def summarize_list(url: str) -> tuple:
    session = requests.Session()
    print(f"Fetching list page: {url}", file=sys.stderr)
    html = fetch_html(url, session)
    rows = parse_rows(html, url)

    total_rows = len(rows)
    id_counts = Counter(r["person_id"] for r in rows if r["person_id"])
    unique_ids = len(id_counts)
    duplicate_ids = sum(1 for c in id_counts.values() if c > 1)
    duplicate_rows = sum(c - 1 for c in id_counts.values() if c > 1)
    no_person_id = sum(1 for r in rows if not r["person_id"])

    return total_rows, unique_ids, duplicate_ids, duplicate_rows, no_person_id


def summarize_csv(path: str) -> Counter:
    if not os.path.exists(path):
        print(f"(no existence CSV found at {path}, skipping)", file=sys.stderr)
        return Counter()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return Counter(row.get("Exists") or "(blank)" for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Opptly PublicLists URL to scrape")
    parser.add_argument(
        "--existence-csv",
        default="candidates_existence_check.csv",
        help="candidates_existence_check.csv to summarize (default: %(default)s)",
    )
    args = parser.parse_args()

    total_rows, unique_ids, duplicate_ids, duplicate_rows, no_person_id = summarize_list(args.url)
    status_counts = summarize_csv(args.existence_csv)

    print()
    print("=== List summary ===")
    print(f"Total rows on list:              {total_rows}")
    print(f"Unique OpptlyPersonId:            {unique_ids}")
    print(f"Person ids appearing >1 time:      {duplicate_ids}")
    print(f"Duplicate rows (extra occurrences): {duplicate_rows}")
    if no_person_id:
        print(f"Rows with no person id:           {no_person_id}")

    print()
    print(f"=== CSV summary ({args.existence_csv}) ===")
    if status_counts:
        total_csv_rows = sum(status_counts.values())
        print(f"Total rows in CSV:                {total_csv_rows}")
        for status, count in status_counts.most_common():
            print(f"  {status:<20} {count}")
        created = status_counts.get("Created", 0)
        print(f"\nSuccessfully pushed (Created):     {created}")
    else:
        print("No CSV data available.")


if __name__ == "__main__":
    main()
