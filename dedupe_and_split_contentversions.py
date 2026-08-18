"""
End-to-end: scrape an Opptly public candidate list, keep only candidates
missing from Salesforce (optional), download each candidate's LAST resume,
and write the result out as ContentVersion-style JSON files split into
chunks of 200 records.

Combines what used to be two separate scripts (scrape_opptly.py +
dedupe_and_split_contentversions.py) into one.

Output naming:
    contentversions.json     (records 1-200)
    contentversions_1.json   (records 201-400)
    contentversions_2.json   (records 401-600)
    ...

Progress is durably appended to a scratch file (<output base>.ndjson) as
each resume is downloaded, so an interrupted run can be re-launched with
the same command and it will skip everything already saved instead of
re-downloading.

Each record looks like:
    {
        "FirstPublishLocationId": null,
        "Title": "Chevaundae-Moore-resume",
        "PathOnClient": "Chevaundae-Moore-resume.pdf",
        "VersionData": "<base64 resume bytes>",
        "OpptlyPersonId": "9016490",
        "FullName": "'-Vaundae' Moore, Che",
        "JobId": "179306",
        "JobTitle": "Engineering Technician"
    }

Usage:
    pip install requests beautifulsoup4
    python dedupe_and_split_contentversions.py https://jobs.opptly.com/PublicLists/<list-id>
    python dedupe_and_split_contentversions.py <url> --missing-only candidates_existence_check.json
    python dedupe_and_split_contentversions.py <url> -o contentversions.json --chunk-size 200
"""

import argparse
import base64
import json
import os
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


def parse_rows(html: str, base_url: str) -> list:
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

        links = [a for a in cells[0].find_all("a") if a.get("href")]
        if not links:
            continue  # row without an attached resume
        link = links[-1]  # a row can list multiple attachments; use the last one

        resume_url = urljoin(base_dir, link["href"])
        resume_filename = link.get_text(strip=True)

        record = dict(zip(COLUMNS[1:], (c.get_text(strip=True) for c in cells[1:])))
        record["resume_url"] = resume_url
        record["resume_filename"] = resume_filename
        records.append(record)

    return records


def keep_last_per_person(rows: list) -> list:
    last_by_person = {}
    no_person_id = []
    order = []
    for record in rows:
        pid = record["person_id"]
        if not pid:
            no_person_id.append(record)
            continue
        if pid not in last_by_person:
            order.append(pid)
        last_by_person[pid] = record  # later rows overwrite earlier ones

    return [last_by_person[pid] for pid in order] + no_person_id


def load_missing_ids(path: str) -> set:
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f)["missing"])


def download_resume(
    url: str,
    session: requests.Session,
    cache: dict,
    retries: int = 3,
    backoff: float = 2.0,
) -> bytes:
    if url in cache:
        return cache[url]

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            resp.raise_for_status()
            cache[url] = resp.content
            return resp.content
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff * (2 ** (attempt - 1))
                print(
                    f"  !! attempt {attempt}/{retries} failed ({exc}), retrying in {wait:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(wait)

    raise last_exc


def build_contentversion(record: dict, resume_bytes: bytes) -> dict:
    filename = record["resume_filename"] or "resume"
    title = filename.rsplit(".", 1)[0] if "." in filename else filename

    return {
        "FirstPublishLocationId": None,
        "Title": title,
        "PathOnClient": filename,
        "VersionData": base64.b64encode(resume_bytes).decode("ascii"),
        "OpptlyPersonId": record["person_id"],
        "FullName": record["full_name"],
        "JobId": record["job_id"],
        "JobTitle": record["job_title"],
    }


def ndjson_path_for(output_path: str) -> str:
    root, _ext = os.path.splitext(output_path)
    return root + ".ndjson"


def append_record(ndjson_path: str, record: dict) -> None:
    # Append-only, O(1) per record -- never re-reads or rewrites prior records.
    with open(ndjson_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")))
        f.write("\n")


def load_seen_person_ids(ndjson_path: str) -> tuple:
    """Stream the ndjson scratch file to recover state from a prior run,
    without holding every record (including its base64 payload) in memory."""
    seen = set()
    count = 0
    if not os.path.exists(ndjson_path):
        return seen, count
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                pid = json.loads(line).get("OpptlyPersonId")
            except json.JSONDecodeError:
                continue
            if pid:
                seen.add(pid)
    return seen, count


def chunk_filename(base: str, index: int) -> str:
    if index == 0:
        return base
    name, ext = os.path.splitext(base)
    return f"{name}_{index}{ext}"


def split_ndjson_into_chunks(ndjson_path: str, output_base: str, chunk_size: int) -> int:
    """Text-stream the ndjson scratch file straight into chunk_size-record
    JSON array files -- no per-record decode/encode, so this stays cheap
    even at hundreds of MB."""
    if not os.path.exists(ndjson_path):
        with open(output_base, "w", encoding="utf-8") as f:
            f.write("[]")
        return 1

    chunk_index = 0
    count_in_chunk = 0
    out_f = None

    def open_chunk(idx):
        path = chunk_filename(output_base, idx)
        f = open(path, "w", encoding="utf-8")
        f.write("[")
        return f

    with open(ndjson_path, "r", encoding="utf-8") as fin:
        out_f = open_chunk(chunk_index)
        for line in fin:
            line = line.strip()
            if not line:
                continue
            if count_in_chunk == chunk_size:
                out_f.write("]")
                out_f.close()
                chunk_index += 1
                count_in_chunk = 0
                out_f = open_chunk(chunk_index)

            if count_in_chunk > 0:
                out_f.write(",")
            out_f.write(line)
            count_in_chunk += 1

        out_f.write("]")
        out_f.close()

    return chunk_index + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Opptly PublicLists URL to scrape")
    parser.add_argument(
        "-o", "--output", default="contentversions.json", help="Base output JSON file name"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=200, help="Records per output file"
    )
    parser.add_argument(
        "--missing-only",
        metavar="EXISTENCE_CHECK_JSON",
        default=None,
        help="Path to a candidates_existence_check.json file; only process "
        "candidates listed under its 'missing' key (skip ones already in SF)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process the first N candidates (testing)"
    )
    parser.add_argument(
        "--delay", type=float, default=5.0, help="Seconds to wait between resume downloads"
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=100,
        help="Refresh the chunked JSON output every N processed records "
        "(each record is durably appended immediately regardless)",
    )
    parser.add_argument(
        "--desc",
        action="store_true",
        help="Process candidates sorted by Full name in descending order",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of attempts when fetching a resume before giving up",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Base seconds to wait between resume fetch retries (doubles each attempt)",
    )
    args = parser.parse_args()

    session = requests.Session()

    print(f"Fetching list page: {args.url}", file=sys.stderr)
    html = fetch_html(args.url, session)

    rows = parse_rows(html, args.url)
    print(f"Found {len(rows)} candidate rows with resumes", file=sys.stderr)

    rows = keep_last_per_person(rows)
    print(f"{len(rows)} unique candidates after keeping last resume per OpptlyPersonId", file=sys.stderr)

    if args.missing_only:
        missing_ids = load_missing_ids(args.missing_only)
        before = len(rows)
        rows = [r for r in rows if r["person_id"] in missing_ids]
        print(
            f"--missing-only: kept {len(rows)}/{before} candidates present in "
            f"{args.missing_only}'s 'missing' list",
            file=sys.stderr,
        )

    if args.desc:
        rows.sort(key=lambda r: r["full_name"].lower(), reverse=True)

    if args.limit:
        rows = rows[: args.limit]

    total = len(rows)
    cache = {}
    ndjson_path = ndjson_path_for(args.output)
    seen_person_ids, existing_count = load_seen_person_ids(ndjson_path)
    processed = existing_count
    if seen_person_ids:
        print(
            f"Resuming from {ndjson_path}: {existing_count} records already saved "
            f"({len(seen_person_ids)} unique OpptlyPersonId)",
            file=sys.stderr,
        )

    for current, record in enumerate(rows, 1):
        person_id = record["person_id"]
        progress = f"[current {current}/{total} | processed {processed}]"

        if person_id and person_id in seen_person_ids:
            print(
                f"{progress} skip (OpptlyPersonId {person_id} already saved)",
                file=sys.stderr,
            )
            continue

        print(
            f"{progress} {record['full_name']} - {record['resume_filename']}",
            file=sys.stderr,
        )
        try:
            resume_bytes = download_resume(
                record["resume_url"],
                session,
                cache,
                retries=args.retries,
                backoff=args.retry_backoff,
            )
        except requests.RequestException as exc:
            print(f"  !! failed to download resume after {args.retries} attempts: {exc}", file=sys.stderr)
            continue

        # Append-only write: O(1), never rereads or rewrites prior records.
        append_record(ndjson_path, build_contentversion(record, resume_bytes))
        if person_id:
            seen_person_ids.add(person_id)
        processed += 1

        if processed % args.save_every == 0:
            n_chunks = split_ndjson_into_chunks(ndjson_path, args.output, args.chunk_size)
            print(f"  -- refreshed {n_chunks} chunk file(s) ({processed} records) --", file=sys.stderr)

        time.sleep(args.delay)

    n_chunks = split_ndjson_into_chunks(ndjson_path, args.output, args.chunk_size)

    print(f"Wrote {processed} ContentVersion records across {n_chunks} file(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
