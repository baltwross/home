#!/usr/bin/env python3
"""Rebuild apple_stores_us.json, the table of US Apple Store positions.

watch_iphone_duo.py uses the table to know which stores lie within range of a
location, because Apple's pickup endpoint lists only the 12 nearest stores per
query. Run this when Apple opens or closes a US store:

    ./refresh_apple_stores.py

It reads the store numbers from Apple's public store list, then asks the
pickup endpoint around stores it has not placed yet until all have coordinates.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

import watch_iphone_duo as watcher

STORE_LIST_URL = "https://www.apple.com/retail/storelist/"
PART = next(iter(watcher.PARTS))


def directory() -> list[str]:
    """Store numbers of every US Apple Store, from the public store list page."""
    request = urllib.request.Request(STORE_LIST_URL, headers={"User-Agent": watcher.USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        page = response.read().decode("utf-8", errors="replace")
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise SystemExit("store list page has no embedded data; its layout has changed")
    locales = json.loads(match.group(1))["props"]["pageProps"]["storeList"]
    country = next(entry for entry in locales if entry.get("locale") == "en_US")
    return sorted(store["id"] for state in country["state"] for store in state["store"])


def main() -> int:
    numbers = directory()
    positions: dict[str, tuple[float, float]] = {}
    unplaced = []
    for number in numbers:
        if number in positions:
            continue
        try:
            payload = watcher.fetch(watcher.build_url([PART], store=number))
            listed = watcher.parse_stores(payload, [PART])
        except watcher.CheckError as exc:
            print(f"{number}: {exc}", file=sys.stderr)
            unplaced.append(number)
            continue
        for store in listed:
            if store.position is not None:
                positions[store.number] = store.position
        if number not in positions:
            unplaced.append(number)
        time.sleep(0.2)

    table = {number: list(positions[number]) for number in sorted(positions)}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), watcher.STORE_TABLE)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{\n")
        handle.write(",\n".join(f'  "{n}": {json.dumps(p)}' for n, p in table.items()))
        handle.write("\n}\n")
    print(f"Wrote {len(table)} stores to {watcher.STORE_TABLE} ({len(numbers)} in Apple's list).")
    if unplaced:
        print(f"Not offering pickup, left out: {', '.join(unplaced)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
