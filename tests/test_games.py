# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Library scan, executable choice, bitness and API detection."""

import os
import struct
import tempfile
import unittest
from unittest import mock

import _harness  # noqa: F401
import reshade_games as G
from _pe import make_pe


def _write(path, data=b""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _app(root, appid, name, installdir):
    _write(os.path.join(root, "steamapps", f"appmanifest_{appid}.acf"),
           f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{installdir}"\n}}\n'
           .encode())
    os.makedirs(os.path.join(root, "steamapps", "common", installdir), exist_ok=True)
    return os.path.join(root, "steamapps", "common", installdir)


class Scan(unittest.TestCase):
    def test_lists_games_in_all_libraries_without_tools(self):
        steam, sd = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
               f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{steam}"\n}}\n"1"\n{{\n"path" "{sd}"\n}}\n}}\n'
               .replace("\\", "\\\\").encode())
        _app(steam, 10, "Zeta", "Zeta")
        _app(sd, 20, "alpha", "Alpha")
        _app(steam, 1493710, "Proton Experimental", "Proton - Experimental")
        _app(steam, 228980, "Steamworks Common Redistributables", "Steamworks Shared")
        _app(steam, 30, "Escape", "../../outside")
        self.assertEqual([g["appid"] for g in G.scan(steam)], [20, 10])


def _vdf(node):
    """Steam's binary KeyValues for a dict of dicts, strings and ints."""
    out = b""
    for key, value in node.items():
        if isinstance(value, dict):
            out += b"\x00" + key.encode() + b"\0" + _vdf(value) + b"\x08"
        elif isinstance(value, int):
            out += b"\x02" + key.encode() + b"\0" + struct.pack("<i", value)
        else:
            out += b"\x01" + key.encode() + b"\0" + value.encode() + b"\0"
    return out


class Shortcuts(unittest.TestCase):
    def test_windows_shortcuts_with_their_launch_options(self):
        steam, games = tempfile.mkdtemp(), tempfile.mkdtemp()
        eden = os.path.join(games, "Eden", "eden.exe")
        _write(eden, make_pe(64))
        data = _vdf({"shortcuts": {
            "0": {"appid": -1234567890, "AppName": "Eden", "Exe": f'"{eden}"', "StartDir": f'"{games}"',
                  "LaunchOptions": "-fullscreen", "LastPlayTime": 0},
            "1": {"appid": 5, "AppName": "Native", "Exe": '"/usr/bin/retroarch"', "LaunchOptions": ""},
            "2": {"appid": 6, "AppName": "Gone", "Exe": '"/nowhere/game.exe"'},
        }}) + b"\x08"
        _write(os.path.join(steam, "userdata", "123", "config", "shortcuts.vdf"), data)
        _write(os.path.join(steam, "userdata", "456", "config", "shortcuts.vdf"), b"\x00broken")
        found = G.shortcuts(steam)
        self.assertEqual(found, [{"appid": (-1234567890) & 0xFFFFFFFF, "name": "Eden",
                                  "install_dir": os.path.dirname(eden), "exe": "eden.exe", "nonsteam": True,
                                  "launch_options": "-fullscreen"}])
        # the shortcut's own exe is offered first, even when another one looks more like the game
        _write(os.path.join(games, "Eden", "maintenancetool.exe"), make_pe(64, [], b"\0" * 3_000_000))
        self.assertEqual(G.inspect(found[0])["candidates"][0]["exe"], "eden.exe")
        _app(steam, 10, "A Steam game", "Game")
        self.assertEqual([g["name"] for g in G.all_games(steam)], ["A Steam game", "Eden"])


class Executables(unittest.TestCase):
    def test_pe_info_reads_bitness_and_imports(self):
        d = tempfile.mkdtemp()
        _write(os.path.join(d, "a.exe"), make_pe(32, ["KERNEL32.dll", "d3d9.dll"]))
        _write(os.path.join(d, "b.exe"), make_pe(64))
        _write(os.path.join(d, "c.exe"), b"#!/bin/sh\n")
        self.assertEqual(G.pe_info(os.path.join(d, "a.exe")), {"bits": 32, "imports": {"kernel32.dll", "d3d9.dll"}})
        self.assertEqual(G.pe_info(os.path.join(d, "b.exe")), {"bits": 64, "imports": set()})
        self.assertIsNone(G.pe_info(os.path.join(d, "c.exe")))
        self.assertIsNone(G.pe_info(os.path.join(d, "missing.exe")))

    def test_detect_api(self):
        d = tempfile.mkdtemp()
        cases = {
            "dx11.exe": (make_pe(64, ["d3d11.dll", "dxgi.dll"]), ("dxgi", "imports")),
            "dx9.exe": (make_pe(32, ["d3d9.dll"]), ("d3d9", "imports")),
            "dx8.exe": (make_pe(32, ["d3d8.dll"]), ("d3d9", "imports")),  # through DXVK's d3d8 on d3d9
            "gl.exe": (make_pe(64, ["OPENGL32.dll"]), ("opengl32", "imports")),
            # links OpenGL as a fallback but loads Direct3D 11 at run time (Unity's UnityPlayer.dll does this)
            "fallback.exe": (make_pe(64, ["OPENGL32.dll"], b"\0" * 100 + b"d3d11.dll\0dxgi.dll\0"), ("dxgi", "strings")),
            # imports d3d9 for side jobs but renders with DirectX 12 (Red Dead Redemption 2 does this)
            "dx12d3d9.exe": (make_pe(64, ["d3d9.dll"], b"d3d12.dll\0dxgi.dll\0"), ("dxgi", "strings")),
            # loads Direct3D at run time: only the name appears in the file
            "dynamic.exe": (make_pe(64, [], b"\0" * 5000 + b"D3D9.DLL\0"), ("d3d9", "strings")),
            "vk.exe": (make_pe(64, ["vulkan-1.dll"]), ("vulkan", "imports")),
            "unknown.exe": (make_pe(64), ("dxgi", "default")),
        }
        for name, (data, want) in cases.items():
            _write(os.path.join(d, name), data)
            self.assertEqual(G.detect_api(os.path.join(d, name)), want, name)

    def test_engine_dll_beside_a_silent_exe(self):
        d = tempfile.mkdtemp()
        _write(os.path.join(d, "Hades.exe"), make_pe(64, ["kernel32.dll"]))
        _write(os.path.join(d, "EngineWin64s.dll"), make_pe(64, ["d3d11.dll"]))
        _write(os.path.join(d, "opengl32.dll"), make_pe(64, ["vulkan-1.dll"]))  # one of ours: never evidence
        self.assertEqual(G.detect_api(os.path.join(d, "Hades.exe")), ("dxgi", "imports"))

    def test_unity_player_is_read_with_the_launcher(self):
        d = tempfile.mkdtemp()
        _write(os.path.join(d, "Game.exe"), make_pe(64, ["kernel32.dll"]))
        _write(os.path.join(d, "UnityPlayer.dll"), make_pe(64, ["d3d11.dll"]))
        self.assertEqual(G.detect_api(os.path.join(d, "Game.exe")), ("dxgi", "imports"))

    def test_mentions_finds_names_across_chunk_borders(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "big.exe")
        _write(path, b"\0" * ((1 << 22) - 4) + b"d3d9.dll")
        self.assertEqual(G._mentions(path, (b"d3d9.dll",)), {b"d3d9.dll"})

    def test_inspect_prefers_the_real_game_binary(self):
        root = tempfile.mkdtemp()
        install = _app(root, 1, "Big Game", "BigGame")
        _write(os.path.join(install, "BigGame.exe"), make_pe(64, [], b"\0" * 200_000))  # Unreal's bootstrap
        _write(os.path.join(install, "Game", "Binaries", "Win64", "BigGame-Win64-Shipping.exe"), make_pe(64))
        _write(os.path.join(install, "unins000.exe"), make_pe(32, [], b"\0" * 5_000_000))
        _write(os.path.join(install, "_CommonRedist", "vcredist_x64.exe"), make_pe(64))
        _write(os.path.join(install, "EasyAntiCheat", "EasyAntiCheat_EOS_Setup.exe"), make_pe(64))
        found = G.inspect({"name": "Big Game", "install_dir": install})
        exes = [c["exe"] for c in found["candidates"]]
        self.assertEqual(exes[0], "Game/Binaries/Win64/BigGame-Win64-Shipping.exe")
        self.assertEqual(exes[-1], "unins000.exe")  # listed, but last
        self.assertNotIn("_CommonRedist/vcredist_x64.exe", exes)
        self.assertTrue(found["anticheat"])

    def test_inspect_prefers_the_running_exe(self):
        root = tempfile.mkdtemp()
        install = _app(root, 1, "Hades", "Hades")
        _write(os.path.join(install, "x64", "Hades.exe"), make_pe(64))
        _write(os.path.join(install, "x64Vk", "Hades.exe"), make_pe(64, [], b"\0" * 3_000_000))
        _write(os.path.join(install, "Content", "SFXCharacterClass_Vanguard.pcc"), b"")  # not an anti-cheat
        with mock.patch.object(G, "running_exes", return_value={"s:/steamapps/common/hades/x64/hades.exe"}):
            found = G.inspect({"name": "Hades", "install_dir": install})
        self.assertEqual(found["candidates"][0], {"exe": "x64/Hades.exe", "bits": 64, "running": True})
        # another game's x64/Hades.exe running does not count
        with mock.patch.object(G, "running_exes", return_value={"s:/steamapps/common/other/x64/hades.exe"}):
            self.assertNotIn("running", G.inspect({"name": "Hades", "install_dir": install})["candidates"][0])
        self.assertFalse(found["anticheat"])
        # not running: the DirectX build still comes before the bigger Vulkan one
        with mock.patch.object(G, "running_exes", return_value=set()):
            self.assertEqual(G.inspect({"name": "Hades", "install_dir": install})["candidates"][0]["exe"], "x64/Hades.exe")

    def test_inspect_matches_the_game_name(self):
        root = tempfile.mkdtemp()
        install = _app(root, 1, "Hollow Knight", "Hollow Knight")
        _write(os.path.join(install, "hollow_knight.exe"), make_pe(64))
        _write(os.path.join(install, "tool.exe"), make_pe(64, [], b"\0" * 2_000_000))
        found = G.inspect({"name": "Hollow Knight", "install_dir": install})
        self.assertEqual(found["candidates"][0], {"exe": "hollow_knight.exe", "bits": 64})
        self.assertFalse(found["anticheat"])


if __name__ == "__main__":
    unittest.main()
