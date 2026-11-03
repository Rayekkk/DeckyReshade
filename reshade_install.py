# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Putting ReShade next to a game and taking it away again.

Rules that make rollback safe:
  * DLLs are only ever added; a file of the same name that is not ours stops the install (another ReShade, a mod),
    except a d3dcompiler_47.dll the game ships itself: ReShade uses it as it is when it builds Shader Model 5.1, else
    it is set aside (d3dcompiler_47.dll.deckyreshade-backup) for ours and put back on removal,
  * the manifest records every file we wrote with its sha256, and we delete only files whose hash still matches,
  * ReShade.ini is created when missing and otherwise only gets our shader folders added; it holds the user's
    ReShade settings, so it stays in the game folder on removal (with ReShadePreset.ini and ReShade.log, which
    ReShade writes); a first preset written for AutoHDR is removed with it while nobody has changed it,
  * launch options are never touched. Proton already loads dxgi, d3d9, d3d11 and d3d12 from the game folder first
    (its overrides for DXVK and vkd3d), and Wine does so for d3dcompiler_47 and dinput8 (built "prefer native");
    the other APIs (WINE_APIS) get a Wine DLL override in the game's prefix, for its executable alone, taken out
    again on removal while it is still ours.
"""

import os
import re
import shutil
import time

import dk_fs
from dk_fs import sha256_file
from reshade_games import APIS

COMPILER = "d3dcompiler_47.dll"
INI = "ReShade.ini"
PRESET = "ReShadePreset.ini"
LOG = "ReShade.log"
BACKUP = ".deckyreshade-backup"  # a game file set aside while ours is in its place
REGISTRY = "user.reg"  # the prefix's HKEY_CURRENT_USER
WINE_OVERRIDE = "native,builtin"
WINE_APIS = ("opengl32", "d3d10")  # APIs Wine would otherwise take from itself (checked on Proton 9 and 11)


class InstallError(Exception):
    pass


def _check_manifest(data):
    """dk_fs's validate hook: app id -> an entry with the fields everything here relies on."""
    dk_fs.require_object(data)
    for appid, e in data.items():
        if (not appid.isdigit() or not isinstance(e, dict)
                or not all(isinstance(e.get(k), str) for k in ("name", "target_dir", "exe", "api"))
                or type(e.get("bits")) is not int or not isinstance(e.get("files"), dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in e["files"].items())
                or "wine" in e and not (isinstance(e["wine"], dict)
                                        and all(isinstance(e["wine"].get(k), str) for k in ("prefix", "exe", "dll")))
                or "backups" in e and not (isinstance(e["backups"], dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in e["backups"].items()))):
            raise ValueError(f"entry {appid!r} is not a game set up by this plugin")


class Manifest:
    """appid -> {name, target_dir, exe, api, bits, files: {name: sha256}, wine?: {prefix, exe, dll},
    backups?: {name: sha256 of the game's own file set aside}}

    It is the only record of what the plugin put into game folders. A damaged file comes back from its last-good
    copy; when that is impossible (or the file cannot be read) `problem` says why and nothing is saved over it, so
    the record is never lost to a later change."""

    def __init__(self, path):
        self.path, self.entries, self.problem, self.recovered = path, {}, "", ""
        try:
            loaded = dk_fs.load_json(path, {}, validate=_check_manifest)
        except OSError as e:
            self.problem = f"The list of games set up could not be read ({dk_fs.shown(e)})."
            return
        if loaded.status == "lost":
            self.problem = ("The list of games set up is damaged, so no game can be changed. It is kept as it is; "
                            "the Decky log has the details.")
        self.recovered = loaded.detail if loaded.status in ("lost", "recovered") else ""
        self.entries = {int(k): v for k, v in loaded.value.items()}

    def save(self):
        if self.problem:
            raise InstallError(self.problem)
        dk_fs.write_json(self.path, {str(k): v for k, v in self.entries.items()})


def _builds_sm51(path):
    """Whether a d3dcompiler_47 builds Shader Model 5.1, which ReShade compiles DirectX 12 effects with. Windows 8.1's
    (6.3.9600, still shipped by some games) does not: every effect fails with X3506 "unrecognized compiler target"."""
    with open(path, "rb") as f:
        return b"vs_5_1" in f.read()


def launch_options(api):
    """What the user pastes into a game's launch options when they manage them (Settings → Use launch options).
    n,b also for the compiler: when our DLL is gone but the option stays, Wine falls back to its own."""
    return f'WINEDLLOVERRIDES="d3dcompiler_47=n,b;{api}=n,b" %command%'


def wine_prefix(game, steam_root):
    """The game's Proton prefix folder (compatdata/<appid>), '' before its first start (Steam makes it then).
    A Steam game's is in its own library, a shortcut's in Steam's main one."""
    libraries = [] if game.get("nonsteam") else [os.path.dirname(os.path.dirname(game["install_dir"]))]
    for steamapps in libraries + [os.path.join(steam_root, "steamapps")]:
        path = os.path.join(steamapps, "compatdata", str(game["appid"]))
        if os.path.isfile(os.path.join(path, "pfx", REGISTRY)):
            return path
    return ""


def prefix_in_use(prefix):
    """Whether a process runs in the prefix (the game, its launcher, a wineserver still closing). Wine keeps the
    registry in memory and writes it back on exit, so a change made meanwhile would be lost."""
    prefix = os.path.realpath(prefix)
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue  # gone, or not ours to read (a Proton game runs as the same user)
        for var in env:
            name, _, value = var.partition(b"=")
            if name in (b"STEAM_COMPAT_DATA_PATH", b"WINEPREFIX") and value:
                path = os.path.realpath(os.fsdecode(value))
                if path in (prefix, os.path.join(prefix, "pfx")):
                    return True
    return False


def _section(exe):
    # the key as Wine writes it in user.reg, backslashes doubled; Wine matches the exe name without case
    return f"[Software\\\\Wine\\\\AppDefaults\\\\{exe}\\\\DllOverrides]"


def _registry(prefix):
    with open(os.path.join(prefix, "pfx", REGISTRY), "rb") as f:
        return f.read().decode("utf-8", "surrogateescape").split("\n")


def _save_registry(prefix, lines):
    dk_fs.write_atomic(os.path.join(prefix, "pfx", REGISTRY), "\n".join(lines).encode("utf-8", "surrogateescape"))


def _find_section(lines, exe):
    """(index of the section's header, index after its last line), or (None, None)."""
    header = _section(exe).lower()
    for i, line in enumerate(lines):
        if line.lower().startswith(header):  # the header is followed by " <modified time>"
            end = i + 1
            while end < len(lines) and lines[end] and not lines[end].startswith("["):
                end += 1
            return i, end
    return None, None


def set_dll_override(prefix, exe, dll):
    """Wine loads dll from the game folder first, for this executable only (what WINEDLLOVERRIDES=dll=n,b in its
    launch options would do). True when we added it; False when the same value was already there, so it is not ours
    to take away. Another value for the DLL is the user's: refused."""
    if not re.fullmatch(r"[\w .+()-]+\.exe", exe, re.ASCII):  # Wine would escape other characters in the key
        raise InstallError(f"the executable's name ({exe}) is not one the plugin can set Wine up for; turn on "
                           "\"Use launch options\" in Settings instead")
    lines = _registry(prefix)
    value = f'"{dll}"="{WINE_OVERRIDE}"'
    start, end = _find_section(lines, exe)
    if start is None:
        if lines and lines[-1] == "":
            lines.pop()
        lines += ["", f"{_section(exe)} {int(time.time())}", value, ""]
    else:
        current = next((l for l in lines[start + 1:end] if l.lower().startswith(f'"{dll}"=')), None)
        if current == value:
            return False
        if current is not None:
            raise InstallError(f"this game already has its own Wine setting for {dll}; leaving it alone. Turn on "
                               "\"Use launch options\" in Settings instead")
        lines.insert(end, value)
    _save_registry(prefix, lines)
    return True


def remove_dll_override(prefix, exe, dll):
    """Take out what set_dll_override added; a value changed since is no longer ours and stays."""
    try:
        lines = _registry(prefix)
    except FileNotFoundError:
        return  # the prefix was deleted, and the setting with it
    start, end = _find_section(lines, exe)
    value = f'"{dll}"="{WINE_OVERRIDE}"'
    if start is None or value not in lines[start + 1:end]:
        return
    body = [l for l in lines[start + 1:end] if l != value]
    if any(not l.startswith("#") for l in body):
        lines[start + 1:end] = body
    else:  # only Wine's time stamp left: the section goes, with the blank line before it
        del lines[start - 1 if start and lines[start - 1] == "" else start:end]
    _save_registry(prefix, lines)


def wine_path(path):
    """A Linux path as Proton's Z: drive sees it."""
    return "Z:" + path.replace("/", "\\")


def search_paths(shaders_dir):
    """ReShade.ini keys -> our folder for them, searched recursively as the official installer sets it up."""
    root = wine_path(shaders_dir)
    return {"EffectSearchPaths": root + "\\Shaders\\**", "TextureSearchPaths": root + "\\Textures\\**"}


def ini_text(shaders_dir):
    """A new ReShade.ini: our shader folders, presets next to the game, no first-run tutorial."""
    paths = search_paths(shaders_dir)
    return ("[GENERAL]\n"
            + "".join(f"{key}={value}\n" for key, value in paths.items())
            + "PresetPath=.\\ReShadePreset.ini\n"
            "\n[OVERLAY]\n"
            "TutorialProgress=4\n")


def with_shader_paths(text, shaders_dir):
    """An existing ReShade.ini with our shader folders added to its search paths (the user's paths stay)."""
    ours = search_paths(shaders_dir)
    lines, section, seen = text.splitlines(), "", set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.upper()
            continue
        key, sep, value = stripped.partition("=")
        if section == "[GENERAL]" and sep and key in ours:
            seen.add(key)
            paths = [p for p in value.split(",") if p]
            if ours[key] not in paths:
                lines[i] = f"{key}={','.join(paths + [ours[key]])}"
    missing = [f"{k}={v}" for k, v in ours.items() if k not in seen]
    if missing:
        at = next((i + 1 for i, l in enumerate(lines) if l.strip().upper() == "[GENERAL]"), None)
        if at is None:
            lines = ["[GENERAL]", *missing, ""] + lines
        else:
            lines[at:at] = missing
    return "\n".join(lines) + "\n"


def _replace_via_tmp(dst, fill):
    """Write through a temp file, so a failed copy (a full SD card) never leaves half a DLL or the temp file."""
    tmp = dst + ".reshade-tmp"
    try:
        fill(tmp)
        os.replace(tmp, dst)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass  # the first error is the one to report
        raise


def _copy(src, dst):
    # A copy, not a hard link: a tool overwriting one game's dxgi.dll in place must not change every other game.
    _replace_via_tmp(dst, lambda tmp: shutil.copyfile(src, tmp))


def _write_text(dst, text):
    def fill(tmp):
        with open(tmp, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
    _replace_via_tmp(dst, fill)


def autohdr_preset():
    """A first ReShadePreset.ini for AutoHDR games, with Pumbo's AdvancedAutoHDR switched on."""
    techniques = "AdvancedAutoHDR@AdvancedAutoHDR.fx"
    return f"Techniques={techniques}\nTechniqueSorting={techniques}\n"


def enable(manifest, game, exe, api, bits, sources, shaders_dir, prefix="", preset=None):
    """Install ReShade for one game.

    game: {appid, name, install_dir}; exe: path relative to install_dir; sources: {name in the game folder: file}
    (the ReShade DLL under the API's name, the matching d3dcompiler_47, add-ons); prefix: the game's Proton prefix
    when the API needs a Wine DLL override there ('' when the user manages launch options); preset:
    ReShadePreset.ini to start with when the game has none.
    """
    appid = game["appid"]
    target = os.path.dirname(os.path.join(game["install_dir"], exe))
    old = manifest.entries.get(appid)
    if old and (old["target_dir"], old["api"]) != (target, api):
        raise InstallError("ReShade is set up for another executable or API here; turn it off first")
    known = (old or {}).get("files", {})
    want = {name: sha256_file(src) for name, src in sources.items()}
    set_aside = None  # the game's own compiler, too old for ReShade: kept beside ours and put back on removal
    for name in list(want):
        path = os.path.join(target, name)
        if not os.path.exists(path) and not os.path.islink(path):
            continue
        try:
            digest = sha256_file(path)
        except OSError:
            digest = None  # a dangling link left by another ReShade tool
        if digest in (want[name], known.get(name)):
            continue
        if name == COMPILER and digest:
            if _builds_sm51(path):
                del want[name]  # the game's own compiler works for ReShade too
            else:
                set_aside = digest
            continue
        raise InstallError(f"{name} already exists in the game folder and is not ours (another ReShade or a mod?); "
                           "leaving it alone")

    entry = old or {"name": game["name"], "target_dir": target, "files": {}}
    entry.update(exe=exe, api=api, bits=bits)
    if prefix and not entry.get("wine"):
        if prefix_in_use(prefix):
            raise InstallError("close the game first: Wine writes its settings back when it exits")
        name = os.path.basename(exe)
        try:
            added = set_dll_override(prefix, name, api)
        except OSError as e:
            raise InstallError(f"could not change the game's Wine settings ({dk_fs.shown(e)})") from e
        if added:  # recorded before any file is copied, so a failure later can still be undone
            entry["wine"] = {"prefix": prefix, "exe": name, "dll": api}
            manifest.entries[appid] = entry
            manifest.save()
    try:
        if set_aside:
            path, backup = os.path.join(target, COMPILER), os.path.join(target, COMPILER + BACKUP)
            if os.path.lexists(backup) and sha256_file(backup) != set_aside:
                raise InstallError(f"{COMPILER + BACKUP} in the game folder is not the game's {COMPILER}; leaving both "
                                   "alone")
            # recorded first: put back on removal even if the plugin stops right after the move
            entry.setdefault("backups", {})[COMPILER] = set_aside
            manifest.entries[appid] = entry
            manifest.save()
            os.replace(path, backup)
        for name in want:
            _copy(sources[name], os.path.join(target, name))
            entry["files"][name] = want[name]
            manifest.entries[appid] = entry  # recorded as soon as a file exists, so a crash can still be undone
            manifest.save()
        ini = os.path.join(target, INI)
        if os.path.exists(ini):
            with open(ini, encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
            updated = with_shader_paths(text, shaders_dir)
            if updated.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
                _write_text(ini, updated)
        else:
            _write_text(ini, ini_text(shaders_dir))
        preset_path = os.path.join(target, PRESET)
        if preset and not os.path.exists(preset_path):
            _write_text(preset_path, preset)
            # recorded like a DLL: turning the feature off removes it again, unless the user's edits made it theirs
            entry["files"][PRESET] = sha256_file(preset_path)
    except OSError as e:
        raise InstallError(f"could not write to the game folder ({dk_fs.shown(e)})") from e

    entry["enabled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest.entries[appid] = entry
    manifest.save()


def refresh(manifest, sources_for):
    """Bring every game's ReShade DLL up to a new build; returns how many were updated.

    sources_for(entry) -> {name: file}. Only files that still match what we installed are replaced, so nothing the
    user put there is touched; a running game keeps the DLL it loaded (the old file lives on until it exits).
    """
    updated = 0
    for entry in manifest.entries.values():
        changed = False
        for name, src in sources_for(entry).items():
            had = entry["files"].get(name)
            path = os.path.join(entry["target_dir"], name)
            try:
                want = sha256_file(src)
                if not had or had == want or sha256_file(path) != had:
                    continue
                _copy(src, path)
            except OSError:
                continue
            entry["files"][name] = want
            changed = True
        updated += changed
    if updated:
        manifest.save()
    return updated


def disable(manifest, appid):
    """Remove what we installed. Returns the files left because they changed."""
    entry = manifest.entries.get(appid)
    if not entry:
        return []
    if not os.path.isdir(entry["target_dir"]):
        if not _gone(entry):  # an SD card taken out: forgetting the game would orphan its files
            raise InstallError("the game's folder is not available (is its SD card in?); nothing was changed")
        forget(manifest, appid)  # uninstalled or deleted: nothing of ours is left there
        return []
    wine = entry.get("wine")
    if wine:  # first: refused or failed, nothing else is changed either
        if prefix_in_use(wine["prefix"]):
            raise InstallError("close the game first: Wine writes its settings back when it exits")
        try:
            remove_dll_override(wine["prefix"], wine["exe"], wine["dll"])
        except OSError as e:
            raise InstallError(f"could not change the game's Wine settings ({dk_fs.shown(e)})") from e
        del entry["wine"]
        manifest.save()
    kept = []
    for name, digest in entry["files"].items():
        path = os.path.join(entry["target_dir"], name)
        try:
            if not os.path.exists(path):
                continue
            current = sha256_file(path)
            if current == digest:
                os.remove(path)
            elif current != entry.get("backups", {}).get(name):  # else the game's own is back: handled below
                kept.append(name)
        except OSError:
            kept.append(name)
    for name, digest in entry.get("backups", {}).items():
        path = os.path.join(entry["target_dir"], name)
        backup = path + BACKUP
        try:
            if not os.path.exists(backup):
                continue
            if not os.path.lexists(path):
                os.replace(backup, path)
            elif sha256_file(path) == digest:
                os.remove(backup)  # the game put its own back (an update, Steam's file check)
            else:
                kept.append(name + BACKUP)
        except OSError:
            kept.append(name + BACKUP)
    # ReShade.log stays with ReShade.ini: it is what tells why ReShade did not work, often the reason to turn it off
    del manifest.entries[appid]
    manifest.save()
    return kept


def _install_dir(entry):
    """The game's folder: target_dir without the executable's subfolders."""
    path = entry["target_dir"]
    for _ in [p for p in entry["exe"].replace("\\", "/").split("/")[:-1] if p]:
        path = os.path.dirname(path)
    return path


def _gone(entry):
    """Whether the game's folder is gone for good (uninstalled, moved, deleted) rather than out of reach: the folder
    that held it is still there, which a library on an SD card taken out is not."""
    install_dir = _install_dir(entry)
    return not os.path.isdir(install_dir) and os.path.isdir(os.path.dirname(install_dir))


def forget(manifest, appid):
    """Drop a game whose folder is gone. Its Wine setting goes too when its prefix is still there and free; one left
    behind only points opengl32 or d3d10 at a DLL that is no longer there, and Wine then takes its own."""
    wine = manifest.entries[appid].get("wine")
    if wine and not prefix_in_use(wine["prefix"]):
        try:
            remove_dll_override(wine["prefix"], wine["exe"], wine["dll"])
        except OSError:
            pass
    del manifest.entries[appid]
    manifest.save()


def follow_moved(manifest, games, steam_root):
    """Games whose folder is gone, checked against the library: one moved to another library (Steam takes our files
    along) is followed there, one no longer in the library is forgotten; a game on an SD card that is out stays as it
    is. Returns what changed, for the log."""
    library = {g["appid"]: g for g in games}
    changed = []
    for appid, entry in list(manifest.entries.items()):
        if os.path.isdir(entry["target_dir"]):
            continue
        game = library.get(appid)
        if game and os.path.isfile(os.path.join(game["install_dir"], entry["exe"])):
            entry["target_dir"] = os.path.dirname(os.path.join(game["install_dir"], entry["exe"]))
            wine = entry.get("wine")
            if wine and not os.path.isdir(wine["prefix"]):  # the prefix moved too, with our setting in it
                prefix = wine_prefix(game, steam_root)
                if prefix:
                    wine["prefix"] = prefix
                else:
                    del entry["wine"]
            manifest.save()
            changed.append(f"{entry['name']} moved to {entry['target_dir']}")
        elif not game and _gone(entry):
            forget(manifest, appid)
            changed.append(f"{entry['name']} is no longer installed")
    return changed


def loaded_since(entry, since):
    """Whether ReShade wrote its log in the game folder after since (epoch s): the proof it ran."""
    try:
        return os.path.getmtime(os.path.join(entry["target_dir"], LOG)) >= since - 2
    except OSError:
        return False
