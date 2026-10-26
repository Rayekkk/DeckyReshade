# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Reading ReShade's log, log tails and the report."""

import os
import tempfile
import unittest

import _harness  # noqa: F401
import reshade_diag as D

SAMPLE = """\
2026-10-26 17:00:00:001 [ 4242] | INFO  | Initializing crosire's ReShade version '6.8.0.2073' (64-bit) loaded from "Z:\\g\\dxgi.dll".
2026-10-26 17:00:00:100 [ 4242] | WARN  | Failed to load "Z:\\g\\d3dcompiler_47.dll" with error code 126, using builtin.
2026-10-26 17:00:01:000 [ 4242] | ERROR | Failed to compile "Z:\\s\\Shaders\\Broken.fx":
a line without the separators
2026-10-26 17:00:01:001 [ 4242] | ERROR | Failed to compile "Z:\\s\\Shaders\\Broken.fx":
2026-10-26 17:00:02:000 [ 4242] | ERROR | Failed to create effect runtime.
"""


class ReshadeLog(unittest.TestCase):
    def test_summary(self):
        folder = tempfile.mkdtemp()
        self.assertEqual(D.reshade_log(folder)["found"], False)
        with open(os.path.join(folder, D.LOG), "w", encoding="utf-8") as f:
            f.write(SAMPLE)
        summary = D.reshade_log(folder)
        self.assertTrue(summary["found"] and summary["modified"])
        self.assertEqual(summary["version"], "6.8.0")
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["errors"], ['Failed to compile "Z:\\s\\Shaders\\Broken.fx":',
                                             "Failed to create effect runtime."])

    def test_tail_and_report(self):
        path = os.path.join(tempfile.mkdtemp(), "plugin.log")
        with open(path, "w") as f:
            f.write("\n".join(f"line {i}" for i in range(500)))
        self.assertEqual(D.tail(path, 2), "line 498\nline 499")
        self.assertEqual(D.tail(path + ".missing"), "")
        text = D.report([("Plugin", "0.1.0")], [("Game", {"api": "dxgi"}, "")], "tail")
        for part in ("Plugin: 0.1.0", "== Game", "api: dxgi", "(none)", "== Plugin log (end)", "tail"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
