# SmartHome Automation

A collection of scripts and configurations for home automation, including Roomba diagnostics and monitoring tools.

## Features

- Roomba diagnostics and monitoring
- iPhone monitoring scripts
- Home Assistant configurations

## Setup

1. Clone this repository
2. Create a `.env` file with your environment variables (see `.env.example` if available)
3. Make the scripts executable: `chmod +x *.sh`

## Scripts

- `diagnose_roomba.sh`: Run diagnostics on Roomba devices
- `monitor_iphone.sh`: Monitor iPhone status and connectivity
- `setup_roomba.sh`: Setup and configure Roomba devices
- `watch_iphone_duo.py`: Alert when a nearby Apple Store has an iPhone Duo ready for pickup
- `refresh_apple_stores.py`: Rebuild the table of US Apple Store positions the watcher uses

## iPhone Duo stock watch

`watch_iphone_duo.py` asks Apple's store-pickup endpoint about every iPhone Duo
configuration at every Apple Store within 100 miles of a ZIP code and sends an
[ntfy](https://ntfy.sh) push when one becomes available. The rule is fixed: a
configuration counts as in stock only when Apple reports
`pickupDisplay: "available"` for it at that store. Each (store, configuration)
pair is announced once, and again only after it has gone out of stock and come back.

Apple lists only the 12 nearest stores per query. Where that list stops short of
the radius, the script takes every store in range from `apple_stores_us.json` (the
positions of all US Apple Stores) and asks again around the ones not yet seen:
one query in most places, about five in the densest areas. A store
that opens later is still picked up when Apple lists it next to known ones; run
`./refresh_apple_stores.py` to rebuild the table and be sure.

The watcher is currently off: nothing starts it automatically.

To start it, open Actions → iPhone Duo stock watch → Run workflow. One run then
checks every 30 seconds for five and a half hours and starts the next run before
it ends, so it keeps going until you cancel the run in progress.

The push opens Apple's page for the exact configuration (unlocked; the carrier
can be changed there), with a button per configuration when there are several.

### Setup

1. Install the ntfy app on your phone and subscribe to a topic with a long random
   name (for example the output of `openssl rand -hex 16`). Anyone who knows the
   name can read the topic, so treat it like a password.
2. In the repository, open Settings → Secrets and variables → Actions and add two
   repository secrets:
   - `DUO_ZIP`: the ZIP code to search around
   - `NTFY_TOPIC`: the topic name from step 1
3. Open Actions → iPhone Duo stock watch → Run workflow, tick
   "Send a test push", and confirm the push arrives.

A run fails straight away if either secret is missing.

### Options

| Name | Kind | Default | Meaning |
| --- | --- | --- | --- |
| `DUO_MAX_MILES` | variable | `100` | Check every Apple Store within this many miles |
| `DUO_PARTS` | variable | all eight | Comma-separated part numbers to watch |
| `NTFY_TOKEN` | secret | none | ntfy access token, if pushes get rate limited (HTTP 429) |

Part numbers: `MK1F4LL/A` 256GB Night Sky, `MK1E4LL/A` 256GB Star White,
`MK1H4LL/A` 512GB Night Sky, `MK1G4LL/A` 512GB Star White, `MK1L4LL/A` 1TB Night
Sky, `MK1J4LL/A` 1TB Star White, `MK1R4LL/A` 2TB Night Sky, `MK1Q4LL/A` 2TB Star
White.

### Good to know

- This repository is public, so the workflow logs are too. The scheduled run
  prints only counts; store names appear only in the push.
- A failed check or push does not stop the watcher; it tries again 30 seconds
  later. After ten failed checks in a row it sends one "watcher is failing" push,
  and another when checks work again.
- This holds one GitHub-hosted runner around the clock, which is more than
  Actions is meant for. GitHub may throttle or disable it; the same script runs
  anywhere with `./watch_iphone_duo.py --loop 30`.

### Running it locally

```bash
DUO_ZIP=10001 ./watch_iphone_duo.py --dry-run --verbose   # check once, send nothing
DUO_ZIP=10001 NTFY_TOPIC=your-topic ./watch_iphone_duo.py --loop 30   # keep watching
python3 -m unittest discover -s tests                     # tests
```

## License

This project is private and confidential.
