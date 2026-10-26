# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Putting ReShade next to a game and taking it away again.

Rules that make rollback safe:
  * DLLs are only ever added; a file of the same name that is not ours stops the install (another ReShade, a mod),
    except a d3dcompiler_47.dll the game ships itself, which ReShade can use as it is,
  * the manifest records every file we wrote with its sha256, and we delete only files whose hash still matches,
  * ReShade.ini is created when missing and otherwise only gets our shader folders added; it holds the user's
    ReShade settings, so it stays in the game folder on removal (with ReShadePreset.ini and ReShade.log, which
    ReShade writes),
  * launch options: our entries go into WINEDLLOVERRIDES next to whatever is already there (the user's, another
    plugin's). On removal the original comes back when nobody edited the options since, otherwise only our entries
    are taken out.
"""

import json
import os
import re
import shutil
import time

from reshade_games import APIS
from reshade_net import sha256_file

COMPILER = "d3dcompiler_47.dll"
INI = "ReShade.ini"
PRESET = "ReShadePreset.ini"
LOG = "ReShade.log"
_OVERRIDES = re.compile(r"""^WINEDLLOVERRIDES=(["']?)(.*)\1$""")


class InstallError(Exception):
    pass


class Manifest:
    """appid -> {name, target_dir, exe, api, bits, files: {name: sha256}, launch_original, launch_applied}"""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.entries = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError, AttributeError):
            self.entries = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in self.entries.items()}, f, indent=1)
        os.replace(tmp, self.path)


def our_overrides(api):
    # n,b also for the compiler: when our DLL is gone but the option stays (kept by another tool), Wine falls back
    # to its own instead of failing to load it
    return ["d3dcompiler_47=n,b", f"{api}=n,b"]


def launch_word(api):
    """The WINEDLLOVERRIDES word for one API, as written into launch options (and offered to Decky Launch Options)."""
    return _overrides_word(our_overrides(api))


def dlo_leftover(options):
    """The WINEDLLOVERRIDES word in options when it still holds a ReShade proxy override (with d3dcompiler_47=n,b,
    as this plugin writes it), else ''. Used on what Decky Launch Options stores for a game."""
    for word in (options or "").split():
        match = _OVERRIDES.match(word)
        entries = match.group(2).split(";") if match else []
        if "d3dcompiler_47=n,b" in entries and any(e.split("=")[0] in APIS for e in entries):
            return word
    return ""


def dlo_managed(options):
    """Whether Decky Launch Options runs this game (its options are then ~/.dlo/run %command%, and DLO puts back
    the options it keeps whenever it restores them, so ours would not last)."""
    return any(re.search(r"(^|/)\.dlo/run$", word) for word in (options or "").split())


def _without_dlls(entries, names):
    """Entries with the given DLLs taken out; Wine also accepts a list sharing one mode ('dxgi,d3d11=n,b'),
    whose other DLLs keep that mode."""
    kept = []
    for entry in entries:
        dlls, sep, mode = entry.partition("=")
        rest = [d for d in dlls.split(",") if d and d.lower() not in names]
        if rest:
            kept.append(",".join(rest) + sep + mode)
    return kept


def _overrides_word(entries):
    value = ";".join(entries)
    return f'WINEDLLOVERRIDES="{value}"' if ";" in value else f"WINEDLLOVERRIDES={value}"


def _env_key(word):
    return word.split("=", 1)[0]


def with_overrides(options, ours, env=()):
    """Launch options with our DLL overrides merged in and our environment words (DXVK_HDR=1) next to them;
    %command% added when the options had none. Another value for one of our variables is replaced."""
    keys = {_env_key(w) for w in env}
    words = [w for w in (options or "").split() if _env_key(w) not in keys]
    # words are split on spaces; a quoted value holding one would be cut apart and rejoined wrongly
    if any(w.count('"') % 2 or w.count("'") % 2 for w in words):
        raise InstallError("these launch options quote text with spaces in it, which the plugin will not edit: turn "
                           "off \"Set launch options automatically\" and add the WINEDLLOVERRIDES entries yourself")
    names = {e.split("=", 1)[0].lower() for e in ours}
    for i, word in enumerate(words):
        match = _OVERRIDES.match(word)
        if match:
            kept = _without_dlls([e for e in match.group(2).split(";") if e], names)
            words[i:i + 1] = [_overrides_word(kept + ours), *env]
            break
    else:
        if "%command%" not in words:
            words = ["%command%"] + words  # the old options were the game's arguments
        words[0:0] = [_overrides_word(ours), *env]
    if "%command%" not in words:
        words.append("%command%")
    return " ".join(words)


def without_overrides(current, original, applied, ours, env=()):
    """Undo with_overrides: the original when untouched since, else our entries taken out of what is there now.

    An entry the original had for one of our DLLs (a user's own d3dcompiler_47=n), which ours replaced, comes back;
    so does the original value of one of our environment variables.
    """
    current = (current or "").strip()
    if current == applied:
        return original
    keys = {_env_key(w) for w in env}
    original_env = {_env_key(w): w for w in (original or "").split() if _env_key(w) in keys}
    current = " ".join(original_env.get(_env_key(w), "") if w in env else w for w in current.split())
    before = []
    for word in (original or "").split():
        match = _OVERRIDES.match(word)
        if match:
            before = [e for e in match.group(2).split(";") if e]
    names = {e.split("=", 1)[0].lower() for e in ours}
    restore = []
    for entry in before:
        dlls, sep, mode = entry.partition("=")
        back = [d for d in dlls.split(",") if d.lower() in names]
        if back:
            restore.append(",".join(back) + sep + mode)
    words = []
    for word in current.split():
        match = _OVERRIDES.match(word)
        if match:
            kept = [e for e in match.group(2).split(";") if e and e not in ours]
            kept += [e for e in restore if e not in kept]
            if not kept:
                continue
            word = _overrides_word(kept)
        words.append(word)
    if words == ["%command%"] and "%command%" not in (original or ""):
        return original
    return " ".join(words)


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
            pass
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


def enable(manifest, game, exe, api, bits, sources, shaders_dir, launch_options, launch=True, env=(), preset=None):
    """Install ReShade for one game; returns the launch options to apply.

    game: {appid, name, install_dir}; exe: path relative to install_dir; sources: {name in the game folder: file}
    (the ReShade DLL under the API's name, the matching d3dcompiler_47, add-ons); launch: False leaves the launch
    options to the user (returned unchanged, and never touched on disable); env: environment words to add with our
    overrides (DXVK_HDR=1 for AutoHDR); preset: ReShadePreset.ini to start with when the game has none.
    """
    appid = game["appid"]
    target = os.path.dirname(os.path.join(game["install_dir"], exe))
    old = manifest.entries.get(appid)
    if old and (old["target_dir"], old["api"]) != (target, api):
        raise InstallError("ReShade is set up for another executable or API here; turn it off first")
    known = (old or {}).get("files", {})
    want = {name: sha256_file(src) for name, src in sources.items()}
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
            del want[name]  # the game's own compiler works for ReShade too
            continue
        raise InstallError(f"{name} already exists in the game folder and is not ours (another ReShade or a mod?); "
                           "leaving it alone")

    new_options = with_overrides(launch_options, our_overrides(api), env) if launch else None  # may refuse: first
    # Our entries can already be there (left by an earlier install); they are never part of the user's original.
    original = without_overrides(launch_options, "", None, our_overrides(api), env) if launch_options else ""
    entry = old or {"name": game["name"], "target_dir": target, "files": {}, "launch_original": original}
    entry.update(exe=exe, api=api, bits=bits, env=list(env))
    try:
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
        if preset and not os.path.exists(os.path.join(target, PRESET)):
            _write_text(os.path.join(target, PRESET), preset)
    except OSError as e:
        raise InstallError(f"could not write to the game folder: {e}") from e

    if launch:
        entry["launch_applied"] = new_options
    entry["enabled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest.entries[appid] = entry
    manifest.save()
    return new_options if launch else (launch_options or "").strip()


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


def disable(manifest, appid, launch_options):
    """Remove what we installed. Returns {launch_options, kept: [files left because they changed]}."""
    entry = manifest.entries.get(appid)
    if not entry:
        return {"launch_options": (launch_options or "").strip(), "kept": []}
    if not os.path.isdir(entry["target_dir"]):  # an SD card taken out: forgetting the game would orphan its files
        raise InstallError("the game's folder is not available (is its SD card in?); nothing was changed")
    kept = []
    for name, digest in entry["files"].items():
        path = os.path.join(entry["target_dir"], name)
        try:
            if not os.path.exists(path):
                continue
            if sha256_file(path) == digest:
                os.remove(path)
            else:
                kept.append(name)
        except OSError:
            kept.append(name)
    # ReShade.log stays with ReShade.ini: it is what tells why ReShade did not work, often the reason to turn it off
    if entry.get("launch_applied"):
        restored = without_overrides(launch_options, entry.get("launch_original", ""), entry["launch_applied"],
                                     our_overrides(entry["api"]), entry.get("env", []))
    else:  # the user manages this game's launch options
        restored = (launch_options or "").strip()
    del manifest.entries[appid]
    manifest.save()
    return {"launch_options": restored, "kept": kept}


def loaded_since(entry, since):
    """Whether ReShade wrote its log in the game folder after since (epoch s): the proof it ran."""
    try:
        return os.path.getmtime(os.path.join(entry["target_dir"], LOG)) >= since - 2
    except OSError:
        return False
