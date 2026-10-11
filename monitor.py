#!/usr/bin/env python3
"""
RPSC Results monitor.

Fetches https://rpsc.rajasthan.gov.in/results, parses the results table and
pushes a notification (via ntfy.sh) whenever new result rows appear.

Only the Python standard library is used, so it runs anywhere with python3.

State is kept in state.json: a set of fingerprints of every result row seen so
far. New rows = rows present now whose fingerprint was not seen before.

Usage:
    python monitor.py              # normal run (notify + update state)
    python monitor.py --dry-run    # do not write state / send notifications
    python monitor.py --test       # send a test notification to ntfy
    python monitor.py --verbose
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urljoin

BASE_URL = "https://rpsc.rajasthan.gov.in/"
PAGE_URL = urljoin(BASE_URL, "results")
DEFAULT_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# Fetch + parse
# --------------------------------------------------------------------------- #
class ResultsTableParser(HTMLParser):
    """Extract rows (and the first link in every row) of the first table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.rows = []
        self.cur = None
        self.cell = None
        self.in_cell = False
        self.cell_href = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag in ("script", "style"):
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "tr":
            self.cur = {"cells": [], "href": None}
        elif tag in ("td", "th"):
            self.in_cell = True
            self.cell = []
            self.cell_href = None
        elif tag == "a" and self.in_cell:
            href = a.get("href")
            if href and not self.cell_href:
                self.cell_href = href

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
            return
        if not self.in_table or self.skip:
            return
        if tag == "table":
            self.in_table = False
        elif tag == "tr":
            if self.cur:
                self.rows.append(self.cur)
                self.cur = None
        elif tag in ("td", "th"):
            if self.cur is not None:
                txt = re.sub(r"\s+", " ", "".join(self.cell)).strip()
                self.cur["cells"].append(txt)
                if self.cell_href and not self.cur["href"]:
                    self.cur["href"] = self.cell_href
            self.in_cell = False
            self.cell = None

    def handle_data(self, data):
        if self.in_table and self.in_cell and self.cell is not None and not self.skip:
            self.cell.append(data)


def fetch_html(url=PAGE_URL, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="ignore")


def parse_results(html):
    """Return a list of dicts: {date, exam, desc, link}."""
    p = ResultsTableParser()
    p.feed(html)
    rows = p.rows
    if not rows:
        return []
    header = [c.lower() for c in rows[0]["cells"]]
    # Locate the columns defensively.
    try:
        i_date = next(i for i, c in enumerate(header) if "release" in c and "date" in c)
        i_exam = next(i for i, c in enumerate(header) if "exam" in c)
        i_desc = next(i for i, c in enumerate(header) if "desc" in c or "detail" in c)
    except StopIteration:
        i_date, i_exam, i_desc = 1, 2, 3

    out = []
    for r in rows[1:]:
        cells = r["cells"]
        if len(cells) <= max(i_date, i_exam, i_desc):
            continue
        date = cells[i_date]
        exam = cells[i_exam]
        desc = cells[i_desc]
        if not (date or exam or desc):
            continue
        link = urljoin(BASE_URL, r["href"]) if r["href"] else PAGE_URL
        out.append({"date": date, "exam": exam, "desc": desc, "link": link})
    return out


def fingerprint(row):
    key = "|".join([row["date"], row["exam"], row["desc"], row["link"]])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_state(path, seen, new_count):
    import datetime

    data = {
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "total": len(seen),
        "seen": sorted(seen),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=False)
        f.write("\n")


# --------------------------------------------------------------------------- #
# ntfy notification
# --------------------------------------------------------------------------- #
def send_ntfy(topic, title, message, *, server="https://ntfy.sh", priority="high",
              tags="bell", click=PAGE_URL, token=None):
    url = server.rstrip("/") + "/" + topic
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
        "Tags": tags,
        "Click": click,
        "Markdown": "yes",
        "Content-Type": "text/markdown; charset=utf-8",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def build_message(new_rows):
    lines = []
    for r in new_rows:
        lines.append(f"**{r['date']} — {r['exam']}**\n{r['desc']}\n[Open result]({r['link']})")
    return "\n\n---\n\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Monitor RPSC results page for updates.")
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--topic", default=os.environ.get("NTFY_TOPIC", ""))
    ap.add_argument("--server", default=os.environ.get("NTFY_SERVER", "https://ntfy.sh"))
    ap.add_argument("--token", default=os.environ.get("NTFY_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true", help="avoid state writes / notifications")
    ap.add_argument("--test", action="store_true", help="send a test notification")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    def log(*a):
        if args.verbose or args.test:
            print(*a, file=sys.stderr)

    if args.test:
        if not args.topic:
            print("ERROR: no --topic / NTFY_TOPIC set", file=sys.stderr)
            return 2
        st = send_ntfy(args.topic, "RPSC monitor test",
                       "Agar ye message dikh raha hai to notifications Kaam kar rahe hain. ✅",
                       server=args.server, token=args.token)
        print(f"ntfy HTTP {st} (topic={args.topic})")
        return 0

    log("Fetching", PAGE_URL)
    try:
        html = fetch_html()
    except Exception as e:
        print(f"ERROR: fetch failed: {e}", file=sys.stderr)
        return 1

    rows = parse_results(html)
    log(f"Parsed {len(rows)} rows")
    if len(rows) < 10:
        print(f"ERROR: suspiciously few rows parsed ({len(rows)}); aborting without "
              f"touching state.", file=sys.stderr)
        return 1

    seen_now = {fingerprint(r) for r in rows}
    state = load_state(args.state)

    if state is None:
        # First ever run: save baseline, do not notify.
        print(f"Baseline created with {len(seen_now)} results (no notification sent).")
        if not args.dry_run:
            save_state(args.state, seen_now, 0)
        return 0

    seen_before = set(state.get("seen", []))
    new_fps = seen_now - seen_before
    new_rows = [r for r in rows if fingerprint(r) in new_fps]

    # Preserve page order (newest first).
    log(f"New rows: {len(new_rows)}")

    if not new_rows:
        print("No new results.")
        if not args.dry_run:
            # keep updated timestamp + prune removed rows
            save_state(args.state, seen_now, 0)
        return 0

    # Only-once guard for removed/re-added duplicates handled by set logic.
    title = (f"New RPSC result: {new_rows[0]['exam']}"
             if len(new_rows) == 1 else f"{len(new_rows)} new RPSC results")
    message = build_message(new_rows)

    if args.dry_run or not args.topic:
        if not args.topic:
            print("WARNING: NTFY_TOPIC not set; printing only.", file=sys.stderr)
        print(message)
    else:
        try:
            st = send_ntfy(args.topic, title, message, server=args.server, token=args.token)
            print(f"Notified ntfy (HTTP {st}) about {len(new_rows)} new result(s).")
        except Exception as e:
            print(f"ERROR: ntfy send failed: {e}", file=sys.stderr)
            return 1

    if not args.dry_run:
        save_state(args.state, seen_now, len(new_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
