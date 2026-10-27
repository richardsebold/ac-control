import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import watch_core as wc

ZONE = {"name": "Portão", "points": [[0.4, 0.5], [0.9, 0.5], [0.9, 1.0], [0.4, 1.0]],
        "kinds": ["vehicle", "person"], "seconds": 5}
CAR_IN = (0.5, 0.5, 0.7, 0.8)


def car(box=CAR_IN):
    return wc.Det(box, wc.VEHICLE)


def run(w, dets_at, t0, t1, step=0.5):
    out, t = [], t0
    while t <= t1:
        out += w.update(dets_at(t), t)
        t += step
    return out


class GeometryTest(unittest.TestCase):
    def test_polygon_and_iou(self):
        sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.assertTrue(wc.in_polygon((0.5, 0.5), sq))
        self.assertFalse(wc.in_polygon((1.5, 0.5), sq))
        self.assertAlmostEqual(wc.iou((0, 0, 1, 1), (0, 0, 1, 1)), 1.0)
        self.assertEqual(wc.iou((0, 0, 1, 1), (2, 2, 3, 3)), 0.0)


class DwellTest(unittest.TestCase):
    def watcher(self, zone=ZONE):
        return wc.ZoneWatcher("cam4", [zone], 0.0)

    def test_alerts_once_after_dwell(self):
        w = self.watcher()
        alerts = run(w, lambda t: [car()], wc.BASELINE + 1, wc.BASELINE + 40)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].zone, "Portão")
        self.assertGreaterEqual(alerts[0].seconds, 5)

    def test_no_alert_before_dwell(self):
        w = self.watcher()
        self.assertEqual(run(w, lambda t: [car()], wc.BASELINE + 1, wc.BASELINE + 4), [])

    def test_baseline_car_ignored_while_it_stays(self):
        w = self.watcher()
        self.assertEqual(run(w, lambda t: [car()], 0, 120), [])

    def test_baseline_car_ignored_until_it_leaves_then_returns(self):
        w = self.watcher()
        run(w, lambda t: [car()], 0, 30)
        run(w, lambda t: [], 30.5, 60)
        alerts = run(w, lambda t: [car()], 60.5, 80)
        self.assertEqual(len(alerts), 1)

    def test_passing_car_does_not_alert(self):
        w = self.watcher()
        t0 = wc.BASELINE + 1

        def passing(t):
            x = 0.2 + (t - t0) * 0.1
            return [car((x, 0.5, x + 0.2, 0.8))]
        self.assertEqual(run(w, passing, t0, t0 + 6), [])

    def test_outside_zone_ignored(self):
        w = self.watcher()
        far = car((0.0, 0.1, 0.2, 0.3))
        self.assertEqual(run(w, lambda t: [far], wc.BASELINE + 1, wc.BASELINE + 40), [])

    def test_person_needs_zone_kind(self):
        w = self.watcher({**ZONE, "kinds": ["vehicle"]})
        p = wc.Det(CAR_IN, wc.PERSON)
        self.assertEqual(run(w, lambda t: [p], wc.BASELINE + 1, wc.BASELINE + 40), [])
        w = self.watcher()
        self.assertEqual(len(run(w, lambda t: [p], wc.BASELINE + 1, wc.BASELINE + 40)), 1)

    def test_survives_missed_detections(self):
        w = self.watcher()
        t0 = wc.BASELINE + 1
        alerts = run(w, lambda t: [] if 3 < t - t0 < 4.5 else [car()], t0, t0 + 20)
        self.assertEqual(len(alerts), 1)

    def test_car_that_moved_after_baseline_then_stops_alerts(self):
        w = self.watcher()
        run(w, lambda t: [car((0.5, 0.5, 0.7, 0.8))], 0, 13)
        run(w, lambda t: [car((0.62, 0.52, 0.82, 0.82))], 13.5, 14)
        alerts = run(w, lambda t: [car((0.62, 0.52, 0.82, 0.82))], 14.5, 30)
        self.assertEqual(len(alerts), 1)


class ConfigTest(unittest.TestCase):
    def test_roundtrip_and_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "zones.json"
            self.assertFalse(wc.load_zones(p)["enabled"])
            wc.save_zones({"enabled": True, "cameras": {"cam4": {"zones": [ZONE]}}}, p)
            self.assertEqual(wc.load_zones(p)["cameras"]["cam4"]["zones"][0]["name"], "Portão")


if __name__ == "__main__":
    unittest.main()
