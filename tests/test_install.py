# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Wine DLL overrides in a game's prefix, install/rollback safety, ReShade.ini handling and updates of installed
games."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import _harness  # noqa: F401
import reshade_install as I

# a prefix's user.reg as Proton leaves it, with a section of its own for another game
REG = r"""WINE REGISTRY Version 2
;; All keys relative to \\User\\S-1-5-21-0-0-0-1000

#arch=win64

[Software\\Wine\\AppDefaults\\Gotg.exe\\DllOverrides] 1749140924
#time=1dbd6f7a2f9a1b8
"atiadlxx"="builtin"

[Volatile Environment] 1793715343
"USERPROFILE"="C:\\users\\steamuser"
"""


def _prefix(text=REG):
    prefix = tempfile.mkdtemp()
    _file(os.path.join(prefix, "pfx", I.REGISTRY), text.encode())
    return prefix


def _reg(prefix):
    with open(os.path.join(prefix, "pfx", I.REGISTRY), encoding="utf-8", newline="") as f:
        return f.read()


class WineSettings(unittest.TestCase):
    def test_a_new_section_goes_and_leaves_the_file_as_it_was(self):
        prefix = _prefix()
        self.assertTrue(I.set_dll_override(prefix, "isaac-ng.exe", "opengl32"))
        text = _reg(prefix)
        self.assertTrue(text.startswith(REG))
        self.assertRegex(text[len(REG):], r'^\n\[Software\\\\Wine\\\\AppDefaults\\\\isaac-ng\.exe\\\\DllOverrides\] '
                                          r'\d+\n"opengl32"="native,builtin"\n$')
        I.remove_dll_override(prefix, "isaac-ng.exe", "opengl32")
        self.assertEqual(_reg(prefix), REG)

    def test_an_existing_section_keeps_what_proton_put_there(self):
        prefix = _prefix()
        self.assertTrue(I.set_dll_override(prefix, "gotg.exe", "d3d10"))  # Wine ignores the case of the name
        self.assertIn('"atiadlxx"="builtin"\n"d3d10"="native,builtin"\n\n[Volatile', _reg(prefix))
        I.remove_dll_override(prefix, "gotg.exe", "d3d10")
        self.assertEqual(_reg(prefix), REG)

    def test_the_users_own_setting_is_left_alone(self):
        own = REG.replace('"atiadlxx"="builtin"', '"atiadlxx"="builtin"\n"opengl32"="builtin"')
        prefix = _prefix(own)
        with self.assertRaises(I.InstallError):
            I.set_dll_override(prefix, "Gotg.exe", "opengl32")
        self.assertEqual(_reg(prefix), own)
        # already set the way we would: not ours, so never taken out
        same = REG.replace('"atiadlxx"="builtin"', '"opengl32"="native,builtin"')
        prefix = _prefix(same)
        self.assertFalse(I.set_dll_override(prefix, "Gotg.exe", "opengl32"))
        self.assertEqual(_reg(prefix), same)

    def test_changed_since_or_gone_stays_as_it_is(self):
        prefix = _prefix()
        I.set_dll_override(prefix, "game.exe", "opengl32")
        edited = _reg(prefix).replace('"opengl32"="native,builtin"', '"opengl32"="native"')
        _file(os.path.join(prefix, "pfx", I.REGISTRY), edited.encode())
        I.remove_dll_override(prefix, "game.exe", "opengl32")
        self.assertEqual(_reg(prefix), edited)
        os.remove(os.path.join(prefix, "pfx", I.REGISTRY))  # the prefix was deleted
        I.remove_dll_override(prefix, "game.exe", "opengl32")

    def test_a_name_wine_would_escape_is_refused(self):
        prefix = _prefix()
        for exe in ("Spiel\u00e4.exe", "a]b.exe", 'a"b.exe'):
            with self.assertRaises(I.InstallError):
                I.set_dll_override(prefix, exe, "opengl32")
        self.assertEqual(_reg(prefix), REG)

    def test_the_prefix_of_a_steam_game_and_of_a_shortcut(self):
        steam, sd = tempfile.mkdtemp(), tempfile.mkdtemp()
        game = {"appid": 70, "install_dir": os.path.join(sd, "steamapps", "common", "Game")}
        self.assertEqual(I.wine_prefix(game, steam), "")  # never started
        _file(os.path.join(sd, "steamapps", "compatdata", "70", "pfx", I.REGISTRY), b"")
        self.assertEqual(I.wine_prefix(game, steam), os.path.join(sd, "steamapps", "compatdata", "70"))
        shortcut = {"appid": 99, "install_dir": sd, "nonsteam": True}
        _file(os.path.join(steam, "steamapps", "compatdata", "99", "pfx", I.REGISTRY), b"")
        self.assertEqual(I.wine_prefix(shortcut, steam), os.path.join(steam, "steamapps", "compatdata", "99"))

    @unittest.skipUnless(os.path.isdir("/proc/self"), "reads /proc")
    def test_a_process_in_the_prefix_is_seen(self):
        prefix = _prefix()
        self.assertFalse(I.prefix_in_use(prefix))
        env = dict(os.environ, STEAM_COMPAT_DATA_PATH=prefix)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], env=env)
        try:
            self.assertTrue(I.prefix_in_use(prefix))
        finally:
            child.kill()
            child.wait()

    def test_launch_options_for_the_user_to_paste(self):
        self.assertEqual(I.launch_options("d3d9"), 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;d3d9=n,b" %command%')


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

    def enable(self, **kw):
        I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, self.src, self.shaders, **kw)

    def enable_opengl(self, prefix):
        src = {"opengl32.dll": self.src["dxgi.dll"], I.COMPILER: self.src[I.COMPILER]}
        I.enable(self.manifest, self.game, "bin/game.exe", "opengl32", 64, src, self.shaders, prefix)

    def test_enable_then_disable_restores_the_folder_but_keeps_settings(self):
        self.enable()
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", "d3dcompiler_47.dll", "dxgi.dll", "game.exe"])
        self.assertNotIn("wine", self.manifest.entries[7])
        _file(os.path.join(self.target, I.LOG), b"log")
        self.assertEqual(I.disable(self.manifest, 7), [])
        # settings and the log (why it did not work) stay
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", "ReShade.log", "game.exe"])
        self.assertEqual(I.Manifest(self.manifest.path).entries, {})

    def test_opengl_gets_a_wine_setting_that_goes_with_it(self):
        prefix = _prefix()
        self.enable_opengl(prefix)
        self.assertIn('AppDefaults\\\\game.exe\\\\DllOverrides', _reg(prefix))
        self.assertEqual(I.Manifest(self.manifest.path).entries[7]["wine"],
                         {"prefix": prefix, "exe": "game.exe", "dll": "opengl32"})
        self.enable_opengl(prefix)  # again: still one setting
        self.assertEqual(_reg(prefix).count('"opengl32"'), 1)
        self.assertEqual(I.disable(self.manifest, 7), [])
        self.assertEqual(_reg(prefix), REG)
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", "game.exe"])

    def test_a_running_game_keeps_its_wine_settings_untouched(self):
        prefix = _prefix()
        with mock.patch.object(I, "prefix_in_use", return_value=True):
            with self.assertRaises(I.InstallError):
                self.enable_opengl(prefix)
        self.assertEqual((os.listdir(self.target), self.manifest.entries, _reg(prefix)), (["game.exe"], {}, REG))
        self.enable_opengl(prefix)
        with mock.patch.object(I, "prefix_in_use", return_value=True):
            with self.assertRaises(I.InstallError):
                I.disable(self.manifest, 7)
        self.assertIn("wine", self.manifest.entries[7])
        self.assertIn("opengl32.dll", os.listdir(self.target))

    def test_a_foreign_dll_stops_the_install_before_wine_is_changed(self):
        prefix = _prefix()
        _file(os.path.join(self.target, "opengl32.dll"), b"another reshade")
        with self.assertRaises(I.InstallError):
            self.enable_opengl(prefix)
        self.assertEqual((self.manifest.entries, _reg(prefix)), ({}, REG))

    def test_autohdr_adds_its_addon_and_a_first_preset(self):
        src = dict(self.src, **{"AutoHDR.addon64": _file(self.src["dxgi.dll"] + ".addon", b"addon")})

        def enable():
            I.enable(self.manifest, self.game, "bin/game.exe", "dxgi", 64, src, self.shaders,
                     preset=I.autohdr_preset())

        enable()
        with open(os.path.join(self.target, I.PRESET)) as f:
            self.assertIn("AdvancedAutoHDR@AdvancedAutoHDR.fx", f.read())
        I.disable(self.manifest, 7)
        self.assertFalse(os.path.exists(os.path.join(self.target, "AutoHDR.addon64")))
        # the first preset goes with AutoHDR while untouched, or AdvancedAutoHDR would keep running without it
        self.assertFalse(os.path.exists(os.path.join(self.target, I.PRESET)))
        enable()
        _file(os.path.join(self.target, I.PRESET), b"Techniques=AdvancedAutoHDR@AdvancedAutoHDR.fx,Mine@Mine.fx")
        self.assertEqual(I.disable(self.manifest, 7), [I.PRESET])  # edited: the user's now
        # a preset the user already has is never replaced
        _file(os.path.join(self.target, I.PRESET), b"Techniques=Mine@Mine.fx")
        enable()
        with open(os.path.join(self.target, I.PRESET), "rb") as f:
            self.assertEqual(f.read(), b"Techniques=Mine@Mine.fx")

    def test_an_sd_card_taken_out_keeps_the_game_set_up(self):
        self.enable()
        library = os.path.dirname(self.install_dir)
        os.rename(library, library + ".away")  # the whole library is gone with the card
        with self.assertRaises(I.InstallError):
            I.disable(self.manifest, 7)
        self.assertEqual(I.follow_moved(self.manifest, [], "/no-steam"), [])
        self.assertIn(7, self.manifest.entries)
        os.rename(library + ".away", library)
        I.disable(self.manifest, 7)
        self.assertFalse(os.path.exists(os.path.join(self.target, "dxgi.dll")))

    def test_an_uninstalled_game_is_forgotten(self):
        prefix = _prefix()
        self.enable_opengl(prefix)
        shutil.rmtree(self.install_dir)  # Steam uninstalled it; the library is still there
        self.assertEqual(I.disable(self.manifest, 7), [])
        self.assertEqual((I.Manifest(self.manifest.path).entries, _reg(prefix)), ({}, REG))
        # found by the library check too, without turning it off
        os.makedirs(self.target)
        _file(os.path.join(self.target, "game.exe"), b"exe")
        self.enable()
        shutil.rmtree(self.install_dir)
        self.assertEqual(I.follow_moved(self.manifest, [], "/no-steam"), ["Game is no longer installed"])
        self.assertEqual(self.manifest.entries, {})

    def test_a_moved_game_is_followed_to_its_new_library(self):
        steam = tempfile.mkdtemp()
        old_prefix = os.path.join(steam, "steamapps", "compatdata", "7")
        _file(os.path.join(old_prefix, "pfx", I.REGISTRY), REG.encode())
        self.enable_opengl(old_prefix)
        # Steam's Move install folder: the game, our files with it, and its prefix
        sd = tempfile.mkdtemp()
        moved = os.path.join(sd, "steamapps", "common", "Game")
        shutil.move(self.install_dir, moved)
        shutil.move(old_prefix, os.path.join(sd, "steamapps", "compatdata", "7"))
        game = dict(self.game, install_dir=moved)
        self.assertEqual(len(I.follow_moved(self.manifest, [game], steam)), 1)
        entry = I.Manifest(self.manifest.path).entries[7]
        self.assertEqual((entry["target_dir"], entry["wine"]["prefix"]),
                         (os.path.join(moved, "bin"), os.path.join(sd, "steamapps", "compatdata", "7")))
        self.assertEqual(I.disable(self.manifest, 7), [])
        self.assertEqual(sorted(os.listdir(os.path.join(moved, "bin"))), ["ReShade.ini", "game.exe"])
        self.assertEqual(_reg(os.path.join(sd, "steamapps", "compatdata", "7")), REG)

    def test_foreign_dll_stops_the_install(self):
        _file(os.path.join(self.target, "dxgi.dll"), b"another reshade")
        with self.assertRaises(I.InstallError):
            self.enable()
        self.assertEqual(self.manifest.entries, {})

    def test_games_own_compiler_is_used_and_never_removed(self):
        _file(os.path.join(self.target, I.COMPILER), b"the game's own, with vs_5_1")
        self.enable()
        self.assertNotIn(I.COMPILER, self.manifest.entries[7]["files"])
        I.disable(self.manifest, 7)
        with open(os.path.join(self.target, I.COMPILER), "rb") as f:
            self.assertEqual(f.read(), b"the game's own, with vs_5_1")

    def test_a_compiler_too_old_for_directx_12_is_set_aside_and_put_back(self):
        compiler, backup = os.path.join(self.target, I.COMPILER), os.path.join(self.target, I.COMPILER + I.BACKUP)
        _file(compiler, b"Windows 8.1's, vs_5_0 at most")
        self.enable()
        with open(compiler, "rb") as f:
            self.assertEqual(f.read(), b"compiler")  # ours
        with open(backup, "rb") as f:
            self.assertEqual(f.read(), b"Windows 8.1's, vs_5_0 at most")
        self.assertEqual(list(I.Manifest(self.manifest.path).entries[7]["backups"]), [I.COMPILER])
        self.enable()  # again: nothing more set aside
        self.assertEqual(I.disable(self.manifest, 7), [])
        self.assertEqual(sorted(os.listdir(self.target)), ["ReShade.ini", I.COMPILER, "game.exe"])
        with open(compiler, "rb") as f:
            self.assertEqual(f.read(), b"Windows 8.1's, vs_5_0 at most")

    def test_a_compiler_the_game_put_back_itself_stays(self):
        compiler, backup = os.path.join(self.target, I.COMPILER), os.path.join(self.target, I.COMPILER + I.BACKUP)
        _file(compiler, b"old")
        self.enable()
        _file(compiler, b"old")  # a game update or Steam's file check
        self.assertEqual(I.disable(self.manifest, 7), [])
        self.assertFalse(os.path.exists(backup))
        with open(compiler, "rb") as f:
            self.assertEqual(f.read(), b"old")
        # a backup that is something else is not overwritten
        _file(backup, b"not the game's")
        with self.assertRaises(I.InstallError):
            self.enable()
        with open(compiler, "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_changed_file_is_kept_on_disable(self):
        self.enable()
        _file(os.path.join(self.target, "dxgi.dll"), b"replaced by the user")
        self.assertEqual(I.disable(self.manifest, 7), ["dxgi.dll"])

    def test_enabling_again_is_harmless_and_another_api_is_refused(self):
        self.enable()
        self.enable()
        self.assertEqual(sorted(self.manifest.entries[7]["files"]), [I.COMPILER, "dxgi.dll"])
        with self.assertRaises(I.InstallError):
            I.enable(self.manifest, self.game, "bin/game.exe", "d3d9", 64, self.src, self.shaders)

    def test_refresh_updates_only_files_still_ours(self):
        self.enable()
        other = dict(self.game, appid=8, install_dir=self.install_dir + "2")
        _file(os.path.join(other["install_dir"], "game.exe"), b"exe")
        I.enable(self.manifest, other, "game.exe", "dxgi", 64, self.src, self.shaders)
        _file(os.path.join(other["install_dir"], "dxgi.dll"), b"user's own build")
        new = {"dxgi.dll": _file(self.src["dxgi.dll"] + ".new", b"reshade 2"), I.COMPILER: self.src[I.COMPILER]}
        self.assertEqual(I.refresh(self.manifest, lambda e: new), 1)
        with open(os.path.join(self.target, "dxgi.dll"), "rb") as f:
            self.assertEqual(f.read(), b"reshade 2")
        with open(os.path.join(other["install_dir"], "dxgi.dll"), "rb") as f:
            self.assertEqual(f.read(), b"user's own build")
        # after the update the new file counts as ours, so disabling still removes it
        I.disable(self.manifest, 7)
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
