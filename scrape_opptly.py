"""
Scrape an Opptly public candidate list and emit ContentVersion-style JSON
payloads (one per resume), with the resume file base64-encoded into
VersionData.

Usage:
    pip install requests beautifulsoup4
    python scrape_opptly.py https://jobs.opptly.com/PublicLists/<list-id> -o contentversions.json

Each JSON record looks like:
    {
        "PersonId": "REPLACE_PERSON_ID",      # placeholder, filled in later
        "FirstPublishLocationId": null,        # not published yet
        "Title": "Chevaundae-Moore-resume",
        "PathOnClient": "Chevaundae-Moore-resume.pdf",
        "VersionData": "<base64 resume bytes>",
        "OpptlyPersonId": "9016490",           # source system id, for matching
        "FullName": "'-Vaundae' Moore, Che",
        "JobId": "179306",
        "JobTitle": "Engineering Technician"
    }
"""

import argparse
import base64
import json
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

COLUMNS = [
    "resume_link",
    "full_name",
    "person_id",
    "emails",
    "mobile_phones",
    "all_phones",
    "job_id",
    "job_title",
    "job_step",
    "last_note",
    "street",
    "city",
    "state",
    "postal_code",
    "country",
]


def fetch_html(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.text


def parse_rows(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("No <table> found on page")

    # Attachment hrefs are like "<list-id>/Attachment:<id>", relative to the
    # PublicLists/ directory (i.e. one level above the list page itself).
    base_dir = base_url.rsplit("/", 1)[0] + "/"

    rows = table.find_all("tr")
    records = []
    for tr in rows:
        cells = tr.find_all("td")
        if len(cells) < len(COLUMNS):
            continue  # skip header / malformed rows

        link = cells[0].find("a")
        if link is None or not link.get("href"):
            continue  # row without an attached resume

        resume_url = urljoin(base_dir, link["href"])
        resume_filename = link.get_text(strip=True)

        record = dict(zip(COLUMNS[1:], (c.get_text(strip=True) for c in cells[1:])))
        record["resume_url"] = resume_url
        record["resume_filename"] = resume_filename
        records.append(record)

    return records


def download_resume(url: str, session: requests.Session, cache: dict) -> bytes:
    if url in cache:
        return cache[url]
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    cache[url] = resp.content
    return resp.content


def build_contentversion(record: dict, resume_bytes: bytes) -> dict:
    filename = record["resume_filename"] or "resume"
    title = filename.rsplit(".", 1)[0] if "." in filename else filename

    return {
        "PersonId": "REPLACE_PERSON_ID",
        "FirstPublishLocationId": None,
        "Title": title,
        "PathOnClient": filename,
        "VersionData": base64.b64encode(resume_bytes).decode("ascii"),
        "OpptlyPersonId": record["person_id"],
        "FullName": record["full_name"],
        "JobId": record["job_id"],
        "JobTitle": record["job_title"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Opptly PublicLists URL to scrape")
    parser.add_argument(
        "-o", "--output", default="contentversions.json", help="Output JSON file"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process the first N rows (testing)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.5, help="Seconds to wait between resume downloads"
    )
    args = parser.parse_args()

    session = requests.Session()

    print(f"Fetching list page: {args.url}", file=sys.stderr)
    html = fetch_html(args.url, session)

    rows = parse_rows(html, args.url)
    print(f"Found {len(rows)} candidate rows with resumes", file=sys.stderr)

    if args.limit:
        rows = rows[: args.limit]

    cache = {}
    output = []
    for i, record in enumerate(rows, 1):
        print(
            f"[{i}/{len(rows)}] {record['full_name']} - {record['resume_filename']}",
            file=sys.stderr,
        )
        try:
            resume_bytes = download_resume(record["resume_url"], session, cache)
        except requests.RequestException as exc:
            print(f"  !! failed to download resume: {exc}", file=sys.stderr)
            continue

        output.append(build_contentversion(record, resume_bytes))
        time.sleep(args.delay)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(output)} ContentVersion records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
