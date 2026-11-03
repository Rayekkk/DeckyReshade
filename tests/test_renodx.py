# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Reading the RenoDX wiki's mod list, matching games and checking downloads."""

import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

import _harness  # noqa: F401
import dk_net
import reshade_renodx as X
from _pe import make_pe

SNAP = "[![Snapshot](https://img.shields.io/github/last-commit/x/renodx?path=src&label=Snapshot)]"
NEXUS = "[![Nexus Mods](https://img.shields.io/static/v1?label=Nexus)](https://www.nexusmods.com/game/mods/1)"
# The wiki's layout, trimmed: legend, the main list, then the engine-wide mods with their own per-game tables.
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

### Unreal Engine Extended {SNAP}(https://marat569.github.io/renodx/renodx-ue-extended.addon64)

> **Set `Upgrade Path: Off` before editing Engine.ini.**

| Name | Status | Notes |
| :--- | :---: | :--- |
| ABZÛ | :white_check_mark: | Upgrade Path: On <br> `B8G8R8A8_TYPELESS` `Output Size` |
| Bodycam | :white_check_mark: | Engine.ini |
| A Way Out | :construction: | Upgrade Path: On. Lacks testing.
| A Plague Tale: Requiem | :white_check_mark: | Native HDR |
| Black Myth: Wukong | :white_check_mark: | Engine.ini, Only add `r.HDR.EnableHDROutput=1` to Engine.ini. |
| Hi-Fi Rush | :white_check_mark: | Upgrade Path: On as Engine.ini edits overexposed the shading. |
| Chromatic Conundrum | :white_check_mark: | Upgrade Path: Off. Broken rendering when enabled. |

 ### Unreal Engine {SNAP}(https://clshortfuse.github.io/renodx/renodx-unrealengine.addon64)

| Name | Status | Notes |
| :--- | :---: | :--- |
| ABZÛ | :white_check_mark: | |
| Bodycam | :white_check_mark: | `R10G10B10A2_UNORM` `Output Size` |
| Hogwarts Legacy | :white_check_mark: | Needs a build from the [Discord](https://discord.gg/x) |

### Unity Engine
64-bit: {SNAP}(https://notvoosh.github.io/renodx-unity/renodx-unityengine.addon64) | 32-bit: {SNAP}(https://notvoosh.github.io/renodx-unity/renodx-unityengine.addon32)

| Name | Status | Notes |
| :--- | :---: | :--- |
| Old Game | :white_check_mark: | Use DX11 |
| Hollow Knight | :white_check_mark: | |

### Source Engine
64-bit: {SNAP}(https://github.com/CommandGenius/renodx/releases/download/snapshot/renodx-sourceengine.addon64)

| Name | Status | Notes |
| :--- | :---: | :--- |
| Portal 2 | :white_check_mark: | Needs a DXVK proxy |

### Someone's Engine {SNAP}(https://evil.example.com/renodx-anything.addon64)

| Name | Status | Notes |
| :--- | :---: | :--- |
| Dishonored | :white_check_mark: | |

# Related Mods

| Not A Game | x | {SNAP}(https://notvoosh.github.io/renodx/renodx-other.addon64) | :white_check_mark: |
"""


class Parse(unittest.TestCase):
    def setUp(self):
        self.mods = {m["name"]: m for m in X.parse(WIKI)}

    def test_main_list_then_the_engine_mods_games(self):
        self.assertEqual(list(self.mods), [
            "God of War (2018)", "Hollow Knight", "Dishonored", "A Plague Tale: Requiem", "Shady", "Old Game",
            "ABZÛ (Unreal Engine Extended)", "Bodycam (Unreal Engine Extended)", "A Way Out (Unreal Engine Extended)",
            "A Plague Tale: Requiem (Unreal Engine Extended)", "Black Myth: Wukong (Unreal Engine Extended)",
            "Hi-Fi Rush (Unreal Engine Extended)", "Chromatic Conundrum (Unreal Engine Extended)",
            "ABZÛ (Unreal Engine)", "Bodycam (Unreal Engine)",
            "Hogwarts Legacy (Unreal Engine)", "Old Game (Unity Engine)", "Hollow Knight (Unity Engine)"])

    def test_an_engine_mod_installs_only_where_its_table_asks_for_nothing_more(self):
        m = self.mods
        ue = {"64": "https://marat569.github.io/renodx/renodx-ue-extended.addon64"}
        abzu = m["ABZÛ (Unreal Engine Extended)"]
        self.assertEqual((abzu["status"], abzu["files"], abzu["maintainer"], abzu["engine"]),
                         ("working", ue, "marat569", "Unreal Engine Extended"))
        # its settings for the RenoDX menu are shown, as plain text
        self.assertEqual(abzu["note"], "Upgrade Path: On B8G8R8A8_TYPELESS Output Size")
        self.assertEqual(m["ABZÛ (Unreal Engine)"]["note"], "")
        # the Engine.ini edit the wiki spells out is done here, with Upgrade Path Off as it asks
        bodycam = m["Bodycam (Unreal Engine Extended)"]
        self.assertEqual((bodycam["files"], bodycam["engine_ini"], bodycam["settings"]),
                         (ue, X.ENGINE_INI, {"renodx": {"Set_Path": "0"}}))
        self.assertEqual(m["Black Myth: Wukong (Unreal Engine Extended)"]["engine_ini"],
                         {"SystemSettings": {"r.HDR.EnableHDROutput": "1"}}, "only what the note names")
        # a note that only mentions Engine.ini (to say it did not work) is no Engine.ini game
        hifi = m["Hi-Fi Rush (Unreal Engine Extended)"]
        self.assertEqual(("engine_ini" in hifi, "settings" in hifi, hifi["files"]), (False, False, {}))
        self.assertEqual(m["Chromatic Conundrum (Unreal Engine Extended)"]["settings"], {"renodx": {"Set_Path": "0"}})
        self.assertNotIn("engine_ini", abzu)
        self.assertEqual(m["A Way Out (Unreal Engine Extended)"]["files"], {}, "not marked working")
        self.assertEqual(m["Hogwarts Legacy (Unreal Engine)"]["files"], {}, "a build from Discord")
        self.assertEqual(m["Bodycam (Unreal Engine)"]["files"],
                         {"64": "https://clshortfuse.github.io/renodx/renodx-unrealengine.addon64"})
        self.assertEqual(sorted(m["Old Game (Unity Engine)"]["files"]), ["32", "64"])
        self.assertEqual(m["Bodycam (Unreal Engine Extended)"]["page"], X.WIKI_PAGE)

    def test_match_prefers_what_can_be_installed(self):
        mods = list(self.mods.values())
        cases = {
            "Hollow Knight": "Hollow Knight",  # its own mod, installable, over the engine one
            "Old Game": "Old Game (Unity Engine)",  # its own mod says it was superseded and has no file
            "A Plague Tale: Requiem": "A Plague Tale: Requiem (Unreal Engine Extended)",  # its own is on Nexus only
            "ABZÛ": "ABZÛ (Unreal Engine Extended)",  # both Unreal tables: the Extended rework first
            "Bodycam": "Bodycam (Unreal Engine Extended)",  # its Engine.ini is set up here
            "Hogwarts Legacy": "Hogwarts Legacy (Unreal Engine)",  # none installable: still shown, as a link
            "Portal 2": None,  # the Source Engine mod is not offered
        }
        for game, want in cases.items():
            found = X.match(game, mods)
            self.assertEqual(found and found["name"], want, game)

    def test_status_note_files_and_page(self):
        gow, hk, dis, apt, shady, old = list(self.mods.values())[:6]
        self.assertEqual((gow["status"], gow["files"]),
                         ("working", {"64": "https://clshortfuse.github.io/renodx/renodx-godofwar.addon64"}))
        self.assertEqual((hk["status"], hk["note"], hk["maintainer"]), ("wip", "Currently broken", "Voosh"))
        self.assertEqual(sorted(dis["files"]), ["32", "64"])
        self.assertEqual((apt["status"], apt["files"], apt["page"]),
                         ("working", {}, "https://www.nexusmods.com/game/mods/1"))  # by hand only
        # not a known author: never downloaded, the file is only a link for installing by hand
        self.assertEqual((shady["status"], shady["files"], shady["page"]),
                         ("wip", {}, "https://evil.example.com/renodx-shady.addon64"))
        self.assertEqual((old["status"], old["note"]), ("other", "Superseded by Generic Unity mod"))
        self.assertEqual(old["files"], {}, "a GitHub release of an account not in AUTHORS is not trusted")

    def test_only_known_author_accounts(self):
        self.assertEqual(X.source("https://clshortfuse.github.io/renodx/renodx-godofwar.addon64"),
                         ("clshortfuse", "renodx", "snapshot", "renodx-godofwar.addon64"))
        self.assertEqual(X.source("https://github.com/OopyDoopy/renodx/releases/download/snap-1/renodx-x.addon32"),
                         ("OopyDoopy", "renodx", "snap-1", "renodx-x.addon32"))
        for url in ("https://attacker.github.io/renodx/renodx-godofwar.addon64",
                    "https://github.com/attacker/renodx/releases/download/snapshot/renodx-godofwar.addon64",
                    "https://clshortfuse.github.io.evil.test/renodx/x.addon64",
                    "http://clshortfuse.github.io/renodx/x.addon64",
                    "https://clshortfuse.github.io/renodx/../x.addon64"):
            self.assertIsNone(X.source(url), url)

    def test_host_names_who_publishes_the_file(self):
        self.assertEqual(X.host("https://clshortfuse.github.io/renodx/renodx-godofwar.addon64"), "github.com/clshortfuse")
        self.assertEqual(X.host("https://github.com/mqhaji/renodx/releases/download/snapshot/a.addon64"), "github.com/mqhaji")
        self.assertEqual(X.host("https://github.com/x/renodx/releases/download/snapshot/renodx-old.addon64"), "")
        self.assertEqual(X.host(None), "")

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


def release(filename, data, **changes):
    """GitHub's description of an author's snapshot release holding one add-on."""
    asset = {"name": filename, "state": "uploaded", "size": len(data),
             "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
             "browser_download_url": f"https://github.com/clshortfuse/renodx/releases/download/snapshot/{filename}"}
    return {"tag_name": "snapshot", "assets": [{"name": "other.addon64"}, {**asset, **changes}]}


class GitHub:
    """dk_net as GitHub answers: the release description, then the file (refused when its hash differs)."""

    def __init__(self, data, served=None, **changes):
        self.data, self.served, self.changes, self.calls = data, served or data, changes, []

    def get(self, url, limit, sha256=None, **kw):
        self.calls.append(("get", url, kw))
        return json.dumps(release("renodx-godofwar.addon64", self.data, **self.changes)).encode()

    def download(self, url, dest, limit, sha256=None, **kw):
        self.calls.append(("download", url, kw))
        if hashlib.sha256(self.served).hexdigest() != sha256:
            raise dk_net.Mismatch("not the expected file (SHA-256 differs)")
        with open(dest, "wb") as f:
            f.write(self.served)
        return sha256

    def __enter__(self):
        self.patches = [mock.patch.object(dk_net, "get", self.get), mock.patch.object(dk_net, "download", self.download)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class Download(unittest.TestCase):
    def setUp(self):
        self.mods = {m["name"]: m for m in X.parse(WIKI)}
        self.gow = self.mods["God of War (2018)"]
        self.folder = tempfile.mkdtemp()

    def test_from_the_authors_release_checked_by_githubs_sum(self):
        with GitHub(make_pe(64)) as github:
            path = X.download(self.gow, 64, self.folder)
        self.assertEqual(os.path.basename(path), "renodx-godofwar.addon64")
        (_, api, meta), (_, url, kw) = github.calls
        self.assertEqual((api, meta["hosts"], meta["redirects"]),
                         ("https://api.github.com/repos/clshortfuse/renodx/releases/tags/snapshot", {"api.github.com"},
                          False))
        self.assertEqual(url, "https://github.com/clshortfuse/renodx/releases/download/snapshot/renodx-godofwar.addon64")
        self.assertEqual(kw["hosts"], X.GITHUB_DOWNLOADS)

    def test_the_newest_snapshot_already_here_is_not_downloaded_again(self):
        with GitHub(make_pe(64)) as github:
            first = X.download(self.gow, 64, self.folder)
            self.assertEqual(X.download(self.gow, 64, self.folder), first)
        self.assertEqual([c[0] for c in github.calls], ["get", "download", "get"])
        with GitHub(make_pe(64, [], b"a newer snapshot")) as github:  # changed on GitHub: fetched
            X.download(self.gow, 64, self.folder)
        self.assertEqual([c[0] for c in github.calls], ["get", "download"])

    def test_a_large_engine_wide_mod_is_allowed_but_not_without_limit(self):
        with GitHub(make_pe(64), size=X.MAX_ADDON + 1):
            with self.assertRaisesRegex(X.RenoDXError, "more than the 256 MB"):
                X.download(self.gow, 64, self.folder)
        self.assertGreaterEqual(X.MAX_ADDON, 110 << 20, "the Unity engine-wide mod is about 105 MB")

    def test_a_file_that_does_not_match_its_sum_is_refused_and_not_kept(self):
        with GitHub(make_pe(64), served=make_pe(64, [], b"tampered")):
            with self.assertRaisesRegex(X.RenoDXError, "could not be downloaded"):
                X.download(self.gow, 64, self.folder)
        self.assertEqual(os.listdir(self.folder), [])

    def test_no_sum_or_another_address_from_github_is_refused(self):
        for changes in ({"digest": None}, {"state": "new"}, {"size": 0},
                        {"browser_download_url": "https://evil.test/renodx-godofwar.addon64"},
                        {"name": "renamed.addon64"}):
            with GitHub(make_pe(64), **changes) as github:
                with self.assertRaisesRegex(X.RenoDXError, "install the mod by hand"):
                    X.download(self.gow, 64, self.folder)
            self.assertEqual([c[0] for c in github.calls], ["get"], changes)
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_foreign_account_is_refused_even_from_an_old_list(self):
        stale = {**self.gow, "files": {"64": "https://attacker.github.io/renodx/renodx-godofwar.addon64"}}
        with GitHub(make_pe(64)) as github:
            with self.assertRaisesRegex(X.RenoDXError, "not from a RenoDX author"):
                X.download(stale, 64, self.folder)
        self.assertEqual(github.calls, [], "nothing is even asked for")

    def test_bitness_and_missing_builds(self):
        with GitHub(make_pe(32)):
            self.assertRaises(X.RenoDXError, X.download, self.gow, 64, self.folder)  # wrong file
        self.assertRaises(X.RenoDXError, X.download, self.gow, 32, self.folder)  # no 32-bit build
        self.assertRaises(X.RenoDXError, X.download, self.mods["A Plague Tale: Requiem"], 64, self.folder)
        self.assertEqual(os.listdir(self.folder), [])

    def test_no_release_on_github(self):
        def missing(*a, **kw):
            error = dk_net.NetError("HTTP 404")
            error.status = 404
            raise error
        with mock.patch.object(dk_net, "get", missing):
            with self.assertRaisesRegex(X.RenoDXError, "no RenoDX release named snapshot"):
                X.download(self.gow, 64, self.folder)


if __name__ == "__main__":
    unittest.main()
