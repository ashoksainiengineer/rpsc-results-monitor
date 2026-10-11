import re
import json
from html.parser import HTMLParser

URL = "https://rpsc.rajasthan.gov.in/results"


class TableParser(HTMLParser):
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
            self.cur = {"cells": [], "hrefs": []}
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
                self.cur["hrefs"].append(self.cell_href)
            self.in_cell = False
            self.cell = None

    def handle_data(self, data):
        if self.in_table and self.in_cell and self.cell is not None and not self.skip:
            self.cell.append(data)


def extract_rows(html):
    p = TableParser()
    p.feed(html)
    rows = p.rows
    if not rows:
        return [], []
    header = rows[0]["cells"]
    data = []
    for r in rows[1:]:
        cells = r["cells"]
        if not any(cells):
            continue
        hrefs = [h for h in r["hrefs"] if h]
        data.append({"cells": cells, "hrefs": hrefs})
    return header, data


if __name__ == "__main__":
    html = open("results.html", encoding="utf-8", errors="ignore").read()
    header, data = extract_rows(html)
    print("HEADER:", header)
    print("ROWS:", len(data))
    for r in data[:3]:
        print("---")
        print("cells:", r["cells"])
        print("hrefs:", r["hrefs"])
