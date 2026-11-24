#!/usr/bin/env python3
"""Deterministic iPhone Duo in-store pickup watcher.

Asks Apple's store-pickup endpoint which nearby Apple Stores can hand over an
iPhone Duo today, and sends an ntfy push when a (store, configuration) pair
becomes available. There is one rule and no judgement call:

    a configuration is in stock at a store  <=>  pickupDisplay == "available"

Configuration (environment variables):
    DUO_ZIP         ZIP code (or "City, ST") that "nearby" is centred on. Required.
    NTFY_TOPIC      ntfy topic to publish to. Required unless --dry-run.
    NTFY_SERVER     ntfy server, default https://ntfy.sh
    NTFY_TOKEN      Optional ntfy access token. Sending as an account avoids the
                    per-IP rate limit that shared CI runners can run into.
    DUO_PARTS       Comma-separated part numbers to watch, default: all eight.
    DUO_MAX_MILES   Ignore stores further away than this, default 50.
    DUO_STATE_FILE  Where to remember what was already announced,
                    default .duo-state.json

Exit codes: 0 check completed, 1 bad configuration, 2 Apple check failed,
3 notification failed.

Output is deliberately free of store names and locations unless --verbose is
given, because the scheduled run's logs are public.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PICKUP_URL = "https://www.apple.com/shop/retail/pickup-message"
BUY_URL = "https://www.apple.com/shop/buy-iphone/iphone-duo"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)

# US part numbers. The same part number covers every carrier and unlocked.
PARTS = {
    "MK1F4LL/A": "256GB Night Sky",
    "MK1E4LL/A": "256GB Star White",
    "MK1H4LL/A": "512GB Night Sky",
    "MK1G4LL/A": "512GB Star White",
    "MK1L4LL/A": "1TB Night Sky",
    "MK1J4LL/A": "1TB Star White",
    "MK1R4LL/A": "2TB Night Sky",
    "MK1Q4LL/A": "2TB Star White",
}

EXIT_OK, EXIT_CONFIG, EXIT_CHECK_FAILED, EXIT_NOTIFY_FAILED = 0, 1, 2, 3


class ConfigError(Exception):
    pass


class CheckError(Exception):
    pass


class NotifyError(Exception):
    pass


@dataclass(frozen=True)
class Hit:
    """One configuration that one store can hand over."""

    store_number: str
    store_name: str
    city: str
    distance: float | None
    part: str
    quote: str

    @property
    def config(self) -> str:
        return PARTS.get(self.part, self.part)


def build_url(location: str, parts: list[str]) -> str:
    query = [("pl", "true"), ("location", location)]
    query += [(f"parts.{i}", part) for i, part in enumerate(parts)]
    return PICKUP_URL + "?" + urllib.parse.urlencode(query, safe="/")


def fetch(url: str, attempts: int = 3, timeout: int = 30) -> dict:
    """GET the pickup endpoint. Error text never includes the URL (it holds the ZIP)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"network error ({type(exc).__name__})"
        except ValueError:
            last = "response was not JSON"
        if attempt < attempts:
            time.sleep(5 * attempt)
    raise CheckError(f"Apple pickup endpoint failed after {attempts} attempts: {last}")


def parse_availability(
    payload: dict, parts: list[str], max_miles: float
) -> tuple[list[Hit], int]:
    """Return (configurations in stock, number of stores within range)."""
    body = payload.get("body")
    if not isinstance(body, dict):
        raise CheckError("unexpected response shape: no body")
    if body.get("errorMessage"):
        raise CheckError(f"Apple rejected the query: {body['errorMessage']}")
    stores = body.get("stores")
    if not isinstance(stores, list) or not stores:
        raise CheckError("unexpected response shape: no stores listed")

    hits: list[Hit] = []
    in_range = 0
    for store in stores:
        distance = store.get("storedistance")
        if isinstance(distance, (int, float)) and distance > max_miles:
            continue
        in_range += 1
        availability = store.get("partsAvailability")
        if not isinstance(availability, dict):
            raise CheckError("unexpected response shape: store without partsAvailability")
        for part in parts:
            info = availability.get(part)
            if not isinstance(info, dict) or "pickupDisplay" not in info:
                raise CheckError(f"response has no pickup status for {part}")
            if info["pickupDisplay"] == "available":
                hits.append(
                    Hit(
                        store_number=str(store.get("storeNumber", "")),
                        store_name=str(store.get("storeName", "")),
                        city=str(store.get("city", "")),
                        distance=distance if isinstance(distance, (int, float)) else None,
                        part=part,
                        quote=str(info.get("pickupSearchQuote", "")),
                    )
                )
    return hits, in_range


def fingerprint(key: str, hit: Hit) -> str:
    """Opaque id for a (store, part) pair, so the saved state names no store."""
    message = f"{hit.store_number}|{hit.part}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def load_state(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            return set(json.load(handle)["available"])
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def save_state(path: str, fingerprints: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"available": sorted(fingerprints)}, handle)
        handle.write("\n")


def format_alert(hits: list[Hit]) -> tuple[str, str]:
    """Title and body of the push for newly available configurations."""
    by_store: dict[str, list[Hit]] = {}
    for hit in hits:
        by_store.setdefault(hit.store_number, []).append(hit)
    lines = []
    for store_hits in by_store.values():
        first = store_hits[0]
        where = f"Apple {first.store_name}"
        if first.city:
            where += f", {first.city}"
        if first.distance is not None:
            where += f" ({first.distance:g} mi)"
        lines.append(where)
        lines += [f"  - {hit.config}: {hit.quote or 'available'}" for hit in store_hits]
    if len(by_store) == 1:
        title = f"iPhone Duo in stock: Apple {hits[0].store_name}"
    else:
        title = f"iPhone Duo in stock at {len(by_store)} stores"
    return title, "\n".join(lines)


def send_ntfy(
    server: str,
    topic: str,
    title: str,
    message: str,
    token: str = "",
    attempts: int = 3,
) -> None:
    """Publish a push. Rate limits (429) and server errors are retried."""
    payload = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": 5,
        "tags": ["iphone"],
        "click": BUY_URL,
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        server.rstrip("/") + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    last = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            return
        except urllib.error.HTTPError as exc:
            last = f"ntfy returned HTTP {exc.code}"
            if exc.code != 429 and exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"could not reach ntfy ({type(exc).__name__})"
        if attempt < attempts:
            time.sleep(10 * attempt)
    raise NotifyError(last)


def write_github_output(**values: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for name, value in values.items():
            handle.write(f"{name}={str(value).lower()}\n")


def read_config(env: dict, need_topic: bool) -> dict:
    location = env.get("DUO_ZIP", "").strip()
    if not location:
        raise ConfigError("DUO_ZIP is not set")
    topic = env.get("NTFY_TOPIC", "").strip()
    if need_topic and not topic:
        raise ConfigError("NTFY_TOPIC is not set")
    raw_parts = env.get("DUO_PARTS", "").strip()
    parts = [p.strip().upper() for p in raw_parts.split(",") if p.strip()] or list(PARTS)
    unknown = [p for p in parts if p not in PARTS]
    if unknown:
        raise ConfigError(f"DUO_PARTS has unknown part numbers: {', '.join(unknown)}")
    try:
        max_miles = float(env.get("DUO_MAX_MILES", "").strip() or 50)
    except ValueError:
        raise ConfigError("DUO_MAX_MILES must be a number") from None
    return {
        "location": location,
        "topic": topic,
        "token": env.get("NTFY_TOKEN", "").strip(),
        "server": env.get("NTFY_SERVER", "").strip() or "https://ntfy.sh",
        "parts": parts,
        "max_miles": max_miles,
        "state_file": env.get("DUO_STATE_FILE", "").strip() or ".duo-state.json",
    }


def run(args: argparse.Namespace, env: dict) -> int:
    config = read_config(env, need_topic=not args.dry_run)

    if args.test_notify:
        send_ntfy(
            config["server"],
            config["topic"],
            "iPhone Duo watcher: test",
            "Notifications work. You will get a push like this when a nearby "
            "Apple Store has an iPhone Duo ready for pickup.",
            token=config["token"],
        )
        print("Test notification sent.")
        return EXIT_OK

    payload = fetch(build_url(config["location"], config["parts"]))
    hits, in_range = parse_availability(payload, config["parts"], config["max_miles"])
    if in_range == 0:
        raise ConfigError(
            f"no Apple Store within {config['max_miles']:g} miles of DUO_ZIP; "
            "raise DUO_MAX_MILES"
        )

    key = config["topic"] or "local"
    current = {fingerprint(key, hit) for hit in hits}
    previous = load_state(config["state_file"])
    new_hits = [hit for hit in hits if fingerprint(key, hit) not in previous]

    print(f"Check complete: {len(hits)} available, {len(new_hits)} newly available.")
    if args.verbose:
        print(f"  {in_range} stores in range, {len(config['parts'])} configurations each")
        for hit in hits:
            print(f"  Apple {hit.store_name}: {hit.config} ({hit.quote})")

    if args.dry_run:
        return EXIT_OK

    if new_hits:
        title, body = format_alert(new_hits)
        send_ntfy(config["server"], config["topic"], title, body, token=config["token"])
        print("Notification sent.")
    # Saved only after a successful send, so a failed push is retried next run.
    if current != previous:
        save_state(config["state_file"], current)
    write_github_output(state_changed=current != previous, available=len(hits))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="check stock but send nothing and save no state")
    parser.add_argument("--verbose", action="store_true",
                        help="also print which stores have which configuration")
    parser.add_argument("--test-notify", action="store_true",
                        help="send a test push and exit without checking stock")
    args = parser.parse_args(argv)
    try:
        return run(args, dict(os.environ))
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except CheckError as exc:
        print(f"Check failed: {exc}", file=sys.stderr)
        return EXIT_CHECK_FAILED
    except NotifyError as exc:
        print(f"Notification failed: {exc}", file=sys.stderr)
        return EXIT_NOTIFY_FAILED


if __name__ == "__main__":
    sys.exit(main())
