# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Launch option merging, install/rollback safety, ReShade.ini handling and updates of installed games."""

import os
import tempfile
import time
import unittest

import _harness  # noqa: F401
import reshade_install as I

OURS = I.our_overrides("dxgi")
FSR4 = "WINEDLLOVERRIDES=amdxc64=n,b"  # what FSR4 Injector puts in front of %command%


class LaunchOptions(unittest.TestCase):
    def test_round_trip(self):
        for original in ("", "%command% -dx12", "gamemoderun %command%", "-skipintro", f"{FSR4} %command%",
                         'WINEDLLOVERRIDES="xinput1_3=n,b;dinput8=n,b" mangohud %command%'):
            applied = I.with_overrides(original, OURS)
            self.assertIn("%command%", applied.split())
            self.assertIn("d3dcompiler_47=n,b;dxgi=n,b", applied)
            self.assertEqual(I.without_overrides(applied, original, applied, OURS), original, original)

    def test_merges_into_an_existing_override(self):
        self.assertEqual(I.with_overrides(f"{FSR4} %command%", OURS),
                         'WINEDLLOVERRIDES="amdxc64=n,b;d3dcompiler_47=n,b;dxgi=n,b" %command%')
        self.assertEqual(I.with_overrides("-skipintro", OURS),
                         'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command% -skipintro')
        # our own entries replace a different mode for the same DLL instead of piling up
        self.assertEqual(I.with_overrides('WINEDLLOVERRIDES="dxgi=b" %command%', OURS),
                         'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command%')
        # also when the DLL is in a list sharing one mode: the rest of the list keeps it
        self.assertEqual(I.with_overrides('WINEDLLOVERRIDES="dxgi,d3d11,winmm=b" %command%', OURS),
                         'WINEDLLOVERRIDES="d3d11,winmm=b;d3dcompiler_47=n,b;dxgi=n,b" %command%')

    def test_edited_since_only_our_entries_go(self):
        original = f"{FSR4} %command%"
        applied = I.with_overrides(original, OURS)
        edited = "mangohud " + applied + " -windowed"
        # FSR4 Injector's token comes back exactly as it wrote it, so it still recognises it
        self.assertEqual(I.without_overrides(edited, original, applied, OURS), f"mangohud {FSR4} %command% -windowed")

    def test_users_own_entry_survives(self):
        original = 'WINEDLLOVERRIDES="d3dcompiler_47=n" %command%'
        applied = I.with_overrides(original, OURS)
        self.assertEqual(I.without_overrides(applied + " -x", original, applied, OURS),
                         "WINEDLLOVERRIDES=d3dcompiler_47=n %command% -x")

    def test_users_list_entry_comes_back_for_our_dll(self):
        original = 'WINEDLLOVERRIDES="dxgi,d3d11=b" %command%'
        applied = I.with_overrides(original, OURS)
        self.assertEqual(I.without_overrides("mangohud " + applied, original, applied, OURS),
                         'mangohud WINEDLLOVERRIDES="d3d11=b;dxgi=b" %command%')

    def test_autohdr_variable_round_trip(self):
        env = ["DXVK_HDR=1"]
        for original in ("", "-novid", "DXVK_HDR=0 %command%", f"{FSR4} mangohud %command%"):
            applied = I.with_overrides(original, OURS, env)
            self.assertEqual(applied.split().count("DXVK_HDR=1"), 1, applied)
            self.assertNotIn("DXVK_HDR=0", applied)
            self.assertEqual(I.without_overrides(applied, original, applied, OURS, env), original)
            # edited since: our variable goes, the user's own value comes back
            edited = applied + " -x"
            back = I.without_overrides(edited, original, applied, OURS, env)
            self.assertNotIn("DXVK_HDR=1", back)
            self.assertEqual("DXVK_HDR=0" in back, "DXVK_HDR=0" in original, back)

    def test_decky_launch_options(self):
        for options in ("~/.dlo/run %command%", "/home/deck/.dlo/run %command% -novid"):
            self.assertTrue(I.dlo_managed(options), options)
        for options in ("", "%command% ~/.dlo/running", "gamemoderun %command%"):
            self.assertFalse(I.dlo_managed(options), options)
        self.assertEqual(I.launch_word("d3d9"), 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;d3d9=n,b"')
        # what Decky Launch Options keeps after it took over a game we had set up
        self.assertEqual(I.dlo_leftover('WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command%'),
                         'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b"')
        for clean in ("", "%command%", 'WINEDLLOVERRIDES="xinput1_3=n,b" %command%', "WINEDLLOVERRIDES=dxgi=n,b %command%"):
            self.assertEqual(I.dlo_leftover(clean), "", clean)


class Ini(unittest.TestCase):
    def test_new_ini_points_at_the_shared_shaders(self):
        text = I.ini_text("/home/deck/homebrew/data/DeckyReshade/shaders")
        self.assertIn("EffectSearchPaths=Z:\\home\\deck\\homebrew\\data\\DeckyReshade\\shaders\\Shaders\\**", text)
        self.assertIn("TextureSearchPaths=Z:\\home\\deck\\homebrew\\data\\DeckyReshade\\shaders\\Textures\\**", text)

    def test_existing_ini_keeps_the_users_paths_and_settings(self):
        text = "[GENERAL]\nEffectSearchPaths=.\\reshade-shaders\\Shaders\\**\nPreset=x\n[INPUT]\nKeyOverlay=36,0,0,0\n"
        updated = I.with_shader_paths(text, "/s")
        self.assertIn("EffectSearchPaths=.\\reshade-shaders\\Shaders\\**,Z:\\s\\Shaders\\**", updated)
        self.assertIn("[GENERAL]\nTextureSearchPaths=Z:\\s\\Textures\\**\n", updated)
        self.assertIn("KeyOverlay=36,0,0,0", updated)
        self.assertEqual(I.with_shader_paths(updated, "/s"), updated)  # nothing added twice
        self.assertTrue(I.with_shader_paths("", "/s").startswith("[GENERAL]\nEffectSearchPaths=Z:\\s\\Shaders\\**"))


def _file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class InstallRollback(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp()
        self.manifest = I.Manifest(os.path.join(base, "manifest.json"))
        self.install_dir = os.path.join(base, "common", "Game")
        self.target = os.path.join(self.install_dir, "bin")
        _file(os.path.join(self.target, "game.exe"), b"exe")
        self.shaders = os.path.join(base, "shaders")
        self.src = {"dxgi.dll": _file(os.path.join(base, "data", "ReShade64.dll"), b"reshade 1"),
                    I.COMPILER: _file(os.path.join(base, "data", "d3dcompiler_47.64.dll"), b"compiler")}
        self.game = {"appid": 7, "name": "Game", "install_dir": self.install_dir}

    def enable(self, options="", **kw):
        return I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, self.src, self.shaders, options, **kw)

    def test_enable_then_disable_restores_the_folder_but_keeps_settings(self):
        options = self.enable("%command% -dx11")
        self.assertEqual(options, 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" %command% -dx11')
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", "d3dcompiler_47.dll", "dxgi.dll", "game.exe"])
        _file(os.path.join(self.target, I.LOG), b"log")
        res = I.disable(self.manifest, 7, options)
        self.assertEqual(res, {"launch_options": "%command% -dx11", "kept": []})
        # settings and the log (why it did not work) stay
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", "ReShade.log", "game.exe"])
        self.assertEqual(I.Manifest(self.manifest.path).entries, {})

    def test_autohdr_adds_its_addon_variable_and_a_first_preset(self):
        src = dict(self.src, **{"AutoHDR.addon64": _file(self.src["dxgi.dll"] + ".addon", b"addon")})
        options = I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, src, self.shaders, "",
                           env=["DXVK_HDR=1"], preset=I.autohdr_preset())
        self.assertEqual(options, 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b" DXVK_HDR=1 %command%')
        with open(os.path.join(self.target, I.PRESET)) as f:
            self.assertIn("AdvancedAutoHDR@AdvancedAutoHDR.fx", f.read())
        self.assertEqual(I.disable(self.manifest, 7, options + " -x")["launch_options"], "%command% -x")
        self.assertFalse(os.path.exists(os.path.join(self.target, "AutoHDR.addon64")))
        # the first preset goes with AutoHDR while untouched, or AdvancedAutoHDR would keep running without it
        self.assertFalse(os.path.exists(os.path.join(self.target, I.PRESET)))
        I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, src, self.shaders, "",
                 env=["DXVK_HDR=1"], preset=I.autohdr_preset())
        _file(os.path.join(self.target, I.PRESET), b"Techniques=AdvancedAutoHDR@AdvancedAutoHDR.fx,Mine@Mine.fx")
        self.assertEqual(I.disable(self.manifest, 7, "")["kept"], [I.PRESET])  # edited: the user's now
        # a preset the user already has is never replaced
        _file(os.path.join(self.target, I.PRESET), b"Techniques=Mine@Mine.fx")
        I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, src, self.shaders, "",
                 env=["DXVK_HDR=1"], preset=I.autohdr_preset())
        with open(os.path.join(self.target, I.PRESET), "rb") as f:
            self.assertEqual(f.read(), b"Techniques=Mine@Mine.fx")

    def test_apostrophe_in_an_argument_is_no_quote(self):
        self.assertIn("-name=Rayek's", self.enable("-name=Rayek's"))

    def test_quoted_text_with_spaces_is_refused_before_anything_is_written(self):
        for options in ('WINEDLLOVERRIDES="winmm=n,b; version=n,b" %command%',
                        "WINEDLLOVERRIDES='winmm=n,b; version=n,b' %command%"):
            with self.assertRaises(I.InstallError):
                self.enable(options)
        with self.assertRaises(I.InstallError):
            self.enable('WINEDLLOVERRIDES="winmm=n,b; version=n,b" %command%')
        self.assertEqual(os.listdir(self.target), ["game.exe"])
        self.assertEqual(self.manifest.entries, {})

    def test_folder_gone_keeps_the_game_set_up(self):
        options = self.enable()
        os.rename(self.target, self.target + ".away")  # its SD card taken out
        with self.assertRaises(I.InstallError):
            I.disable(self.manifest, 7, options)
        self.assertIn(7, self.manifest.entries)
        os.rename(self.target + ".away", self.target)
        I.disable(self.manifest, 7, options)
        self.assertFalse(os.path.exists(os.path.join(self.target, "dxgi.dll")))

    def test_foreign_dll_stops_the_install(self):
        _file(os.path.join(self.target, "dxgi.dll"), b"another reshade")
        with self.assertRaises(I.InstallError):
            self.enable()
        self.assertEqual(self.manifest.entries, {})

    def test_games_own_compiler_is_used_and_never_removed(self):
        _file(os.path.join(self.target, I.COMPILER), b"the game's own")
        options = self.enable()
        self.assertNotIn(I.COMPILER, self.manifest.entries[7]["files"])
        I.disable(self.manifest, 7, options)
        with open(os.path.join(self.target, I.COMPILER), "rb") as f:
            self.assertEqual(f.read(), b"the game's own")

    def test_changed_file_is_kept_on_disable(self):
        options = self.enable()
        _file(os.path.join(self.target, "dxgi.dll"), b"replaced by the user")
        self.assertEqual(I.disable(self.manifest, 7, options)["kept"], ["dxgi.dll"])

    def test_without_auto_launch_options_they_are_left_alone(self):
        self.assertEqual(self.enable("-x", launch=False), "-x")
        self.assertEqual(I.disable(self.manifest, 7, "-x")["launch_options"], "-x")

    def test_enabling_again_is_harmless_and_another_api_is_refused(self):
        first = self.enable("-x")
        self.assertEqual(self.enable(first), first)
        self.assertEqual(self.manifest.entries[7]["launch_original"], "-x")
        with self.assertRaises(I.InstallError):
            I.enable(self.manifest, self.game, "bin/game.exe", "d3d9", 64, self.src, self.shaders, first)

    def test_refresh_updates_only_files_still_ours(self):
        self.enable()
        other = dict(self.game, appid=8, install_dir=self.install_dir + "2")
        _file(os.path.join(other["install_dir"], "game.exe"), b"exe")
        I.enable(self.manifest, other, "game.exe", "dxgi", 64, self.src, self.shaders, "")
        _file(os.path.join(other["install_dir"], "dxgi.dll"), b"user's own build")
        new = {"dxgi.dll": _file(self.src["dxgi.dll"] + ".new", b"reshade 2"), I.COMPILER: self.src[I.COMPILER]}
        self.assertEqual(I.refresh(self.manifest, lambda e: new), 1)
        with open(os.path.join(self.target, "dxgi.dll"), "rb") as f:
            self.assertEqual(f.read(), b"reshade 2")
        with open(os.path.join(other["install_dir"], "dxgi.dll"), "rb") as f:
            self.assertEqual(f.read(), b"user's own build")
        # after the update the new file counts as ours, so disabling still removes it
        I.disable(self.manifest, 7, "")
        self.assertFalse(os.path.exists(os.path.join(self.target, "dxgi.dll")))

    def test_loaded_since_reads_the_log_time(self):
        self.enable()
        entry = self.manifest.entries[7]
        start = time.time()
        self.assertFalse(I.loaded_since(entry, start))
        _file(os.path.join(self.target, I.LOG), b"log")
        self.assertTrue(I.loaded_since(entry, start))


if __name__ == "__main__":
    unittest.main()
