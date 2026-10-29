# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""The plugin as the panel drives it, with the network replaced: setup, games on and off, versions, AutoHDR,
RenoDX, non-Steam games, logs, removing everything again, the RPC contract and stopping."""

import asyncio
import hashlib
import inspect
import os
import re
import tempfile
import threading
import unittest
from unittest import mock

import _harness
import dk_fs
import dk_net
import main
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
OPTIONS = 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;{api}=n,b" {env}%command% {rest}'


def fake_installer(marker):
    return installer(dll64=make_pe(64, [], marker.encode()))


def fake_download(versions):
    """dk_net.download serving whatever each URL stands for; versions: ReShade version -> DLL marker."""
    def download(url, dest, limit, sha256=None, **kw):
        if "reshade.me/downloads/" in url:
            data = fake_installer(versions[re.search(r"Setup_(\d+\.\d+\.\d+)", url).group(1)])
        elif url.endswith(".addon64"):
            data = make_pe(64)
        elif "d3dcompiler" in url:
            data = make_pe(64 if "_32" not in url else 32)
        else:
            data = archive({"repo-master/Shaders/ReShade.fxh": "x", "repo-master/Shaders/Effect.fx": "x"})
        digest = hashlib.sha256(data).hexdigest()
        if sha256 and digest != sha256 and "reshade.me" in url:  # stand-in compilers cannot match Microsoft's hash
            raise dk_net.Mismatch("not the expected file (SHA-256 differs)")
        with open(dest, "wb") as f:
            f.write(data)
        download.calls.append((url, kw))
        return digest
    download.calls = []
    return download


def known(versions, *names):
    """KNOWN for the stand-in installers of these versions (both builds share one)."""
    sums = {v: hashlib.sha256(fake_installer(versions[v])).hexdigest() for v in names}
    return {v: {False: sums[v], True: sums[v]} for v in names}


def fake_autohdr(root, cancel=None):
    for bits in (32, 64):
        with open(reshade_release.autohdr_path(root, bits), "wb") as f:
            f.write(make_pe(bits))


class Base(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp()
        decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(base, "settings")
        decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(base, "runtime")
        decky.DECKY_USER_HOME = os.path.join(base, "home")
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
        self.download = fake_download(self.versions)
        self.patches = [
            mock.patch.object(dk_net, "download", self.download),
            mock.patch.object(reshade_shaders, "fetch_list", return_value=reshade_shaders.parse_list(LIST + PUMBO)),
            mock.patch.object(reshade_release, "fetch_autohdr", fake_autohdr),
            mock.patch.object(reshade_renodx, "fetch_list", return_value=reshade_renodx.parse(WIKI)),
            mock.patch.object(reshade_release, "KNOWN", known(self.versions, "6.9.0", "6.5.1")),
            mock.patch.object(reshade_release, "VERSIONS", ["6.9.0", "6.5.1"]),
            mock.patch.object(reshade_release, "FALLBACK", "6.9.0"),
            mock.patch.object(reshade_release, "latest_version", return_value="6.9.0"),
            # GitHub's description of an author's release: the address (served by fake_download), no sum to check
            mock.patch.object(reshade_renodx, "_asset", lambda author, repo, tag, name, cancel:
                              (f"https://github.com/{author}/{repo}/releases/download/{tag}/{name}", 1 << 20, None)),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    async def start(self, setup=False, autohdr=False):
        """A started plugin with its background work done; with setup, the wizard already finished."""
        p = main.Plugin()
        await p._main()
        await asyncio.gather(*p.tasks)
        if setup:
            r = await p.setup(True, "latest", autohdr)
            self.assertTrue(r["ok"], r)
        return p

    def dll(self, name="dxgi.dll"):
        with open(os.path.join(self.game_dir, name), "rb") as f:
            return f.read()


class Setup(Base):
    def test_first_start_shows_the_wizard_with_the_library_scanned(self):
        async def flow():
            p = await self.start()
            state = (await p.get_state())["state"]
            self.assertIsNone(state["reshade"]["installed"])  # the panel shows the setup wizard
            self.assertTrue(state["settings"]["addon"])  # add-on build by default
            self.assertEqual([(g["name"], g["renodx"]) for g in state["games"]],
                             [("Eden", None), ("God of War", "working")])
        self.run_async(flow())

    def test_setup_downloads_reshade_shaders_and_autohdr(self):
        async def flow():
            p = await self.start(setup=True, autohdr=True)
            state = (await p.get_state())["state"]
            self.assertEqual(state["job"], {"task": "", "error": ""})
            self.assertEqual((state["reshade"]["installed"], state["reshade"]["addon"]), ("6.9.0", True))
            self.assertTrue(state["reshade"]["autohdr_ready"])
            self.assertEqual(state["shaders"]["installed"], ["advancedautohdr-by-pumbo", "standard-effects"])
        self.run_async(flow())

    def test_a_failed_setup_is_answered_and_kept_for_the_panel(self):
        async def flow():
            p = await self.start()
            with mock.patch.object(reshade_release, "fetch", side_effect=reshade_release.ReleaseError("offline")):
                r = await p.setup(True, "latest", False)
            self.assertEqual((r["ok"], r["error"], r["state"]["job"]["error"]), (False, "offline", "offline"))
            self.assertIsNone(r["state"]["reshade"]["installed"])
        self.run_async(flow())


class Games(Base):
    def test_enable_merges_launch_options_and_stays_in_the_game_folder(self):
        async def flow():
            p = await self.start(setup=True)
            info = await p.get_game(70)
            self.assertEqual((info["ok"], info["exe"], info["bits"], info["detected_api"]), (True, "Game.exe", 64, "dxgi"))
            self.assertFalse(info["log"]["found"])
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid")
            self.assertEqual(r, {"ok": True, "dlo": False, "launch_options": OPTIONS.format(api="dxgi", env="", rest="-novid")})
            self.assertIn(b"build 6.9.0", self.dll())
            r = await p.enable_game(70, "../../escape.exe", "dxgi", False, "", "")
            self.assertEqual(r["ok"], False)
            self.assertIn("not in the game's folder", r["error"])
            self.assertFalse((await p.get_game(12345))["ok"])
        self.run_async(flow())

    def test_a_game_without_a_windows_executable_is_unsupported_not_a_failed_read(self):
        async def flow():
            p = await self.start(setup=True)
            os.remove(os.path.join(self.game_dir, "Game.exe"))
            r = await p.get_game(70)
            self.assertEqual((r["ok"], r.get("unsupported")), (False, True))
            self.assertIn("native Linux game", r["error"])
            self.assertNotIn("unsupported", await p.get_game(12345), "a game not found can still be read again")
        self.run_async(flow())

    def test_autohdr_and_a_new_api_set_the_game_up_again(self):
        async def flow():
            p = await self.start(setup=True)
            options = (await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid"))["launch_options"]
            r = await p.enable_game(70, "Game.exe", "dxgi", True, "", options)
            self.assertEqual(r["launch_options"], OPTIONS.format(api="dxgi", env="DXVK_HDR=1 ", rest="-novid"))
            self.assertTrue(os.path.exists(os.path.join(self.game_dir, "AutoHDR.addon64")))
            self.assertTrue(os.path.exists(os.path.join(self.game_dir, "ReShadePreset.ini")))
            self.assertFalse((await p.enable_game(70, "Game.exe", "d3d9", True, "", ""))["ok"])  # not DXGI
            # switching API: the old setup is undone first, launch options stay one merge
            r = await p.enable_game(70, "Game.exe", "d3d11", False, "", r["launch_options"])
            self.assertEqual(r["launch_options"], OPTIONS.format(api="d3d11", env="", rest="-novid"))
            self.assertFalse(os.path.exists(os.path.join(self.game_dir, "dxgi.dll")))
            self.assertFalse(os.path.exists(os.path.join(self.game_dir, "AutoHDR.addon64")))
        self.run_async(flow())

    def test_renodx_mod_from_its_author_with_the_hdr_variable(self):
        async def flow():
            p = await self.start(setup=True)
            options = (await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid"))["launch_options"]
            info = await p.get_game(70)
            self.assertEqual((info["renodx"]["auto"], info["renodx"]["mod"]["files"]), ("God of War (2018)", ["64"]))
            self.assertEqual(info["renodx"]["mod"]["host"], "github.com/clshortfuse")
            self.assertFalse((await p.enable_game(70, "Game.exe", "dxgi", True, "God of War (2018)", options))["ok"])
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "God of War (2018)", options)
            self.assertEqual(r["launch_options"], OPTIONS.format(api="dxgi", env="DXVK_HDR=1 ", rest="-novid"))
            self.assertTrue(os.path.exists(os.path.join(self.game_dir, "renodx-godofwar.addon64")))
            self.assertEqual((await p.get_state())["state"]["enabled"][0]["renodx"], "God of War (2018)")
            self.assertEqual((await p.get_game(70))["renodx"]["installed"], "God of War (2018)")
            # the author renames the snapshot: updating takes the old file out instead of leaving two mods
            mod = p._mod("God of War (2018)")
            mod["files"]["64"] = mod["files"]["64"].replace("renodx-godofwar", "renodx-gow")
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "God of War (2018)", r["launch_options"])
            self.assertEqual(sorted(n for n in os.listdir(self.game_dir) if n.startswith("renodx")),
                             ["renodx-gow.addon64"])
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "", r["launch_options"])
            self.assertEqual(r["launch_options"], OPTIONS.format(api="dxgi", env="", rest="-novid"))
            self.assertFalse([n for n in os.listdir(self.game_dir) if n.startswith("renodx")])
            self.assertFalse((await p.enable_game(70, "Game.exe", "dxgi", False, "Not In The List", ""))["ok"])
        self.run_async(flow())

    def test_a_renodx_download_does_not_hold_up_other_calls(self):
        async def flow():
            p = await self.start(setup=True)
            started, release = threading.Event(), threading.Event()

            def slow(*a, **kw):
                started.set()
                release.wait(5)
                return self.download(*a, **kw)

            with mock.patch.object(dk_net, "download", slow):
                enabling = asyncio.create_task(p.enable_game(70, "Game.exe", "dxgi", False, "God of War (2018)", ""))
                await asyncio.to_thread(started.wait, 5)
                self.assertFalse(p.lock.locked(), "the download runs before the lock is taken")
                report = await asyncio.wait_for(p.save_report(), 5)  # needs the lock
                self.assertTrue(report["ok"])
                release.set()
                self.assertTrue((await enabling)["ok"])
        self.run_async(flow())

    def test_non_steam_game_options_come_from_shortcuts(self):
        async def flow():
            p = await self.start(setup=True)
            r = await p.enable_game(self.emu_appid, "eden.exe", "opengl32", False, "", "")
            self.assertEqual(r["launch_options"], OPTIONS.format(api="opengl32", env="", rest="-fullscreen"))
            self.assertTrue(os.path.exists(os.path.join(self.emu_dir, "opengl32.dll")))
            r = await p.disable_game(self.emu_appid, "")
            self.assertEqual((r["ok"], r["launch_options"]), (True, "-fullscreen"))
        self.run_async(flow())

    def test_decky_launch_options_keeps_the_launch_options(self):
        async def flow():
            p = await self.start(setup=True)
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "", "~/.dlo/run %command%")
            self.assertEqual(r, {"ok": True, "launch_options": "~/.dlo/run %command%", "dlo": True})
            # DLO kept ReShade's overrides as the game's original: the panel is told to switch them off there
            os.makedirs(os.path.join(decky.DECKY_USER_HOME, ".dlo"))
            dlo = os.path.join(decky.DECKY_USER_HOME, ".dlo", "settings.json")
            with open(dlo, "w") as f:
                f.write('{"profiles": {"70": {"originalLaunchOptions": '
                        '"WINEDLLOVERRIDES=\\"d3dcompiler_47=n,b;dxgi=n,b\\" %command%"}}}')
            r = await p.disable_game(70, "~/.dlo/run %command%")
            self.assertEqual((r["launch_options"], r["dlo_leftover"]),
                             ("~/.dlo/run %command%", 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b"'))
            self.assertEqual(sorted(os.listdir(os.path.dirname(dlo))), ["settings.json"], "DLO's file is only read")
            # Decky Launch Options installed: launch options are never written, whatever they are now
            r = await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid", True)
            self.assertEqual(r, {"ok": True, "launch_options": "-novid", "dlo": True})
        self.run_async(flow())

    def test_two_sessions_without_reshade_warn_the_user(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            for expect_warning in (False, True):
                self.assertTrue((await p.session_started(70))["managed"])
                r = await p.session_ended(70)
                self.assertEqual("warning" in r, expect_warning)
            self.assertEqual(await p.session_started(999), {"ok": True, "managed": False})
        self.run_async(flow())

    def test_logs_and_the_report(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            with open(os.path.join(self.game_dir, "ReShade.log"), "w") as f:
                f.write("t [1] | ERROR | Failed to compile x.fx\n")
            self.assertIn("Failed to compile", (await p.get_logs(70))["reshade"])
            self.assertEqual((await p.get_game(70))["log"]["errors"], ["Failed to compile x.fx"])
            report = await p.save_report()
            self.assertEqual(os.path.dirname(report["path"]), os.path.join(decky.DECKY_USER_HOME, "Downloads"))
            with open(report["path"], encoding="utf-8") as f:
                self.assertIn("Failed to compile x.fx", f.read())
            # a game without ReShade: the log beside the executable the panel shows, never outside the game
            with open(os.path.join(self.emu_dir, "ReShade.log"), "w") as f:
                f.write("old run")
            self.assertEqual((await p.get_logs(self.emu_appid, "eden.exe"))["reshade"], "old run")
            self.assertEqual((await p.get_logs(self.emu_appid, "../../escape.exe"))["reshade"], "")
        self.run_async(flow())


class Versions(Base):
    def test_a_newer_reshade_without_known_sums_is_shown_never_installed(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            with mock.patch.object(reshade_release, "latest_version", return_value="6.10.0"):
                state = (await p.check_reshade())["state"]
                self.assertEqual((state["reshade"]["newer_than_known"], state["reshade"]["update_available"]),
                                 ("6.10.0", False))
                state = (await p.update_reshade())["state"]
                self.assertEqual(state["reshade"]["installed"], "6.9.0")
                self.assertIn(b"build 6.9.0", self.dll())
            self.assertFalse([c for c in self.download.calls if "6.10.0" in c[0]], "never even downloaded")
        self.run_async(flow())

    def test_a_plugin_update_with_new_sums_moves_every_game(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            with mock.patch.object(reshade_release, "KNOWN", known(self.versions, "6.10.0", "6.9.0", "6.5.1")), \
                    mock.patch.object(reshade_release, "FALLBACK", "6.10.0"), \
                    mock.patch.object(reshade_release, "latest_version", return_value="6.10.0"):
                state = (await p.check_reshade())["state"]
                self.assertTrue(state["reshade"]["update_available"])
                self.assertIsNone(state["reshade"]["newer_than_known"])
                state = (await p.update_reshade())["state"]
                self.assertEqual(state["reshade"]["installed"], "6.10.0")
                self.assertIn(b"build 6.10.0", self.dll())
                self.assertNotIn("6.9.0", os.listdir(p.reshade_root))  # the old build is gone
            # reshade.me unreachable: nothing changes and the panel is told why
            with mock.patch.object(reshade_release, "latest_version",
                                   side_effect=reshade_release.ReleaseError("offline")):
                state = (await p.update_reshade())["state"]
                self.assertEqual(state["reshade"]["installed"], "6.10.0")
                self.assertEqual(state["reshade"]["check_error"], "offline")
        self.run_async(flow())

    def test_a_fixed_version_and_the_standard_build_reach_every_game(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            state = (await p.set_version("6.5.1"))["state"]
            self.assertEqual((state["reshade"]["installed"], state["settings"]["version"]), ("6.5.1", "6.5.1"))
            self.assertIn(b"build 6.5.1", self.dll())
            with mock.patch.object(reshade_release, "latest_version", side_effect=AssertionError("checked")):
                await p.update_reshade()
            state = (await p.set_setting("addon", False))["state"]
            self.assertEqual((state["reshade"]["installed"], state["reshade"]["addon"]), ("6.5.1", False))
            r = await p.set_version("1.0.0")
            self.assertEqual((r["ok"], r["state"]["settings"]["version"]), (False, "6.5.1"))
            self.assertFalse((await p.set_setting("nonsense", True))["ok"])
        self.run_async(flow())

    def test_settings_change_in_memory_only_once_saved(self):
        async def flow():
            p = await self.start()
            with mock.patch.object(dk_fs, "write_json", side_effect=OSError(28, "No space left on device")):
                r = await p.set_setting("auto_launch_options", False)
            self.assertEqual(r["ok"], False)
            self.assertIn("No space left", r["error"])
            self.assertTrue(r["state"]["settings"]["auto_launch_options"])
        self.run_async(flow())


class Data(Base):
    def test_a_failed_renodx_refresh_keeps_the_list_with_the_reason(self):
        async def flow():
            p = await self.start()
            with mock.patch.object(reshade_renodx, "fetch_list",
                                   side_effect=reshade_renodx.RenoDXError("Could not load the RenoDX mod list")):
                state = (await p.refresh_renodx())["state"]
            self.assertEqual(state["renodx"]["error"], "Could not load the RenoDX mod list")
            self.assertEqual(state["renodx"]["count"], len(reshade_renodx.parse(WIKI)))
            self.assertEqual([g["renodx"] for g in state["games"] if g["name"] == "God of War"], ["working"])
            mods = (await p.get_renodx_mods())["mods"]
            self.assertIn({"name": "God of War (2018)", "status": "working"}, mods)
        self.run_async(flow())

    def test_shader_packages_load_as_a_job(self):
        async def flow():
            p = await self.start(setup=True)
            p.packages = None
            r = await p.load_packages()
            self.assertTrue(r["ok"])
            self.assertTrue(r["state"]["shaders"]["packages"])
            p.job = {"task": "Updating shaders…", "error": ""}
            r = await p.load_packages()
            self.assertEqual(r["ok"], False, "one job at a time")
            self.assertIn("Updating shaders", r["error"])
            p.job = {"task": "", "error": ""}
            self.assertFalse((await p.set_package("no-such-package", True))["ok"])
            r = await p.set_package("standard-effects", False)
            self.assertNotIn("standard-effects", r["state"]["shaders"]["installed"])
        self.run_async(flow())

    def test_downloaded_files_go_only_when_no_game_uses_them(self):
        async def flow():
            p = await self.start(setup=True)
            options = (await p.enable_game(70, "Game.exe", "dxgi", False, "", "-novid"))["launch_options"]
            r = await p.remove_data()
            self.assertEqual(r["ok"], False)
            self.assertIn("Turn ReShade off", r["state"]["job"]["error"])
            r = await p.disable_game(70, options)
            self.assertEqual(r["launch_options"], "-novid")
            self.assertEqual(sorted(os.listdir(self.game_dir)), ["Game.exe", "ReShade.ini"])
            state = (await p.remove_data())["state"]
            self.assertEqual(state["job"]["error"], "")
            self.assertIsNone(state["reshade"]["installed"])
            self.assertEqual(state["shaders"]["installed"], [])
        self.run_async(flow())

    def test_a_damaged_game_list_blocks_changes_and_says_why(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            for name in os.listdir(decky.DECKY_PLUGIN_SETTINGS_DIR):
                if name.startswith("manifest.json"):
                    with open(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, name), "w") as f:
                        f.write("{broken")
            q = await self.start()
            state = (await q.get_state())["state"]
            self.assertIn("damaged", state["job"]["error"])
            r = await q.enable_game(70, "Game.exe", "dxgi", False, "", "")
            self.assertFalse(r["ok"])
            with open(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "manifest.json")) as f:
                self.assertEqual(f.read(), "{broken", "kept for repair, never written over")
        self.run_async(flow())


class Contract(Base):
    def test_every_rpc_answers_ok_and_never_raises(self):
        async def flow():
            p = await self.start()
            public = [n for n, f in inspect.getmembers(main.Plugin, inspect.iscoroutinefunction)
                      if not n.startswith("_")]
            self.assertIn("get_state", public)
            for name in public:
                self.assertTrue(hasattr(getattr(main.Plugin, name), "__wrapped__"), f"{name} has no RPC boundary")
            with mock.patch.object(main.reshade_games, "all_games", side_effect=KeyError("/home/someone")):
                r = await p.scan_games()
            self.assertEqual(r["ok"], False)
            self.assertNotIn("someone", r["error"])
        self.run_async(flow())


class WriteErrors(Base):
    def test_a_failed_write_tells_why_without_the_path(self):
        async def flow():
            p = await self.start(setup=True)
            denied = OSError(13, "Permission denied", "/home/someone/file")
            with mock.patch.object(main.reshade_install, "_copy", side_effect=denied):
                game = await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            with mock.patch.object(reshade_shaders, "_save_index", side_effect=denied):
                shader = await p.set_package(p.packages[0]["id"], True)
            with mock.patch.object(reshade_release, "extract", side_effect=denied):
                release = await p.set_version("6.5.1")
            with mock.patch.object(main.dk_fs, "write_json", side_effect=denied):
                setting = await p.set_setting("auto_launch_options", False)
            with mock.patch.object(p, "_report", side_effect=denied):
                report = await p.save_report()
            for r in (game, shader, release, setting, report):
                self.assertEqual(r["ok"], False)
                self.assertIn("Permission denied", r["error"])
                self.assertNotIn("someone", r["error"])
            with mock.patch.object(main.reshade_install.dk_fs, "load_json", side_effect=denied):
                problem = main.reshade_install.Manifest(p.manifest.path).problem
            self.assertIn("Permission denied", problem)
            self.assertNotIn("someone", problem)
        self.run_async(flow())


class Stopping(Base):
    def test_unload_cancels_background_work_and_downloads(self):
        async def flow():
            p = await self.start(setup=True)
            started = threading.Event()

            def hanging(*a, cancel=None, **kw):
                started.set()
                while not cancel():
                    threading.Event().wait(0.01)
                raise reshade_release.ReleaseError("cancelled")

            with mock.patch.object(reshade_release, "latest_version",
                                   side_effect=lambda cancel=None: hanging(cancel=cancel)):
                job = asyncio.create_task(p.update_reshade())
                p._spawn(asyncio.sleep(60))
                await asyncio.to_thread(started.wait, 5)
                await p._unload()  # never awaits anything that can hang
                self.assertTrue(p.stopping.is_set())
                await asyncio.wait_for(job, 5)  # the request saw the cancel and the job ended
                await asyncio.sleep(0)
                self.assertFalse(p.tasks)
            r = await p.update_reshade()
            self.assertEqual(r["ok"], False, "no job starts once stopping")
            self.assertFalse((await p.check_for_updates())["ok"])
        self.run_async(flow())

    def test_uninstall_leaves_games_set_up(self):
        async def flow():
            p = await self.start(setup=True)
            await p.enable_game(70, "Game.exe", "dxgi", False, "", "")
            await p._uninstall()
            self.assertTrue(os.path.exists(os.path.join(self.game_dir, "dxgi.dll")))
        self.run_async(flow())

    def test_stops_after_a_failed_start(self):
        async def flow():
            p = main.Plugin()
            with mock.patch.object(main.dk_update, "Updates", side_effect=OSError("no home")):
                with self.assertRaises(OSError):
                    await p._main()
            await p._unload()
            await p._uninstall()
            self.assertTrue(p.stopping.is_set())
        self.run_async(flow())


if __name__ == "__main__":
    unittest.main()
