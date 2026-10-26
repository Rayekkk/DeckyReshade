# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Reading the RenoDX wiki's mod list, matching games and checking downloads."""

import os
import tempfile
import unittest
from unittest import mock

import _harness  # noqa: F401
import reshade_net
import reshade_renodx as X
from _pe import make_pe

SNAP = "[![Snapshot](https://img.shields.io/github/last-commit/x/renodx?path=src&label=Snapshot)]"
NEXUS = "[![Nexus Mods](https://img.shields.io/static/v1?label=Nexus)](https://www.nexusmods.com/game/mods/1)"
# The wiki's layout, trimmed: legend, the main list, then multi-game mods that are not read.
WIKI = f"""# Installation
Install ReShade with add-on support.

# List

### Legend

:white_check_mark:: Working, Playable

| Name | Maintainer | Links | Status |
| :--- | :--- | :--- | :---: |
| God of War (2018) | Ritsu | {SNAP}(https://clshortfuse.github.io/renodx/renodx-godofwar.addon64) | :white_check_mark: |
| [Hollow Knight](https://github.com/clshortfuse/renodx/discussions/230) | Voosh | {NEXUS} &middot; {SNAP}(https://notvoosh.github.io/renodx/renodx-hollowknight.addon64) | [:construction:](# "Currently broken") |
| Dishonored | Oopy | {SNAP}(https://oopydoopy.github.io/renodx/renodx-dishonored.addon32) &middot; {SNAP}(https://oopydoopy.github.io/renodx/renodx-dishonored.addon64) | :white_check_mark: |
| A Plague Tale: Requiem | Someone | {NEXUS} | ✅ |
| Shady | Mallory | {SNAP}(https://evil.example.com/renodx-shady.addon64) | 🚧 |
| Old Game | Nobody | {SNAP}(https://github.com/x/renodx/releases/download/snapshot/renodx-old.addon64) | Superseded by Generic Unity mod |

## Multi-Game Mods

| Some Unity Game | x | {SNAP}(https://notvoosh.github.io/renodx-unity/renodx-unityengine.addon64) | :white_check_mark: |
"""


class Parse(unittest.TestCase):
    def setUp(self):
        self.mods = {m["name"]: m for m in X.parse(WIKI)}

    def test_main_list_only(self):
        self.assertEqual(list(self.mods), ["God of War (2018)", "Hollow Knight", "Dishonored",
                                           "A Plague Tale: Requiem", "Shady", "Old Game"])

    def test_status_note_files_and_page(self):
        gow, hk, dis, apt, shady, old = self.mods.values()
        self.assertEqual((gow["status"], gow["files"]),
                         ("working", {"64": "https://clshortfuse.github.io/renodx/renodx-godofwar.addon64"}))
        self.assertEqual((hk["status"], hk["note"], hk["maintainer"]), ("wip", "Currently broken", "Voosh"))
        self.assertEqual(sorted(dis["files"]), ["32", "64"])
        self.assertEqual((apt["status"], apt["files"], apt["page"]),
                         ("working", {}, "https://www.nexusmods.com/game/mods/1"))  # by hand only
        self.assertEqual((shady["status"], shady["files"]), ("wip", {}))  # not an author's host: never downloaded
        self.assertEqual((old["status"], old["note"]), ("other", "Superseded by Generic Unity mod"))
        self.assertTrue(old["files"])  # GitHub releases are trusted

    def test_unreadable_page(self):
        self.assertRaises(X.RenoDXError, X.parse, "<html>moved</html>")
        self.assertRaises(X.RenoDXError, X.parse, "# List\n\nnothing here\n")

    def test_match(self):
        mods = list(self.mods.values())
        cases = {"God of War": "God of War (2018)", "Hollow Knight™": "Hollow Knight", "DISHONORED": "Dishonored",
                 "Dishonored 2": None, "God of War Ragnarök": None}
        for game, want in cases.items():
            found = X.match(game, mods)
            self.assertEqual(found and found["name"], want, game)


class Download(unittest.TestCase):
    def serve(self, data):
        def download(url, dest, limit, sha256=None, progress=None):
            with open(dest, "wb") as f:
                f.write(data)
        return mock.patch.object(reshade_net, "download", download)

    def test_bitness_is_checked(self):
        mods = {m["name"]: m for m in X.parse(WIKI)}
        folder = tempfile.mkdtemp()
        with self.serve(make_pe(64)):
            path = X.download(mods["God of War (2018)"], 64, folder)
        self.assertEqual(os.path.basename(path), "renodx-godofwar.addon64")
        with self.serve(make_pe(32)):
            self.assertRaises(X.RenoDXError, X.download, mods["God of War (2018)"], 64, folder)  # wrong file
        self.assertRaises(X.RenoDXError, X.download, mods["God of War (2018)"], 32, folder)  # no 32-bit build
        self.assertRaises(X.RenoDXError, X.download, mods["A Plague Tale: Requiem"], 64, folder)
        self.assertEqual(os.listdir(folder), ["renodx-godofwar.addon64"])


if __name__ == "__main__":
    unittest.main()
