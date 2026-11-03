"""Regression tests for the PinUP Popper bridge (tools/popper_bridge/nucleo_bridge.py), no cabinet needed:

  * every table's second-screen composition (s2all): kept, written at a table's start only when it changed,
    put back as it came, never over a table's own choice, nothing for a table without a .directb2s
  * the layouts the bridge makes by itself match dmd_s2_layout (dmd_core.c)
  * a 'D' picture (the board's DMD drawn by the bridge) goes once more after a quiet second

  python -m unittest discover -s tests/tools -v
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRIDGE = os.path.join(ROOT, "tools", "popper_bridge")
sys.path.insert(0, BRIDGE)


def load():
    spec = importlib.util.spec_from_file_location("nucleo_bridge", os.path.join(BRIDGE, "nucleo_bridge.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nb = load()


class FakePopper:
    def __init__(self, root):
        self.root = os.path.join(root, "PinUPSystem")

    def b2s_for(self, gid):
        return None if gid == 9 else "C:/t/%d.directb2s" % gid

    def q(self, sql, args):
        return [{"ROM": "rom%d" % args[0]}]

    def id_for_file(self, n):
        return {"a.vpx": 1, "b.vpx": 2, "nob2s.vpx": 9}.get(n)


class EveryTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "VisualPinball", "VPinMAME"))
        open(os.path.join(self.tmp, "VisualPinball", "VPinMAME", "DmdDevice.ini"), "w").close()
        self.calls = []
        self.saved = nb.b2s_info, nb.s2_apply, nb.s2_restore, nb.log
        nb.b2s_info = lambda b2s: {"bw": 1280, "bh": 1124, "grill": 100}
        nb.s2_apply = lambda b2s, ini, rom, comp, section=None: self.calls.append(("apply", rom, comp))
        nb.s2_restore = lambda b2s, ini, rom, dmd_key=None: self.calls.append(("restore", rom))
        nb.log = lambda *a: None
        self.link = nb.Link.__new__(nb.Link)
        self.link.s2_store = os.path.join(self.tmp, "s2.json")
        self.link.s2 = [1920, 0, 1280, 1024]
        self.link.popper = FakePopper(self.tmp)

    def tearDown(self):
        nb.b2s_info, nb.s2_apply, nb.s2_restore, nb.log = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def store(self):
        with open(self.link.s2_store, encoding="utf-8") as f:
            return json.load(f)

    def test_nothing_chosen_touches_nothing(self):
        self.link.s2_on_start(["a.vpx"])
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(self.link.s2_store))

    def test_backglass_only(self):
        self.assertEqual(self.link.set_s2_all({"mode": 1}), (True, ""))
        self.assertFalse(self.link.set_s2_all({"mode": 5})[0])
        self.link.s2_on_start(["not a table", "a.vpx"])   # the first reading that names a table
        kind, rom, comp = self.calls[-1]
        self.assertEqual((kind, rom), ("apply", "rom1"))
        self.assertEqual(comp["bg"], [0, 0, 1280, 1024])   # 1280x1024 without its grill: the whole screen
        self.assertIsNone(comp["vdmd"])                     # the DMD only on the board
        self.assertFalse(comp["grill"])
        self.assertEqual((comp["x0"], comp["y0"]), (1920, 0))
        self.assertEqual(self.store()["auto"], {"1": 1})
        n = len(self.calls)
        self.link.s2_on_start(["a.vpx"])
        self.assertEqual(len(self.calls), n, "written again although nothing changed")

    def test_own_choice_kept_and_given_back(self):
        self.link.set_s2_all({"mode": 1})
        self.assertEqual(self.link.apply_s2({"id": 2, "mode": 0}), (True, ""))
        n = len(self.calls)
        self.link.s2_on_start(["b.vpx"])
        self.assertEqual(len(self.calls), n, "a table's own choice overwritten")
        self.assertEqual(self.link.apply_s2({"id": 2, "follow": True}), (True, ""))
        self.assertEqual(self.calls[-1][:2], ("apply", "rom2"))
        self.assertNotIn("2", self.store())
        self.assertEqual(self.store()["auto"]["2"], 1)
        self.link.apply_s2({"id": 2, "mode": 1, "bg": [0, 0, 1280, 1024], "dmd": None})
        self.assertEqual(self.store()["2"], {"mode": 1, "dmd": False})
        self.assertNotIn("2", self.store()["auto"])

    def test_backglass_above_dmd(self):
        self.link.set_s2_all({"mode": 2})
        self.link.s2_on_start(["a.vpx"])
        comp = self.calls[-1][2]
        bg, dmd = comp["bg"], comp["vdmd"]
        self.assertEqual(dmd[2:], [1280, 320])          # a 4:1 DMD the whole width
        self.assertEqual(bg[1] + bg[3], dmd[1])         # right under the backglass
        self.assertTrue(self.link.vdmd_wanted(1))
        self.assertFalse(self.link.vdmd_wanted(2))

    def test_as_it_came_restores_once(self):
        self.link.set_s2_all({"mode": 1})
        self.link.s2_on_start(["a.vpx"])
        self.link.set_s2_all({"mode": 0})
        self.link.s2_on_start(["a.vpx"])
        self.assertEqual(self.calls[-1], ("restore", "rom1"))
        self.assertNotIn("1", self.store()["auto"])
        n = len(self.calls)
        self.link.s2_on_start(["a.vpx"])
        self.assertEqual(len(self.calls), n)

    def test_no_directb2s(self):
        self.link.set_s2_all({"mode": 1})
        self.assertEqual(self.link.s2_follow(9), (True, ""))
        self.link.s2_on_start(["nob2s.vpx"])
        self.assertEqual(self.calls, [])


class Layout(unittest.TestCase):
    def test_as_dmd_core(self):
        info = {"bw": 3000, "bh": 2915, "grill": 820}   # TMNT: 3000x2095 without its grill, 13% short of 1280x1024
        self.assertEqual(nb.s2_layout(1, info, 1280, 1024)["bg"], [0, 0, 1280, 1024])   # within 16%: the screen
        wide = {"bw": 3000, "bh": 1500, "grill": 0}       # far wider than the screen: full width, centred
        self.assertEqual(nb.s2_layout(1, wide, 1280, 1024)["bg"], [0, 192, 1280, 640])
        info = {"bw": 3000, "bh": 2915, "grill": 820}
        self.assertIsNone(nb.s2_layout(1, {"bw": 0, "bh": 0, "grill": 0}, 1280, 1024))
        self.assertIsNone(nb.s2_layout(3, info, 1280, 1024))
        # within DMD_S2_STRETCH: the whole screen
        self.assertEqual(nb.s2_fit(1280, 960, [0, 0, 1280, 1024], 16), [0, 0, 1280, 1024])


class DAgain(unittest.TestCase):
    def test_once_after_a_quiet_second(self):
        sent = []
        link = nb.Link.__new__(nb.Link)
        link.d_last, link.d_again = None, 0.0
        link.send = lambda t, p, wait=True: sent.append((t, p)) or True
        self.assertTrue(link.send_d(b"one"))
        link.d_tick()
        self.assertEqual(len(sent), 1, "sent again before its second")
        link.d_again = time.time() - 0.01
        link.d_tick()
        link.d_tick()
        self.assertEqual(sent, [("D", b"one"), ("D", b"one")])


if __name__ == "__main__":
    unittest.main()
