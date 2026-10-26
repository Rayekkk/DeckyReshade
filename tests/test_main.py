# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""The plugin as the panel drives it, with the network replaced: setup, games on and off, versions, AutoHDR,
non-Steam games, logs and removing everything again."""

import asyncio
import hashlib
import os
import re
import tempfile
import unittest
from unittest import mock

import _harness
import main
import reshade_net
import reshade_release
import reshade_renodx
import reshade_shaders
from _pe import make_pe
from test_games import _vdf
from test_renodx import WIKI
from test_release import installer
from test_shaders import LIST, archive

decky = _harness.install()
PUMBO = """
[29]
PackageName=AdvancedAutoHDR by Pumbo
InstallPath=.\\reshade-shaders\\Shaders
DownloadUrl=https://github.com/Filoppi/PumboAutoHDR/archive/refs/heads/master.zip
"""


def fake_installer(marker):
    return installer(dll64=make_pe(64, [], marker.encode()))


def fake_download(versions):
    """reshade_net.download serving whatever each URL stands for; versions: ReShade version -> DLL marker."""
    def download(url, dest, limit, sha256=None, progress=None):
        if "reshade.me/downloads/" in url:
            data = fake_installer(versions[re.search(r"Setup_(\d+\.\d+\.\d+)", url).group(1)])
        elif url.endswith(".addon64"):
            data = make_pe(64)
        elif "d3dcompiler" in url:
            data = make_pe(64 if "_32" not in url else 32)
        else:
            data = archive({"repo-master/Shaders/ReShade.fxh": "x", "repo-master/Shaders/Effect.fx": "x"})
        with open(dest, "wb") as f:
            f.write(data)
        digest = reshade_net.sha256_file(dest)
        if sha256 and digest != sha256 and "reshade.me" in url:  # stand-in compilers cannot match Microsoft's hash
            raise reshade_net.NetError("does not match its known SHA-256")
        return digest
    return download


def fake_autohdr(root):
    for bits in (32, 64):
        with open(reshade_release.autohdr_path(root, bits), "wb") as f:
            f.write(make_pe(bits))


class Flow(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp()
        decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(base, "settings")
        decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(base, "runtime")
        decky.DECKY_USER_HOME = os.path.join(base, "home")
        main._ready = asyncio.Event()
        steam = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")
        apps = os.path.join(steam, "steamapps")
        os.makedirs(os.path.join(apps, "common", "Game"))
        with open(os.path.join(apps, "appmanifest_70.acf"), "w") as f:
            f.write('"AppState"\n{\n"appid" "70"\n"name" "God of War"\n"installdir" "Game"\n}\n')
        self.game_dir = os.path.join(apps, "common", "Game")
        with open(os.path.join(self.game_dir, "Game.exe"), "wb") as f:
            f.write(make_pe(64, ["d3d11.dll"]))
        # a non-Steam game: a Windows emulator added to Steam, with its own launch options
        self.emu_dir = os.path.join(base, "Emulators", "Eden")
        os.makedirs(self.emu_dir)
        with open(os.path.join(self.emu_dir, "eden.exe"), "wb") as f:
            f.write(make_pe(64, ["opengl32.dll"]))
        os.makedirs(os.path.join(steam, "userdata", "1", "config"))
        with open(os.path.join(steam, "userdata", "1", "config", "shortcuts.vdf"), "wb") as f:
            f.write(_vdf({"shortcuts": {"0": {"appid": -5, "AppName": "Eden",
                                              "Exe": f'"{os.path.join(self.emu_dir, "eden.exe")}"',
                                              "LaunchOptions": "-fullscreen"}}}) + b"\x08")
        self.emu_appid = -5 & 0xFFFFFFFF
        self.versions = {"6.9.0": "build 6.9.0", "6.10.0": "build 6.10.0", "6.5.1": "build 6.5.1"}
        sha = hashlib.sha256(fake_installer("build 6.5.1")).hexdigest()
        self.patches = [
            mock.patch.object(reshade_net, "download", fake_download(self.versions)),
            mock.patch.object(reshade_shaders, "fetch_list", return_value=reshade_shaders.parse_list(LIST + PUMBO)),
            mock.patch.object(reshade_release, "fetch_autohdr", fake_autohdr),
            mock.patch.object(reshade_renodx, "fetch_list", return_value=reshade_renodx.parse(WIKI)),
            mock.patch.object(reshade_release, "KNOWN", {"6.5.1": {False: sha, True: sha}}),
            mock.patch.object(reshade_release, "VERSIONS", ["6.5.1"]),
            mock.patch.object(reshade_release, "FALLBACK", "6.5.1"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def dll(self, name="dxgi.dll"):
        with open(os.path.join(self.game_dir, name), "rb") as f:
            return f.read()

    def test_whole_flow(self):
        async def flow():
            p = main.Plugin()
            with mock.patch.object(reshade_release, "latest_version", return_value="6.9.0"):
                await p._main()
                await p._scan_task
                await p._renodx_task
                state = await p.get_state()
                self.assertIsNone(state["reshade"]["installed"])  # the panel shows the setup wizard
                self.assertTrue(state["settings"]["addon"])  # add-on build by default
                self.assertEqual([(g["name"], g["renodx"]) for g in state["games"]], [("Eden", None), ("God of War", "working")])

                state = await p.setup(True, "latest", True)
                self.assertEqual(state["job"], {"task": "", "error": ""})
                self.assertEqual((state["reshade"]["installed"], state["reshade"]["addon"]), ("6.9.0", True))
                self.assertTrue(state["reshade"]["autohdr_ready"])
                self.assertEqual(state["shaders"]["installed"], ["advancedautohdr-by-pumbo", "standard-effects"])

                info = await p.get_game(70)
                self.assertEqual((info["exe"], info["bits"], info["detected_api"]), ("Game.exe", 64, "dxgi"))
                self.assertFalse(info["log"]["found"])
                res = await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid")
                self.assertEqual(res, {"ok": True, "dlo": False,
                                       "launch_options": 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command% -novid'})
                self.assertIn(b"build 6.9.0", self.dll())
                self.assertFalse((await p.enable_game(70, "../../escape.exe", "dxgi", False, "", ""))["ok"])

                # AutoHDR on while ReShade is on: set up again with the add-on, its variable and a first preset
                res = await p.enable_game(70, "Game.exe", "dxgi", True, "", res["launch_options"])
                self.assertEqual(res["launch_options"],
                                 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" DXVK_HDR=1 %command% -novid')
                self.assertTrue(os.path.exists(os.path.join(self.game_dir, "AutoHDR.addon64")))
                self.assertTrue(os.path.exists(os.path.join(self.game_dir, "ReShadePreset.ini")))
                self.assertFalse((await p.enable_game(70, "Game.exe", "d3d9", True, "", ""))["ok"])  # not DXGI

                # switching API: the old setup is undone first, launch options stay one merge
                res = await p.enable_game(70, "Game.exe", "d3d11", False, "", res["launch_options"])
                self.assertEqual(res["launch_options"], 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;d3d11=n,b" %command% -novid')
                self.assertFalse(os.path.exists(os.path.join(self.game_dir, "dxgi.dll")))
                self.assertFalse(os.path.exists(os.path.join(self.game_dir, "AutoHDR.addon64")))
                game_options = (await p.enable_game(70, "Game.exe", "dxgi", False, "", res["launch_options"]))["launch_options"]

                # RenoDX: matched by name, downloaded from its author, HDR variable added; not together with AutoHDR
                info = await p.get_game(70)
                self.assertEqual((info["renodx"]["auto"], info["renodx"]["mod"]["files"]), ("God of War (2018)", ["64"]))
                self.assertFalse((await p.enable_game(70, "Game.exe", "dxgi", True, "God of War (2018)", game_options))["ok"])
                res = await p.enable_game(70, "Game.exe", "dxgi", False, "God of War (2018)", game_options)
                self.assertEqual(res["launch_options"],
                                 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" DXVK_HDR=1 %command% -novid')
                self.assertTrue(os.path.exists(os.path.join(self.game_dir, "renodx-godofwar.addon64")))
                self.assertEqual((await p.get_state())["enabled"][0]["renodx"], "God of War (2018)")
                self.assertEqual((await p.get_game(70))["renodx"]["installed"], "God of War (2018)")
                res = await p.enable_game(70, "Game.exe", "dxgi", False, "", res["launch_options"])
                game_options = res["launch_options"]
                self.assertEqual(game_options, 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command% -novid')
                self.assertFalse(os.path.exists(os.path.join(self.game_dir, "renodx-godofwar.addon64")))
                self.assertFalse((await p.enable_game(70, "Game.exe", "dxgi", False, "Not In The List", ""))["ok"])

                # a non-Steam game: Steam's app details have no launch options, shortcuts.vdf has them
                res = await p.enable_game(self.emu_appid, "eden.exe", "opengl32", False, "", "")
                self.assertEqual(res["launch_options"],
                                 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;opengl32=n,b" %command% -fullscreen')
                self.assertTrue(os.path.exists(os.path.join(self.emu_dir, "opengl32.dll")))

            with mock.patch.object(reshade_release, "latest_version", return_value="6.10.0"):
                state = await p.check_reshade()
                self.assertTrue(state["reshade"]["update_available"])
                state = await p.update_reshade()
                self.assertEqual(state["reshade"]["installed"], "6.10.0")
                self.assertIn(b"build 6.10.0", self.dll())
                self.assertNotIn("6.9.0", os.listdir(p.reshade_root))  # the old build is gone

            # reshade.me unreachable: nothing changes and the panel is told why
            with mock.patch.object(reshade_release, "latest_version",
                                   side_effect=reshade_release.ReleaseError("offline")):
                state = await p.update_reshade()
                self.assertEqual(state["reshade"]["installed"], "6.10.0")
                self.assertEqual(state["reshade"]["check_error"], "offline")

            # a fixed older version, then the standard build: every game follows, no auto-update
            state = await p.set_version("6.5.1")
            self.assertEqual((state["reshade"]["installed"], state["settings"]["version"]), ("6.5.1", "6.5.1"))
            self.assertIn(b"build 6.5.1", self.dll())
            with mock.patch.object(reshade_release, "latest_version", side_effect=AssertionError("checked")):
                await p.update_reshade()
            state = await p.set_setting("addon", False)
            self.assertEqual((state["reshade"]["installed"], state["reshade"]["addon"]), ("6.5.1", False))

            # twice in a row without ReShade's log: the user is warned
            for expect_warning in (False, True):
                await p.session_started(70)
                res = await p.session_ended(70)
                self.assertEqual("warning" in res, expect_warning)

            # logs and the report
            with open(os.path.join(self.game_dir, "ReShade.log"), "w") as f:
                f.write("t [1] | ERROR | Failed to compile x.fx\n")
            self.assertIn("Failed to compile", (await p.get_logs(70))["reshade"])
            self.assertEqual((await p.get_game(70))["log"]["errors"], ["Failed to compile x.fx"])
            report = await p.save_report()
            with open(report["path"], encoding="utf-8") as f:
                self.assertIn("Failed to compile x.fx", f.read())

            # downloaded files cannot go while games use them
            state = await p.remove_data()
            self.assertIn("Turn ReShade off", state["job"]["error"])
            res = await p.disable_game(70, game_options)
            self.assertEqual(res["launch_options"], "-novid")
            self.assertEqual(sorted(os.listdir(self.game_dir)), ["Game.exe", "ReShade.ini", "ReShade.log",
                                                                   "ReShadePreset.ini"])
            res = await p.disable_game(self.emu_appid, "")
            self.assertEqual(res["launch_options"], "-fullscreen")

            # a game Decky Launch Options runs: files go in, its launch options are left to DLO
            res = await p.enable_game(70, "Game.exe", "dxgi", False, "", "~/.dlo/run %command%")
            self.assertEqual(res, {"ok": True, "launch_options": "~/.dlo/run %command%", "dlo": True})
            await p.disable_game(70, "~/.dlo/run %command%")

            state = await p.remove_data()
            self.assertEqual(state["job"]["error"], "")
            self.assertIsNone(state["reshade"]["installed"])
            self.assertEqual(state["shaders"]["installed"], [])

        asyncio.run(flow())


if __name__ == "__main__":
    unittest.main()
