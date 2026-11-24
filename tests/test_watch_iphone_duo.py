import argparse
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import watch_iphone_duo as w  # noqa: E402

NIGHT_256, WHITE_256 = "MK1F4LL/A", "MK1E4LL/A"


def store(number, name, distance, statuses):
    return {
        "storeNumber": number,
        "storeName": name,
        "city": "Testville",
        "storedistance": distance,
        "partsAvailability": {
            part: {
                "pickupDisplay": status,
                "pickupSearchQuote": "Available Today"
                if status == "available"
                else "Currently unavailable",
            }
            for part, status in statuses.items()
        },
    }


def payload(*stores):
    return {"head": {"status": "200"}, "body": {"stores": list(stores)}}


def args(**overrides):
    values = {"dry_run": False, "verbose": False, "test_notify": False}
    values.update(overrides)
    return argparse.Namespace(**values)


class ParseTests(unittest.TestCase):
    parts = [NIGHT_256, WHITE_256]

    def test_only_available_counts_as_in_stock(self):
        data = payload(
            store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}),
            store("R2", "Other", 9.0, {NIGHT_256: "ineligible", WHITE_256: "unavailable"}),
        )
        hits, in_range = w.parse_availability(data, self.parts, 50)
        self.assertEqual(in_range, 2)
        self.assertEqual([(h.store_number, h.part) for h in hits], [("R1", NIGHT_256)])
        self.assertEqual(hits[0].config, "256GB Night Sky")

    def test_stores_beyond_max_miles_are_ignored(self):
        data = payload(
            store("R1", "Near", 2.0, {NIGHT_256: "unavailable", WHITE_256: "unavailable"}),
            store("R2", "Far", 80.0, {NIGHT_256: "available", WHITE_256: "available"}),
        )
        hits, in_range = w.parse_availability(data, self.parts, 50)
        self.assertEqual((hits, in_range), ([], 1))

    def test_apple_error_message_fails_the_check(self):
        data = {"body": {"errorMessage": "Please enter a valid city, state or zip code."}}
        with self.assertRaisesRegex(w.CheckError, "valid city"):
            w.parse_availability(data, self.parts, 50)

    def test_unexpected_shapes_fail_the_check(self):
        for data in ({}, {"body": {}}, {"body": {"stores": []}}):
            with self.assertRaises(w.CheckError):
                w.parse_availability(data, self.parts, 50)
        missing_part = payload(store("R1", "Near", 2.0, {NIGHT_256: "unavailable"}))
        with self.assertRaisesRegex(w.CheckError, WHITE_256):
            w.parse_availability(missing_part, self.parts, 50)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = w.read_config({"DUO_ZIP": "10001", "NTFY_TOPIC": "t"}, need_topic=True)
        self.assertEqual(config["parts"], list(w.PARTS))
        self.assertEqual(config["max_miles"], 50)
        self.assertEqual(config["server"], "https://ntfy.sh")

    def test_rejects_missing_or_bad_values(self):
        bad = [
            {},
            {"DUO_ZIP": "10001"},
            {"DUO_ZIP": "10001", "NTFY_TOPIC": "t", "DUO_PARTS": "NOPE1LL/A"},
            {"DUO_ZIP": "10001", "NTFY_TOPIC": "t", "DUO_MAX_MILES": "far"},
        ]
        for env in bad:
            with self.assertRaises(w.ConfigError):
                w.read_config(env, need_topic=True)

    def test_url_carries_location_and_every_part(self):
        url = w.build_url("10001", [NIGHT_256, WHITE_256])
        self.assertIn("location=10001", url)
        self.assertIn(f"parts.0={NIGHT_256}", url)
        self.assertIn(f"parts.1={WHITE_256}", url)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {
            "DUO_ZIP": "10001",
            "NTFY_TOPIC": "secret-topic",
            "DUO_PARTS": f"{NIGHT_256},{WHITE_256}",
            "DUO_STATE_FILE": os.path.join(self.tmp.name, "state.json"),
        }

    def run_with(self, data, **arg_overrides):
        with mock.patch.object(w, "fetch", return_value=data), \
                mock.patch.object(w, "send_ntfy") as send:
            code = w.run(args(**arg_overrides), self.env)
        return code, send

    def test_alerts_once_then_again_only_after_a_restock(self):
        none = payload(store("R1", "Near", 2.0, {NIGHT_256: "unavailable", WHITE_256: "unavailable"}))
        one = payload(store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}))
        two = payload(store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "available"}))

        self.assertEqual(self.run_with(none)[1].call_count, 0)

        _, send = self.run_with(one)
        title, body = send.call_args.args[2:]
        self.assertEqual(title, "iPhone Duo in stock: Apple Near")
        self.assertIn("256GB Night Sky", body)

        self.assertEqual(self.run_with(one)[1].call_count, 0, "same stock, no repeat")

        _, send = self.run_with(two)
        self.assertIn("256GB Star White", send.call_args.args[3])
        self.assertNotIn("Night Sky", send.call_args.args[3], "only the new one")

        self.assertEqual(self.run_with(none)[1].call_count, 0)
        self.assertEqual(self.run_with(one)[1].call_count, 1, "restock alerts again")

    def test_failed_push_is_retried_on_the_next_run(self):
        one = payload(store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}))
        with mock.patch.object(w, "fetch", return_value=one), \
                mock.patch.object(w, "send_ntfy", side_effect=w.NotifyError("down")):
            with self.assertRaises(w.NotifyError):
                w.run(args(), self.env)
        self.assertEqual(self.run_with(one)[1].call_count, 1)

    def test_dry_run_sends_nothing_and_saves_nothing(self):
        one = payload(store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}))
        code, send = self.run_with(one, dry_run=True)
        self.assertEqual((code, send.call_count), (0, 0))
        self.assertFalse(os.path.exists(self.env["DUO_STATE_FILE"]))

    def test_state_file_names_no_store_or_part(self):
        one = payload(store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}))
        self.run_with(one)
        with open(self.env["DUO_STATE_FILE"], encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(len(json.loads(text)["available"]), 1)
        for leak in ("R1", "Near", "MK1F4", "10001"):
            self.assertNotIn(leak, text)

    def test_no_store_in_range_is_a_configuration_error(self):
        far = payload(store("R2", "Far", 80.0, {NIGHT_256: "available", WHITE_256: "available"}))
        with mock.patch.object(w, "fetch", return_value=far):
            with self.assertRaises(w.ConfigError):
                w.run(args(), self.env)

    def test_main_maps_failures_to_exit_codes(self):
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(w, "fetch", side_effect=w.CheckError("HTTP 541")):
            self.assertEqual(w.main([]), w.EXIT_CHECK_FAILED)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(w.main([]), w.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main()
