import argparse
import json
import os
import random
import sys
import tempfile
import unittest
import urllib.parse
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


class FakeApple:
    """Answers like Apple: the 12 stores nearest a location or another store."""

    def __init__(self, origin, positions, in_stock=()):
        self.origin = origin
        self.positions = positions  # store number -> (latitude, longitude)
        self.in_stock = set(in_stock)
        self.queries = 0

    def fetch(self, url):
        self.queries += 1
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if "store" in query and query["store"][0] not in self.positions:
            return {"body": {"errorMessage": "There is no store associated with this search."}}
        centre = self.positions[query["store"][0]] if "store" in query else self.origin
        nearest = sorted(
            (round(w.miles_between(centre, position), 2), number)
            for number, position in self.positions.items()
        )[: w.PAGE_SIZE]
        listed = []
        for distance, number in nearest:
            status = "available" if number in self.in_stock else "unavailable"
            item = store(number, f"Store {number}", distance, {NIGHT_256: status})
            item["storelatitude"], item["storelongitude"] = self.positions[number]
            listed.append(item)
        return payload(*listed)


class ParseTests(unittest.TestCase):
    parts = [NIGHT_256, WHITE_256]

    def survey(self, data, max_miles=100):
        with mock.patch.object(w, "fetch", return_value=data):
            return w.survey("10001", self.parts, max_miles)

    def test_only_available_counts_as_in_stock(self):
        data = payload(
            store("R1", "Near", 2.0, {NIGHT_256: "available", WHITE_256: "unavailable"}),
            store("R2", "Other", 9.0, {NIGHT_256: "ineligible", WHITE_256: "unavailable"}),
        )
        hits, in_range, queries = self.survey(data)
        self.assertEqual((in_range, queries), (2, 1))
        self.assertEqual([(h.store_number, h.part) for h in hits], [("R1", NIGHT_256)])
        self.assertEqual(hits[0].config, "256GB Night Sky")

    def test_stores_beyond_max_miles_are_ignored(self):
        data = payload(
            store("R1", "Near", 2.0, {NIGHT_256: "unavailable", WHITE_256: "unavailable"}),
            store("R2", "Far", 80.0, {NIGHT_256: "available", WHITE_256: "available"}),
        )
        hits, in_range, _ = self.survey(data, max_miles=50)
        self.assertEqual((hits, in_range), ([], 1))

    def test_apple_error_message_fails_the_check(self):
        data = {"body": {"errorMessage": "Please enter a valid city, state or zip code."}}
        with self.assertRaisesRegex(w.CheckError, "valid city"):
            w.parse_stores(data, self.parts)

    def test_unexpected_shapes_fail_the_check(self):
        for data in ({}, {"body": {}}, {"body": {"stores": []}}):
            with self.assertRaises(w.CheckError):
                w.parse_stores(data, self.parts)
        missing_part = payload(store("R1", "Near", 2.0, {NIGHT_256: "unavailable"}))
        with self.assertRaisesRegex(w.CheckError, WHITE_256):
            w.parse_stores(missing_part, self.parts)


class WiderSearchTests(unittest.TestCase):
    """Apple lists only 12 stores per query; the rest of the radius must still be checked."""

    origin = (40.75, -74.0)

    def region(self):
        # A city dense enough that every city store's 12 nearest are other city
        # stores, with the remaining stores scattered far outside it.
        rng = random.Random(7)
        spots = [(rng.uniform(0, 10), rng.uniform(0, 6.28)) for _ in range(25)]  # city
        spots += [(rng.uniform(20, 95), rng.uniform(0, 6.28)) for _ in range(20)]  # suburbs
        spots += [(rng.uniform(110, 160), rng.uniform(0, 6.28)) for _ in range(10)]  # too far
        return {
            f"R{i:03d}": w.step(self.origin, miles, bearing)
            for i, (miles, bearing) in enumerate(spots)
        }

    def miles(self, position):
        return w.miles_between(self.origin, position)

    def survey(self, apple, table, max_miles=100):
        with mock.patch.object(w, "fetch", side_effect=apple.fetch), \
                mock.patch.object(w, "load_store_table", return_value=dict(table)) as load:
            result = w.survey("10001", [NIGHT_256], max_miles, pause=0)
        return result, load

    def test_checks_every_store_in_range_not_just_the_nearest_twelve(self):
        positions = self.region()
        in_range = {n for n, p in positions.items() if self.miles(p) <= 100}
        farthest = max(in_range, key=lambda n: self.miles(positions[n]))
        outside = next(n for n in positions if n not in in_range)
        apple = FakeApple(self.origin, positions, in_stock={farthest, outside})

        (hits, count, queries), _ = self.survey(apple, positions)

        self.assertGreater(len(in_range), w.PAGE_SIZE)
        self.assertEqual(count, len(in_range))
        self.assertEqual([h.store_number for h in hits], [farthest])
        self.assertAlmostEqual(hits[0].distance, self.miles(positions[farthest]), delta=0.5)
        self.assertEqual(queries, apple.queries)
        self.assertLess(queries, len(in_range) / 2, "far fewer queries than stores")

    def test_one_query_is_enough_when_the_first_list_reaches_the_radius(self):
        positions = self.region()
        twelfth = sorted(self.miles(p) for p in positions.values())[w.PAGE_SIZE - 1]
        apple = FakeApple(self.origin, positions)
        (_, count, queries), load = self.survey(apple, positions, max_miles=twelfth - 0.5)
        self.assertEqual((queries, count), (1, w.PAGE_SIZE - 1))
        load.assert_not_called()

    def test_table_and_apple_may_disagree_about_a_few_stores(self):
        table = self.region()
        positions = dict(table)
        suburbs = sorted((n for n, p in table.items() if 20 <= self.miles(p) <= 80),
                         key=lambda n: self.miles(table[n]))
        # Opened since the table was built, next to a store the table does know.
        positions["R800"] = w.step(table[suburbs[len(suburbs) // 2]], 1, 0.0)
        # Closed since the table was built: Apple no longer knows it.
        table["R900"] = w.step(self.origin, 50, 1.0)
        in_range = {n for n, p in positions.items() if self.miles(p) <= 100}
        apple = FakeApple(self.origin, positions, in_stock={"R800"})

        (hits, count, _), _ = self.survey(apple, table)

        self.assertIn("R800", in_range)
        self.assertEqual(count, len(in_range))
        self.assertEqual([h.store_number for h in hits], ["R800"])

    def test_many_unknown_stores_fail_the_check(self):
        positions = self.region()
        table = dict(positions)
        for i in range(5):
            table[f"R90{i}"] = w.step(self.origin, 40 + i, 1.0)
        with self.assertRaises(w.CheckError):
            self.survey(FakeApple(self.origin, positions), table)

    def test_a_runaway_search_fails_instead_of_continuing(self):
        positions = self.region()
        with mock.patch.object(w, "MAX_QUERIES", 2):
            with self.assertRaisesRegex(w.CheckError, "did not finish"):
                self.survey(FakeApple(self.origin, positions), positions)

    def test_shipped_store_table_is_usable(self):
        table = w.load_store_table()
        self.assertGreater(len(table), 200)
        for number, (latitude, longitude) in table.items():
            self.assertRegex(number, r"^R\d{3}$")
            self.assertTrue(18 < latitude < 72 and -170 < longitude < -60, number)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = w.read_config({"DUO_ZIP": "10001", "NTFY_TOPIC": "t"}, need_topic=True)
        self.assertEqual(config["parts"], list(w.PARTS))
        self.assertEqual(config["max_miles"], 100)
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
        url = w.build_url([NIGHT_256, WHITE_256], location="10001")
        self.assertIn("location=10001", url)
        self.assertIn(f"parts.0={NIGHT_256}", url)
        self.assertIn(f"parts.1={WHITE_256}", url)

    def test_url_can_ask_around_a_store_instead(self):
        url = w.build_url([NIGHT_256], store="R095")
        self.assertIn("store=R095", url)
        self.assertIn("searchNearby=true", url)
        self.assertNotIn("location=", url)


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
        far = payload(store("R2", "Far", 180.0, {NIGHT_256: "available", WHITE_256: "available"}))
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
