# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Installed Steam games, their Windows executables, and what each one needs from ReShade.

ReShade goes next to the executable that actually renders (Windows looks for a DLL in the program's own folder
first), as a 32- or 64-bit DLL to match it, named after the graphics API the game loads. All three are read from the
executable itself: the bitness from its PE header, the API from its import table, else from the DLL names it
mentions (games that load Direct3D at run time). The user can override both choices in the panel.
"""

import os
import re
import struct

MACHINE_BITS = {0x14C: 32, 0x8664: 64}
# Proxy DLL names ReShade can run as (it exports their entry points), in the order the panel lists them. dinput8 is a
# loader of last resort: ReShade then hooks whichever graphics API the game uses.
APIS = ("dxgi", "d3d9", "d3d10", "d3d11", "d3d12", "opengl32", "dinput8")
# The APIs that present through DXGI, the only ones the AutoHDR add-on can switch to HDR.
DXGI_APIS = ("dxgi", "d3d10", "d3d11", "d3d12")
# Lower-case name fragments of anti-cheat files and folders: EAC, BattlEye, XIGNCODE, nProtect GameGuard, PunkBuster,
# EQU8. Not "vanguard": Riot's lives outside game folders, and the word names game files (Mass Effect's Vanguard class).
ANTICHEAT = ("easyanticheat", "battleye", "beservice", "start_protected_game.exe", "eac_launcher",
             "xigncode", "gameguard", "npgamemon", "punkbuster", "pbsvc", "equ8")
# Executables that are rarely the game: installers, redistributables, crash reporters, anti-cheat bootstrappers.
NOT_GAME = re.compile(r"unins|setup|install|redist|vcredist|dxsetup|directx|dotnet|crash|report|helper|"
                      r"easyanticheat|battleye|start_protected|eac_launcher|cefprocess|webhelper|ue4prereq|"
                      r"touchup|cleanup|activation|benchmark|server", re.I)
SKIP_DIRS = {"_commonredist", "__installer", "redist", "redistributables", "directx", "dotnetfx", "vcredist",
             "support", "thirdparty", "easyanticheat", "battleye", "prereqs", "__macosx"}
# Steam's own tools show up as installed apps too.
TOOLS = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common Redistributables|SteamVR)", re.I)
MAX_DEPTH = 6
MAX_CANDIDATES = 12
SCAN_LIMIT = 256 << 20

_KV = re.compile(r'"([^"]+)"\s+"([^"]*)"')


def _values(text, key):
    return [v for k, v in _KV.findall(text) if k.lower() == key]


def libraries(steam_root):
    """Steam library roots, the main one first."""
    roots = [steam_root]
    try:
        with open(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return roots
    for path in _values(text, "path"):
        path = path.replace("\\\\", "\\")
        if os.path.realpath(path) not in map(os.path.realpath, roots):
            roots.append(path)
    return roots


def scan(steam_root):
    """Installed Steam apps that are not Steam tools, sorted by name: {appid, name, install_dir}.

    Cheap on purpose (manifests only); executables are looked at when a game is picked.
    """
    games = {}
    for lib in libraries(steam_root):
        apps = os.path.join(lib, "steamapps")
        try:
            manifests = [n for n in os.listdir(apps) if n.startswith("appmanifest_") and n.endswith(".acf")]
        except OSError:
            continue
        for name in manifests:
            try:
                with open(os.path.join(apps, name), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            appid, title, installdir = (_values(text, k) for k in ("appid", "name", "installdir"))
            if not (appid and installdir) or not appid[0].isdigit():
                continue
            # installdir is a folder name in steamapps/common; anything path-like could lead out of the library
            if installdir[0] in ("", ".", "..") or "/" in installdir[0] or "\\" in installdir[0]:
                continue
            title = title[0] if title else installdir[0]
            install_dir = os.path.join(apps, "common", installdir[0])
            if TOOLS.match(title) or not os.path.isdir(install_dir):
                continue
            games[int(appid[0])] = {"appid": int(appid[0]), "name": title, "install_dir": install_dir}
    return sorted(games.values(), key=lambda g: g["name"].lower())


def _binary_vdf(data):
    """Steam's binary KeyValues (shortcuts.vdf): 0x00 nested map, 0x01 string, 0x02 int32, 0x07 uint64, 0x08 end.
    Keys are lower-cased."""
    def parse(i):
        node = {}
        while i < len(data):
            kind = data[i]
            i += 1
            if kind == 0x08:
                return node, i
            end = data.index(b"\0", i)
            key = data[i:end].decode("utf-8", "replace").lower()
            i = end + 1
            if kind == 0x00:
                node[key], i = parse(i)
            elif kind == 0x01:
                end = data.index(b"\0", i)
                node[key] = data[i:end].decode("utf-8", "replace")
                i = end + 1
            elif kind == 0x02:
                node[key] = struct.unpack_from("<i", data, i)[0]
                i += 4
            elif kind == 0x07:
                i += 8
            else:
                raise ValueError(f"unknown field type {kind}")
        return node, i
    return parse(0)[0]


def shortcuts(steam_root):
    """Non-Steam games (Steam shortcuts) that start a Windows .exe through Proton.

    {appid, name, install_dir (the exe's folder), exe (its name), nonsteam: True}.
    """
    games = {}
    try:
        users = os.listdir(os.path.join(steam_root, "userdata"))
    except OSError:
        return []
    for user in users:
        path = os.path.join(steam_root, "userdata", user, "config", "shortcuts.vdf")
        try:
            with open(path, "rb") as f:
                entries = _binary_vdf(f.read()).get("shortcuts", {})
        except (OSError, ValueError, IndexError, struct.error):
            continue
        for entry in entries.values() if isinstance(entries, dict) else []:
            exe = str(entry.get("exe", "")).strip().strip('"')
            if not isinstance(entry.get("appid"), int) or not exe.lower().endswith(".exe") or not os.path.isfile(exe):
                continue  # native Linux shortcuts (and Heroic/Lutris launchers) have no Windows exe to put ReShade by
            appid = entry["appid"] & 0xFFFFFFFF
            games[appid] = {"appid": appid, "name": str(entry.get("appname") or os.path.basename(exe)),
                            "install_dir": os.path.dirname(exe), "exe": os.path.basename(exe), "nonsteam": True}
    return list(games.values())


def all_games(steam_root):
    """Steam games and non-Steam shortcuts, sorted by name."""
    return sorted(scan(steam_root) + shortcuts(steam_root), key=lambda g: g["name"].lower())


def _rva_to_offset(sections, rva):
    for va, vsize, raw_size, raw_ptr in sections:
        if va <= rva < va + max(vsize, raw_size):
            return raw_ptr + rva - va
    return None


def _cstring(f, offset, limit=256):
    f.seek(offset)
    return f.read(limit).split(b"\0", 1)[0]


def pe_info(path):
    """{"bits": 32|64, "imports": {lower-case DLL names}} for a Windows executable or DLL, None for anything else."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
            if head[:2] != b"MZ" or len(head) < 64:
                return None
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            f.seek(pe)
            coff = f.read(24)
            if len(coff) < 24 or coff[:4] != b"PE\0\0":
                return None
            machine, n_sections = struct.unpack_from("<HH", coff, 4)
            opt_size = struct.unpack_from("<H", coff, 20)[0]
            bits = MACHINE_BITS.get(machine)
            if not bits:
                return None
            opt = f.read(opt_size)
            imports = set()
            # data directory 1 (imports) sits after the standard and Windows-specific fields: 96 bytes in PE32,
            # 112 in PE32+
            dirs = 96 if bits == 32 else 112
            if len(opt) >= dirs + 16:
                rva = struct.unpack_from("<I", opt, dirs + 8)[0]
                table = f.read(40 * min(n_sections, 96))
                sections = [struct.unpack_from("<IIII", table, i * 40 + 8)
                            for i in range(len(table) // 40)]
                sections = [(va, vsize, raw_size, raw_ptr) for vsize, va, raw_size, raw_ptr in sections]
                offset = _rva_to_offset(sections, rva) if rva else None
                for i in range(512 if offset is not None else 0):
                    f.seek(offset + i * 20)
                    descriptor = f.read(20)
                    if len(descriptor) < 20 or descriptor == b"\0" * 20:
                        break
                    name_at = _rva_to_offset(sections, struct.unpack_from("<I", descriptor, 12)[0])
                    if name_at is not None:
                        imports.add(_cstring(f, name_at).decode("ascii", "replace").lower())
            return {"bits": bits, "imports": imports}
    except (OSError, struct.error):
        return None


def _mentions(path, names):
    """Which of the byte strings in names occur (case-insensitively) in the first SCAN_LIMIT bytes of path."""
    found, tail, read = set(), b"", 0
    try:
        with open(path, "rb") as f:
            while read < SCAN_LIMIT and len(found) < len(names):
                chunk = f.read(1 << 22)
                if not chunk:
                    break
                read += len(chunk)
                window = tail + chunk.lower()
                found.update(n for n in names if n in window)
                tail = window[-32:]
    except OSError:
        pass  # an unreadable executable names no API: the caller falls back to the default
    return found


def _api_from(names):
    if names & {"d3d12.dll", "d3d11.dll", "d3d10.dll", "d3d10_1.dll", "dxgi.dll"}:
        return "dxgi"
    if names & {"d3d9.dll", "d3d8.dll"}:
        return "d3d9"  # Proton's DXVK runs Direct3D 8 on top of its d3d9, where ReShade hooks in
    if "opengl32.dll" in names:
        return "opengl32"
    if "vulkan-1.dll" in names:
        return "vulkan"
    return None


def detect_api(exe_path):
    """(api, how): api is one of APIS or "vulkan" (which a DLL cannot hook); how is imports, strings or default.

    Unity games render from UnityPlayer.dll next to a small launcher exe, so that file is read along with the exe.
    Only a DirectX 10-12 import decides on its own. Engines link OpenGL as a fallback while loading Direct3D at run
    time (Unity imports only opengl32 and runs DirectX 11), and big DirectX 12 games import d3d9 for side jobs
    (Red Dead Redemption 2), so the DLL names the files mention are read too, and newer DirectX wins. When the exe
    says nothing (the engine is a DLL beside it, as in Hades), the imports of the DLLs in its folder are read.
    """
    folder = os.path.dirname(exe_path)
    files = [exe_path]
    unity = os.path.join(folder, "UnityPlayer.dll")
    if os.path.isfile(unity):
        files.append(unity)
    imported = set()
    for path in files:
        imported |= (pe_info(path) or {}).get("imports", set())
    api = _api_from(imported)
    if api == "dxgi":
        return api, "imports"
    wanted = (b"d3d12.dll", b"d3d11.dll", b"d3d10.dll", b"dxgi.dll", b"d3d9.dll", b"d3d8.dll", b"opengl32.dll",
              b"vulkan-1.dll")
    mentioned = set()
    for path in files:
        mentioned |= {n.decode() for n in _mentions(path, wanted)}
    found = _api_from(imported | mentioned)
    if found:
        return found, "imports" if found == api else "strings"
    found = _api_from(_folder_imports(folder))
    return (found, "imports") if found else ("dxgi", "default")


# What the plugin itself puts next to a game; never evidence of the game's API.
OURS = {f"{api}.dll" for api in APIS} | {"d3dcompiler_47.dll"}
MAX_FOLDER_DLLS = 64


def _folder_imports(folder):
    """The imports of the DLLs beside an exe."""
    try:
        names = [n for n in os.listdir(folder) if n.lower().endswith(".dll") and n.lower() not in OURS]
    except OSError:
        return set()
    imported = set()
    for name in sorted(names)[:MAX_FOLDER_DLLS]:
        imported |= (pe_info(os.path.join(folder, name)) or {}).get("imports", set())
    return imported


def running_exes():
    """Lower-case paths, with forward slashes, of the .exe files running processes were started with (under Proton
    a Windows path such as S:\\steamapps\\common\\Hades\\x64\\Hades.exe)."""
    found = set()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read(4096).split(b"\0")
        except OSError:
            continue
        found.update(a.decode("utf-8", "replace").replace("\\", "/").lower() for a in args[:3]
                     if a.lower().endswith(b".exe"))
    return found


def _score(rel, size, game_name):
    name = os.path.basename(rel).lower()
    stem = re.sub(r"[^a-z0-9]", "", name[:-4])
    title = re.sub(r"[^a-z0-9]", "", game_name.lower())
    score = size / (1 << 20)  # the renderer is usually the biggest executable
    if "shipping" in name:
        score += 500  # Unreal Engine's real game binary
    if stem and title and (stem in title or title in stem):
        score += 200
    if "launcher" in name:
        score -= 300
    if re.search(r"(vk|vulkan)[^/]*/|vulkan", rel.lower()):
        score -= 400  # a game's Vulkan build (Hades' x64Vk): ReShade cannot hook it, its DirectX build is the one
    if NOT_GAME.search(name):
        score -= 1000  # still listed: a game can be called "Crash ..." or "... Server"
    return score - 5 * rel.count("/")


def inspect(game):
    """Executables worth offering for one game, best first, and whether it ships anti-cheat.

    {"candidates": [{"exe": path relative to install_dir, "bits": 32|64}], "anticheat": bool}
    """
    install_dir = game["install_dir"]
    base_depth = install_dir.rstrip(os.sep).count(os.sep)
    found, anticheat, running = [], False, running_exes()
    folder = os.path.basename(install_dir.rstrip(os.sep)).lower()
    for root, dirs, files in os.walk(install_dir):
        names = [n.lower() for n in dirs + files]
        if any(marker in n for n in names for marker in ANTICHEAT):
            anticheat = True
        depth = root.count(os.sep) - base_depth
        dirs[:] = [] if depth >= MAX_DEPTH else [d for d in dirs if d.lower() not in SKIP_DIRS]
        for name in files:
            if not name.lower().endswith(".exe"):
                continue
            path = os.path.join(root, name)
            info = pe_info(path)
            if not info:
                continue
            rel = os.path.relpath(path, install_dir).replace(os.sep, "/")
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            # the exe the game is running right now wins (by the usual score among several: Unity runs its crash
            # handler beside the game), then the one a shortcut names
            candidate = {"exe": rel, "bits": info["bits"]}
            score = _score(rel, size, game["name"])
            # under Proton the path is S:/steamapps/common/<folder>/<rel>: the folder keeps another game's Game.exe out
            if any(p.endswith(f"/{folder}/{rel.lower()}") for p in running):
                candidate["running"] = True
                score += 2e9
            elif rel == game.get("exe"):
                score += 1e9
            found.append((score, candidate))
    found.sort(key=lambda item: -item[0])
    return {"candidates": [c for _, c in found[:MAX_CANDIDATES]], "anticheat": anticheat}
