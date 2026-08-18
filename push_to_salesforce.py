"""
Push ContentVersion records (built by scrape_opptly.py /
dedupe_and_split_contentversions.py) into Salesforce, linking each resume
to its Candidate__c record.

For each record's OpptlyPersonId, looks up the matching Candidate__c.Id via
the Avature_Person_ID__c field, and inserts in batches of up to 200 via the
REST Composite sObject Collections API with only the real ContentVersion
fields (Title, PathOnClient, VersionData, FirstPublishLocationId) --
JobTitle/JobId/FullName/OpptlyPersonId are dropped from the payload, they
only exist to drive this script's own matching/logging.

Setting FirstPublishLocationId to the Candidate__c.Id makes Salesforce
auto-create the ContentDocumentLink to that candidate.

On success, the record is rewritten in its source chunk file with
FirstPublishLocationId set to the real Candidate__c.Id and
JobTitle/JobId/FullName/OpptlyPersonId removed. Records that fail or have
no Candidate__c match are left untouched (so a retry can still find their
OpptlyPersonId).

candidates_existence_check.csv is updated as records are processed: rows
for a successfully-pushed OpptlyPersonId flip from "Not Exist" to
"Created"; rows for a failed push are set to "Error" with the failure
reason recorded in a new "Error" column.

Uses the Salesforce CLI (`sf`) for auth -- the target org must already be
authenticated (`sf org login web --alias <org>`).

--limit caps how many NEW (not-yet-pushed) records are pushed in this run.
Progress is tracked in <base>.pushed.ndjson, so rerunning with a fresh
--limit continues where the last run left off without re-pushing anyone
or re-querying Salesforce for candidates already linked.

Usage:
    python push_to_salesforce.py --target-org Production --limit 200
    python push_to_salesforce.py --base contentversions.json --target-org Preprod --limit 50
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile

CANDIDATE_ID_FIELD = "Avature_Person_ID__c"
QUERY_BATCH_SIZE = 200  # SOQL IN-clause batch
PUSH_BATCH_SIZE = 200  # composite sobjects collection hard limit
FIELDS_DROPPED_ON_SUCCESS = ("JobTitle", "JobId", "FullName", "OpptlyPersonId")


def chunk_filename(base: str, index: int) -> str:
    if index == 0:
        return base
    name, ext = os.path.splitext(base)
    return f"{name}_{index}{ext}"


def discover_chunks(dir_: str, base: str) -> list:
    paths = []
    index = 0
    while True:
        path = os.path.join(dir_, chunk_filename(base, index))
        if not os.path.exists(path):
            break
        paths.append(path)
        index += 1
    return paths


def run_sf_json(args: list) -> dict:
    """For `sf` subcommands that support --json (e.g. data query)."""
    cmd = ["sf"] + args + ["--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        raise RuntimeError(f"sf command failed: {' '.join(args)}\n{result.stderr or result.stdout}")
    payload = json.loads(result.stdout)
    if payload.get("status") != 0:
        raise RuntimeError(f"sf command returned non-zero status: {payload}")
    return payload["result"]


def load_pushed_ids(pushed_log_path: str) -> set:
    pushed = set()
    if not os.path.exists(pushed_log_path):
        return pushed
    with open(pushed_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pushed.add(json.loads(line)["OpptlyPersonId"])
            except (json.JSONDecodeError, KeyError):
                continue
    return pushed


def append_pushed(pushed_log_path: str, entry: dict) -> None:
    with open(pushed_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")))
        f.write("\n")


def query_candidate_ids(person_ids: list, target_org: str) -> dict:
    mapping = {}
    unique_ids = sorted(set(person_ids))
    for i in range(0, len(unique_ids), QUERY_BATCH_SIZE):
        batch = unique_ids[i : i + QUERY_BATCH_SIZE]
        id_list = ",".join("'" + pid.replace("'", "\\'") + "'" for pid in batch)
        soql = (
            f"SELECT Id, {CANDIDATE_ID_FIELD} FROM Candidate__c "
            f"WHERE {CANDIDATE_ID_FIELD} IN ({id_list})"
        )
        result = run_sf_json(["data", "query", "--query", soql, "--target-org", target_org])
        for rec in result["records"]:
            mapping[rec[CANDIDATE_ID_FIELD]] = rec["Id"]
    return mapping


def push_batch(sf_records: list, target_org: str, api_version: str) -> list:
    body = {"allOrNone": False, "records": sf_records}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(body, f)
        body_path = f.name

    try:
        cmd = [
            "sf", "api", "request", "rest",
            f"services/data/v{api_version}/composite/sobjects",
            "--target-org", target_org,
            "-X", "POST",
            "-b", f"@{body_path}",
            "-H", "Content-Type: application/json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f"push batch failed: {result.stderr or result.stdout}")
        return json.loads(result.stdout)
    finally:
        os.unlink(body_path)


def load_existence_csv(path: str) -> tuple:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    if "Error" not in fieldnames:
        fieldnames.append("Error")
        for row in rows:
            row["Error"] = ""
    return fieldnames, rows


def write_existence_csv(path: str, fieldnames: list, rows: list) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=".", help="Directory containing the chunk files")
    parser.add_argument("--base", default="contentversions.json", help="Base file name (chunk 0)")
    parser.add_argument(
        "--target-org", required=True, help="sf CLI target org alias/username (e.g. Production, Preprod)"
    )
    parser.add_argument(
        "--limit", type=int, required=True, help="Max number of NEW records to push this run"
    )
    parser.add_argument("--api-version", default="61.0", help="Salesforce REST API version")
    parser.add_argument(
        "--pushed-log",
        default=None,
        help="ndjson file tracking already-pushed OpptlyPersonId (default: <base>.pushed.ndjson)",
    )
    parser.add_argument(
        "--existence-csv",
        default="candidates_existence_check.csv",
        help="candidates_existence_check.csv to update with Created/Error status",
    )
    args = parser.parse_args()

    pushed_log = args.pushed_log or (
        os.path.splitext(os.path.join(args.dir, args.base))[0] + ".pushed.ndjson"
    )

    chunk_paths = discover_chunks(args.dir, args.base)
    if not chunk_paths:
        raise SystemExit(f"No files found for base '{args.base}' in {args.dir}")

    chunks = {}  # path -> mutable list of records
    total_records = 0
    for path in chunk_paths:
        with open(path, "r", encoding="utf-8") as f:
            chunks[path] = json.load(f)
        total_records += len(chunks[path])
    print(
        f"Found {len(chunk_paths)} file(s) for base '{args.base}', {total_records} total records",
        file=sys.stderr,
    )

    pushed_ids = load_pushed_ids(pushed_log)
    if pushed_ids:
        print(f"{len(pushed_ids)} candidates already pushed (from {pushed_log})", file=sys.stderr)

    # (chunk_path, index_in_chunk, record) in file/record order.
    to_push = []
    for path in chunk_paths:
        for idx, rec in enumerate(chunks[path]):
            pid = rec.get("OpptlyPersonId")
            if not pid:
                continue  # already finalized: fields stripped after a prior successful push
            if pid in pushed_ids:
                continue
            to_push.append((path, idx, rec))
            if len(to_push) >= args.limit:
                break
        if len(to_push) >= args.limit:
            break

    print(f"Selected {len(to_push)} new record(s) to push this run (--limit {args.limit})", file=sys.stderr)
    if not to_push:
        return

    person_ids = [rec.get("OpptlyPersonId") for _, _, rec in to_push if rec.get("OpptlyPersonId")]
    print(
        f"Querying Candidate__c.Id for {len(set(person_ids))} unique OpptlyPersonId via {CANDIDATE_ID_FIELD}...",
        file=sys.stderr,
    )
    candidate_map = query_candidate_ids(person_ids, args.target_org)
    print(f"Matched {len(candidate_map)}/{len(set(person_ids))} candidates in Salesforce", file=sys.stderr)

    existence_fieldnames, existence_rows = load_existence_csv(args.existence_csv)
    rows_by_person_id = {}
    for row in existence_rows:
        rows_by_person_id.setdefault(row.get("Person ID"), []).append(row)

    def mark_existence(pid: str, status: str, error: str = "", candidate_id: str = None) -> None:
        for row in rows_by_person_id.get(pid, []):
            row["Exists"] = status
            row["Error"] = error
            if candidate_id:
                row["Candidate_SF_Id"] = candidate_id
            if status == "Created":
                row["Job_Submission_Exists"] = "Created"

    ready = []
    unmatched = []
    for path, idx, rec in to_push:
        pid = rec.get("OpptlyPersonId")
        candidate_id = candidate_map.get(pid)
        if not candidate_id:
            unmatched.append((path, idx, rec))
            continue
        sf_record = {
            "attributes": {"type": "ContentVersion"},
            "Title": rec.get("Title"),
            "PathOnClient": rec.get("PathOnClient"),
            "VersionData": rec.get("VersionData"),
            "FirstPublishLocationId": candidate_id,
            "Onboarding_File_Type_fileupload__c": "RESUME",
        }
        ready.append((path, idx, rec, candidate_id, sf_record))

    if unmatched:
        print(f"  !! {len(unmatched)} record(s) skipped: no matching Candidate__c found", file=sys.stderr)
        for path, idx, rec in unmatched:
            pid = rec.get("OpptlyPersonId")
            print(f"     - OpptlyPersonId {pid} ({rec.get('FullName')})", file=sys.stderr)
            mark_existence(pid, "Error", "No matching Candidate__c found for OpptlyPersonId")

    pushed_count = 0
    failed_count = 0
    changed_chunk_paths = set()

    for i in range(0, len(ready), PUSH_BATCH_SIZE):
        batch = ready[i : i + PUSH_BATCH_SIZE]
        sf_records = [sf_rec for _, _, _, _, sf_rec in batch]
        results = push_batch(sf_records, args.target_org, args.api_version)

        for (path, idx, rec, candidate_id, _), result in zip(batch, results):
            pid = rec.get("OpptlyPersonId")
            if result.get("success"):
                pushed_count += 1
                content_version_id = result.get("id")
                print(
                    f"  [OK] OpptlyPersonId={pid} CandidateId={candidate_id} "
                    f"ContentVersionId={content_version_id} ({rec.get('FullName')})",
                    file=sys.stderr,
                )
                append_pushed(
                    pushed_log,
                    {
                        "OpptlyPersonId": pid,
                        "ContentVersionId": content_version_id,
                        "CandidateId": candidate_id,
                        "FullName": rec.get("FullName"),
                    },
                )
                # Finalize the record in its source chunk file: real
                # FirstPublishLocationId, and drop the scrape-only fields.
                rec["FirstPublishLocationId"] = candidate_id
                for field in FIELDS_DROPPED_ON_SUCCESS:
                    rec.pop(field, None)
                chunks[path][idx] = rec
                changed_chunk_paths.add(path)

                mark_existence(pid, "Created", candidate_id=candidate_id)
            else:
                failed_count += 1
                error_msg = json.dumps(result.get("errors"))
                print(f"  !! push failed for OpptlyPersonId {pid}: {error_msg}", file=sys.stderr)
                mark_existence(pid, "Error", error_msg)

        print(f"  -- pushed batch of {len(batch)} ({pushed_count} succeeded so far) --", file=sys.stderr)

    for path in changed_chunk_paths:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chunks[path], f, indent=2)
    if changed_chunk_paths:
        print(f"Updated {len(changed_chunk_paths)} chunk file(s) with resolved FirstPublishLocationId", file=sys.stderr)

    write_existence_csv(args.existence_csv, existence_fieldnames, existence_rows)
    print(f"Updated {args.existence_csv}", file=sys.stderr)

    print(
        f"Done: {pushed_count} pushed, {failed_count} failed, {len(unmatched)} unmatched (no Candidate__c match)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
