import queue
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import alarm_core as ac


def hello(model=0xA3, parts=(0x01, 0x01)):
    f = bytearray(102)
    f[0], f[1] = ac.SOF, 102
    f[41] = model
    for i, p in enumerate(parts):
        f[85 + i] = p
    return bytes(f)


def status(parts):
    f = bytearray(118)
    f[0], f[1] = ac.SOF, 118
    for i, p in enumerate(parts):
        f[14 + i] = p
    return bytes(f)


def event(code):
    f = bytearray(24)
    f[0], f[1] = ac.SOF, 24
    f[8:12] = code.encode()
    f[17:21] = b"0001"
    return bytes(f)


class FrameTest(unittest.TestCase):
    def test_matches_reference_bytes(self):
        # why: o checksum de referência (0x32) foi calculado à mão a partir do XOR de 7B 06 01 4F 01
        self.assertEqual(ac.frame(0x01, 0x4F, 0x01), b"\x7b\x06\x01\x4f\x01\x32")
        self.assertEqual(len(ac.STATUS_REQUEST), 5)
        self.assertEqual(len(ac.frame(0x01, 0x21, 0x01, 0x01)), 7)

    def test_split_glued_frames(self):
        a, b = ac.frame(0x01, 0x40, 0x01), ac.STATUS_REQUEST
        self.assertEqual(ac.split_frames(a + b), [a, b])
        self.assertEqual(ac.split_frames(b"\x01\x02\x03"), [b"\x01\x02\x03"])

    def test_summarize(self):
        s = ac.summarize
        self.assertEqual(s({}), "unknown")
        self.assertEqual(s({1: "armed_away", 2: "armed_away"}), "armed_away")
        self.assertEqual(s({1: "armed_away", 2: "disarmed"}), "partial")
        self.assertEqual(s({1: "armed_home", 2: "triggered"}), "triggered")


class HubTest(unittest.TestCase):
    def setUp(self):
        self.changes = queue.Queue()
        cfg = {"bind": "127.0.0.1", "port": 0, "panel_ip": "127.0.0.1", "partitions": [1, 2]}
        self.hub = ac.AlarmHub(cfg, lambda: self.changes.put(self.hub.state))
        self.hub.start()
        self.panel = socket.create_connection(("127.0.0.1", self.hub.port))
        self.panel.settimeout(3)

    def tearDown(self):
        self.panel.close()
        self.hub.stop()

    def wait_state(self, want):
        end = time.time() + 3
        while time.time() < end and self.hub.state != want:
            time.sleep(0.02)
        self.assertEqual(self.hub.state, want)

    def read_frames(self, n):
        buf = b""
        while len(buf) < n:
            buf += self.panel.recv(256)
        return buf

    def test_handshake_and_arm_disarm(self):
        self.panel.sendall(hello())
        want = ac.frame(0x01, 0x21, 0x01, 0x01) + ac.STATUS_REQUEST
        self.assertEqual(self.read_frames(len(want)), want)
        self.assertEqual(self.hub.model, "Active 20 Ethernet")
        self.wait_state("disarmed")

        self.assertTrue(self.hub.arm_away())
        want = ac.frame(1, ac.CMD_AWAY, 1) + ac.frame(1, ac.CMD_AWAY, 2) + ac.STATUS_REQUEST
        self.assertEqual(self.read_frames(len(want)), want)

        self.panel.sendall(status([0x02, 0x02, 0, 0]))
        self.wait_state("armed_away")
        self.panel.sendall(status([0x03, 0x03, 0, 0]))
        self.wait_state("armed_home")
        self.panel.sendall(status([0x81, 0x03, 0, 0]))
        self.wait_state("triggered")

    def test_event_ack_and_state(self):
        self.panel.sendall(event("3401"))
        want = ac.frame(0x01, 0x24, 0x01, *b"0001")
        self.assertEqual(self.read_frames(len(want)), want)
        self.wait_state("armed_away")
        self.panel.sendall(event("1401"))
        self.read_frames(len(want))
        self.wait_state("disarmed")

    def test_keepalive_reply(self):
        self.panel.sendall(b"\x7b\x05\x02\x4d\x35")
        want = ac.frame(0x01, 0x40, 0x01)
        self.assertEqual(self.read_frames(len(want)), want)

    def test_disconnect_clears_state(self):
        self.panel.sendall(status([0x02, 0x02, 0, 0]))
        self.wait_state("armed_away")
        self.panel.close()
        self.wait_state("unknown")
        self.assertFalse(self.hub.command(ac.CMD_DISARM))

    def test_wrong_peer_rejected(self):
        self.hub.cfg["panel_ip"] = "10.255.255.1"
        self.panel.close()
        time.sleep(1.2)
        p = socket.create_connection(("127.0.0.1", self.hub.port))
        p.settimeout(2)
        self.assertEqual(p.recv(16), b"")
        self.assertFalse(self.hub.connected)
        p.close()


if __name__ == "__main__":
    unittest.main()
