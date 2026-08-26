"""
Scrape an Opptly public candidate list and write a CSV of how many rows
each OpptlyPersonId appears in (before any dedup), sorted by count
descending.

Usage:
    python count_person_ids.py https://jobs.opptly.com/PublicLists/<list-id> -o person_id_counts.csv
"""

import argparse
import csv
import sys
from collections import Counter

from scrape_opptly import fetch_html, parse_rows

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Opptly PublicLists URL to scrape")
    parser.add_argument(
        "-o", "--output", default="person_id_counts.csv", help="Output CSV file"
    )
    args = parser.parse_args()

    session = requests.Session()

    print(f"Fetching list page: {args.url}", file=sys.stderr)
    html = fetch_html(args.url, session)

    rows = parse_rows(html, args.url)
    print(f"Found {len(rows)} candidate rows with resumes", file=sys.stderr)

    counts = Counter(r["person_id"] for r in rows)
    print(f"{len(counts)} unique person ids", file=sys.stderr)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["person id", "count"])
        for person_id, count in counts.most_common():
            writer.writerow([person_id, count])

    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
