# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""DeckyReshade - ReShade for Steam and non-Steam games under Proton, set up from Gaming Mode.

ReShade (reshade_release) and shader packages (reshade_shaders) are downloaded once into the plugin's data folder;
each game gets the ReShade DLL for its executable and API plus a ReShade.ini pointing at the shared shaders
(reshade_install). Launch options are applied by the frontend through SteamClient; this backend computes them so
they can be undone exactly. Long downloads run one at a time as a "job" the panel polls. Every step is logged
(decky.logger), and reshade_diag turns the logs into what the panel shows when something fails.
"""

import asyncio
import json
import os
import shutil
import sys
import time

import decky

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import reshade_diag  # noqa: E402
import reshade_games  # noqa: E402
import reshade_install  # noqa: E402
import reshade_release  # noqa: E402
import reshade_renodx  # noqa: E402
import reshade_shaders  # noqa: E402
import reshade_updates  # noqa: E402

try:
    with open(os.path.join(PLUGIN_DIR, "plugin.json"), encoding="utf-8") as _f:
        VERSION = json.load(_f)["version"]
except (OSError, ValueError, KeyError):
    VERSION = "0.0.0"
# addon: ReShade's add-on build (AutoHDR, depth add-ons; ReShade blocks it in online games); version: "latest" (kept
# up to date from reshade.me) or one of reshade_release.VERSIONS; auto_launch_options: turning a game on also sets
# its launch options.
DEFAULT_SETTINGS = {"addon": True, "version": "latest", "auto_launch_options": True}
CHECK_EVERY = 24 * 3600
AUTOHDR_PACKAGE = "advancedautohdr-by-pumbo"  # the effect that turns SDR into HDR, from ReShade's package list
AUTOHDR_ENV = ["DXVK_HDR=1"]  # lets the game's swap chain use HDR under Proton (AutoHDR and RenoDX)
_ready = asyncio.Event()


def _data_dir():
    return getattr(decky, "DECKY_PLUGIN_RUNTIME_DIR", decky.DECKY_PLUGIN_SETTINGS_DIR)


def _home():
    return getattr(decky, "DECKY_USER_HOME", os.path.expanduser("~"))


def _steam_root():
    return os.path.join(_home(), ".local", "share", "Steam")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _dlo_original(appid):
    """The launch options Decky Launch Options stores as a game's original ('' when it has none); read only."""
    profile = _read_json(os.path.join(_home(), ".dlo", "settings.json")).get("profiles", {}).get(str(appid), {})
    value = profile.get("originalLaunchOptions") if isinstance(profile, dict) else ""
    return value if isinstance(value, str) else ""


def _load_settings(path):
    saved = _read_json(path)
    settings = {k: saved[k] if type(saved.get(k)) is type(v) else v for k, v in DEFAULT_SETTINGS.items()}
    if settings["version"] != "latest" and settings["version"] not in reshade_release.VERSIONS:
        settings["version"] = "latest"
    return settings


class Plugin:
    async def _main(self):
        self.reshade_root = os.path.join(_data_dir(), "reshade")
        self.shaders_root = os.path.join(_data_dir(), "shaders")
        self.renodx_root = os.path.join(_data_dir(), "renodx")
        for path in (self.reshade_root, self.shaders_root, self.renodx_root, decky.DECKY_PLUGIN_SETTINGS_DIR):
            os.makedirs(path, exist_ok=True)
        self.manifest = reshade_install.Manifest(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "manifest.json"))
        self.settings_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
        self.settings = _load_settings(self.settings_path)
        # {"version", "addon"}: the ReShade build games use; {"latest", "checked_at", "check_error"}: reshade.me
        self.release_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "reshade.json")
        self.release = _read_json(self.release_path)
        self.lock = asyncio.Lock()
        self.job = {"task": "", "error": ""}
        self.packages = None  # the shader package list, loaded when needed
        self.games, self.scanned = [], False
        self.sessions = {}  # appid -> session start (epoch s)
        # the RenoDX wiki's mod list, kept between restarts: {"mods", "fetched_at", "error"}
        self.renodx_path = os.path.join(_data_dir(), "renodx.json")
        self.renodx = _read_json(self.renodx_path)
        self.renodx_match = {}  # appid -> mod, for the library
        decky.logger.info(f"DeckyReshade {VERSION} on {reshade_diag.os_release()}: settings={self.settings} "
                          f"reshade={self.release.get('version')} addon={self.release.get('addon')} "
                          f"games set up={len(self.manifest.entries)}")
        _ready.set()
        self._scan_task = asyncio.create_task(self.scan_games())
        if time.time() - self.renodx.get("fetched_at", 0) > CHECK_EVERY:
            self._renodx_task = asyncio.create_task(self.refresh_renodx())
        if self._installed() and self.settings["version"] == "latest" and \
                time.time() - self.release.get("checked_at", 0) > CHECK_EVERY:
            self._update_task = asyncio.create_task(self.update_reshade(quiet=True))

    # ---- state -------------------------------------------------------------------------------------------------

    def _installed(self):
        """The ReShade version games use, when its files are all there."""
        version = self.release.get("version")
        if not isinstance(version, str):
            return None
        folder = os.path.join(self.reshade_root, reshade_release.variant(version, self.release.get("addon", False)))
        return version if reshade_release.is_complete(folder) else None

    def _autohdr_ready(self):
        return all(os.path.isfile(reshade_release.autohdr_path(self.reshade_root, b)) for b in (32, 64)) and \
            AUTOHDR_PACKAGE in reshade_shaders.installed(self.shaders_root)

    def _sources(self, api, bits, autohdr=False, renodx_file=None, version=None, addon=None):
        version = version or self.release["version"]
        addon = self.release.get("addon", False) if addon is None else addon
        sources = {f"{api}.dll": reshade_release.dll_path(self.reshade_root, version, addon, bits),
                   reshade_install.COMPILER: reshade_release.compiler_path(self.reshade_root, bits)}
        if autohdr:
            sources[f"AutoHDR.addon{bits}"] = reshade_release.autohdr_path(self.reshade_root, bits)
        if renodx_file:
            sources[renodx_file] = os.path.join(self.renodx_root, renodx_file)
        return sources

    def _match_renodx(self):
        mods = self.renodx.get("mods") or []
        self.renodx_match = {g["appid"]: m for g in self.games if (m := reshade_renodx.match(g["name"], mods))}

    def _mod(self, name):
        return next((m for m in self.renodx.get("mods") or [] if m["name"] == name), None)

    async def get_state(self) -> dict:
        await _ready.wait()
        latest, installed = self.release.get("latest"), self._installed()
        return {
            "version": VERSION,
            "reshade": {"installed": installed, "addon": self.release.get("addon", False), "latest": latest,
                        "update_available": bool(installed and latest and self.settings["version"] == "latest" and
                                                 reshade_release.version_tuple(latest) >
                                                 reshade_release.version_tuple(installed)),
                        "check_error": self.release.get("check_error", ""),
                        "versions": reshade_release.VERSIONS, "autohdr_ready": self._autohdr_ready()},
            "job": self.job,
            "settings": self.settings,
            "launch_words": {api: reshade_install.launch_word(api) for api in reshade_games.APIS},
            "autohdr_env": AUTOHDR_ENV,
            "renodx": {"count": len(self.renodx.get("mods") or []), "fetched_at": self.renodx.get("fetched_at", 0),
                       "error": self.renodx.get("error", "")},
            "scanned": self.scanned,
            "games": [{"appid": g["appid"], "name": g["name"], "nonsteam": g.get("nonsteam", False),
                       "renodx": (self.renodx_match.get(g["appid"]) or {}).get("status")}
                      for g in self.games],
            "enabled": [{"appid": a, "name": e["name"], "api": e["api"], "exe": e["exe"], "bits": e["bits"],
                         "autohdr": bool(e.get("autohdr")), "renodx": e.get("renodx", "")}
                        for a, e in sorted(self.manifest.entries.items(), key=lambda i: i[1]["name"].lower())],
            "shaders": {"installed": reshade_shaders.installed(self.shaders_root), "packages": self.packages},
        }

    def _save_settings(self):
        _write_json(self.settings_path, self.settings)

    def _save_release(self):
        _write_json(self.release_path, self.release)

    async def set_setting(self, key: str, value: bool) -> dict:
        if key not in ("addon", "auto_launch_options") or not isinstance(value, bool):
            return await self.get_state()
        self.settings[key] = value
        self._save_settings()
        decky.logger.info(f"setting {key}={value}")
        if key == "addon" and self._installed() and value != self.release.get("addon", False):
            return await self._job("Switching ReShade build…", self._switch_build, self.release["version"], value)
        return await self.get_state()

    async def set_version(self, version: str) -> dict:
        """"latest" (kept up to date) or one of the known versions, which then stays until changed."""
        if version != "latest" and version not in reshade_release.VERSIONS:
            return await self.get_state()
        self.settings["version"] = version
        self._save_settings()
        decky.logger.info(f"ReShade version set to {version}")
        if not self._installed():
            return await self.get_state()
        return await self._job("Switching ReShade version…", self._apply_version)

    async def scan_games(self) -> dict:
        await _ready.wait()
        self.games = await asyncio.to_thread(reshade_games.all_games, _steam_root())
        self._match_renodx()
        self.scanned = True
        decky.logger.info(f"library: {len(self.games)} game(s), "
                          f"{sum(1 for g in self.games if g.get('nonsteam'))} of them non-Steam, "
                          f"{len(self.renodx_match)} with a RenoDX mod")
        return await self.get_state()

    async def refresh_renodx(self) -> dict:
        """Load the RenoDX wiki's mod list again (also once a day at startup)."""
        await _ready.wait()
        try:
            mods = await asyncio.to_thread(reshade_renodx.fetch_list)
            self.renodx = {"mods": mods, "fetched_at": time.time(), "error": ""}
            decky.logger.info(f"RenoDX list: {len(mods)} mods, {sum(1 for m in mods if m['files'])} installable")
        except reshade_renodx.RenoDXError as e:
            decky.logger.warning(f"RenoDX list: {e}")
            self.renodx = {**self.renodx, "error": str(e)}
        try:
            _write_json(self.renodx_path, self.renodx)
        except OSError as e:
            decky.logger.error(f"RenoDX list not saved: {e}")
        self._match_renodx()
        decky.logger.info(f"RenoDX: {len(self.renodx_match)} game(s) in the library have a mod")
        return await self.get_state()

    async def get_renodx_mods(self) -> dict:
        """Every mod that can be installed from here, for picking one by hand."""
        await _ready.wait()
        mods = [{"name": m["name"], "status": m["status"]} for m in self.renodx.get("mods") or [] if m["files"]]
        return {"mods": sorted(mods, key=lambda m: m["name"].lower())}

    # ---- jobs: one download at a time, errors kept for the panel ----------------------------------------------

    async def _job(self, label, work, *args, quiet=False):
        if self.job["task"]:
            return await self.get_state()
        self.job = {"task": label, "error": ""}
        decky.logger.info(f"job started: {label}")
        try:
            async with self.lock:
                await asyncio.to_thread(work, *args)
            self.job = {"task": "", "error": ""}
            decky.logger.info(f"job done: {label}")
        except Exception as e:  # any failure must end the job, or the panel would wait for it forever
            decky.logger.exception(f"job failed: {label}")
            self.job = {"task": "", "error": "" if quiet else str(e)}
        return await self.get_state()

    def _switch_build(self, version, addon):
        """Fetch one ReShade build, move every game to it, keep only it on disk."""
        reshade_release.fetch(self.reshade_root, version, addon)
        reshade_release.fetch_compilers(self.reshade_root)
        refreshed = reshade_install.refresh(
            self.manifest, lambda e: self._sources(e["api"], e["bits"], e.get("autohdr"), e.get("renodx_file"),
                                                   version, addon))
        self.release.update(version=version, addon=addon)
        self._save_release()
        reshade_release.prune(self.reshade_root, {reshade_release.variant(version, addon)})
        decky.logger.info(f"ReShade {reshade_release.variant(version, addon)} in use, {refreshed} game(s) updated")

    def _check(self):
        """Ask reshade.me for its version; None when it cannot be told (remembered for the panel)."""
        try:
            latest = reshade_release.latest_version()
        except reshade_release.ReleaseError as e:
            decky.logger.warning(f"version check: {e}")
            self.release.update(check_error=str(e), checked_at=time.time())
            self._save_release()
            return None
        decky.logger.info(f"version check: reshade.me offers {latest}")
        self.release.update(latest=latest, check_error="", checked_at=time.time())
        self._save_release()
        return latest

    def _target_version(self):
        if self.settings["version"] != "latest":
            return self.settings["version"]
        return self._check() or reshade_release.FALLBACK

    def _apply_version(self):
        self._switch_build(self._target_version(), self.settings["addon"])

    def _ensure_packages(self):
        if self.packages is None:
            self.packages = reshade_shaders.fetch_list()
        return self.packages

    def _ensure_autohdr(self):
        """The AutoHDR add-on and the AdvancedAutoHDR effect, downloaded the first time a game uses them."""
        reshade_release.fetch_autohdr(self.reshade_root)
        if AUTOHDR_PACKAGE not in reshade_shaders.installed(self.shaders_root):
            package = next((p for p in self._ensure_packages() if p["id"] == AUTOHDR_PACKAGE), None)
            if not package:
                raise reshade_shaders.ShaderError("ReShade's package list no longer has AdvancedAutoHDR.")
            reshade_shaders.install(self.shaders_root, package)

    def _setup(self, autohdr):
        """First setup: ReShade, the compiler, the default shaders and, when asked for, AutoHDR."""
        self._apply_version()
        if not reshade_shaders.installed(self.shaders_root):
            for package in self._ensure_packages():
                if package["default"] or package["required"]:
                    reshade_shaders.install(self.shaders_root, package)
        if autohdr:
            self._ensure_autohdr()

    def _update(self):
        if self.settings["version"] != "latest":
            return
        latest = self._check()
        installed = self._installed()
        if latest and installed and reshade_release.version_tuple(latest) > reshade_release.version_tuple(installed):
            self._switch_build(latest, self.release.get("addon", False))

    async def setup(self, addon: bool, version: str, autohdr: bool) -> dict:
        """The first-run wizard's choices: build, version, AutoHDR."""
        self.settings["addon"] = bool(addon)
        self.settings["version"] = version if version in reshade_release.VERSIONS else "latest"
        self._save_settings()
        decky.logger.info(f"setup: addon={addon} version={self.settings['version']} autohdr={autohdr}")
        return await self._job("Downloading ReShade…", self._setup, bool(autohdr and addon))

    async def check_reshade(self) -> dict:
        """Only look at reshade.me; the panel then offers the update."""
        await asyncio.to_thread(self._check)
        return await self.get_state()

    async def update_reshade(self, quiet: bool = False) -> dict:
        """Check reshade.me and move every game to a newer ReShade; also the startup auto-update (quiet)."""
        return await self._job("Checking for a new ReShade…", self._update, quiet=quiet)

    async def load_packages(self) -> dict:
        try:
            await asyncio.to_thread(self._ensure_packages)
        except reshade_shaders.ShaderError as e:
            decky.logger.error(f"package list: {e}")
            self.job = {"task": "", "error": str(e)}
        return await self.get_state()

    async def set_package(self, pid: str, on: bool) -> dict:
        package = next((p for p in self.packages or [] if p["id"] == pid), None)
        if not package:
            return await self.get_state()
        if on:
            return await self._job(f"Downloading {package['name']}…", reshade_shaders.install, self.shaders_root,
                                   package)
        return await self._job(f"Removing {package['name']}…", reshade_shaders.remove, self.shaders_root, pid)

    def _update_shaders(self):
        for package in self._ensure_packages():
            if package["id"] in reshade_shaders.installed(self.shaders_root):
                reshade_shaders.install(self.shaders_root, package)

    async def update_shaders(self) -> dict:
        return await self._job("Updating shaders…", self._update_shaders)

    def _remove_data(self):
        if self.manifest.entries:
            raise reshade_install.InstallError("Turn ReShade off in all games first; they still use these files.")
        for path in (self.reshade_root, self.shaders_root, self.renodx_root):
            shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path, exist_ok=True)
        self.release = {}
        self._save_release()
        self.packages = None

    async def remove_data(self) -> dict:
        """Delete everything downloaded (ReShade, compiler, add-ons, shaders); the setup wizard shows again."""
        return await self._job("Removing downloaded files…", self._remove_data)

    # ---- games ---------------------------------------------------------------------------------------------------

    def _game(self, appid):
        return next((g for g in self.games if g["appid"] == appid), None)

    def _current_options(self, game, from_steam):
        """A shortcut's launch options as Steam stored them (its app details do not carry them reliably)."""
        if not game.get("nonsteam"):
            return from_steam
        fresh = next((g for g in reshade_games.shortcuts(_steam_root()) if g["appid"] == game["appid"]), None)
        return fresh["launch_options"] if fresh else from_steam

    async def get_game(self, appid: int, exe: str = "", renodx: str = "") -> dict:
        """What the panel shows for one game: executables, the chosen one, bitness, API, AutoHDR, the RenoDX mod
        (the one installed, else renodx when the user picked one, else the matched one) and ReShade's log."""
        await _ready.wait()
        game = self._game(appid)
        if not game:
            return {"ok": False, "error": "Game not found; close and reopen this menu to rescan the library."}
        found = await asyncio.to_thread(reshade_games.inspect, game)
        entry = self.manifest.entries.get(appid)
        candidates = found["candidates"]
        chosen = next((c for c in candidates if c["exe"] == (exe or (entry or {}).get("exe"))), None)
        if not chosen and entry:  # set up for an executable no longer offered: still show it
            chosen = {"exe": entry["exe"], "bits": entry["bits"]}
            candidates = [chosen] + candidates
        chosen = chosen or (candidates[0] if candidates else None)
        if not chosen:
            return {"ok": False, "error": "No Windows executable found in this game's folder (a native Linux game?)."}
        api, how = await asyncio.to_thread(reshade_games.detect_api, os.path.join(game["install_dir"], chosen["exe"]))
        folder = os.path.dirname(os.path.join(game["install_dir"], chosen["exe"]))
        auto = self.renodx_match.get(appid)
        installed = entry.get("renodx", "") if entry else ""
        mod = self._mod(installed or renodx) if installed or renodx else auto
        return {"ok": True, "candidates": candidates, "exe": chosen["exe"], "bits": chosen["bits"],
                "detected_api": api, "detected_how": how, "anticheat": found["anticheat"],
                "nonsteam": game.get("nonsteam", False), "enabled": entry is not None,
                "api": entry["api"] if entry else None, "autohdr": bool(entry and entry.get("autohdr")),
                "renodx": {"installed": installed, "auto": auto["name"] if auto else "",
                           "mod": {**mod, "files": sorted(mod["files"])} if mod else None},
                "log": reshade_diag.reshade_log(folder)}

    async def enable_game(self, appid: int, exe: str, api: str, autohdr: bool, renodx: str,
                          launch_options: str, dlo_installed: bool = False) -> dict:
        """Set ReShade up for one game, with AutoHDR or a RenoDX mod (by its name in the list); when it already is
        with other choices, that is undone first. A RenoDX mod is downloaded again each time (snapshot builds).

        dlo_installed: Decky Launch Options is running. It takes over a game's launch options whenever the game's
        library page is shown (they become its stored original), so anything written there could not be taken out
        again; its ReShade tab is used instead and the launch options are left alone."""
        await _ready.wait()
        game = self._game(appid)
        if not game:
            return {"ok": False, "error": "Game not found; close and reopen this menu to rescan the library."}
        if api not in reshade_games.APIS:
            return {"ok": False, "error": "Pick the graphics API by hand: Vulkan games are not supported yet."}
        if not self._installed():
            return {"ok": False, "error": "Set up ReShade first."}
        if autohdr and not (self.release.get("addon") and api in reshade_games.DXGI_APIS):
            return {"ok": False, "error": "AutoHDR needs the add-on build and a DirectX 10/11/12 game."}
        mod = self._mod(renodx) if renodx else None
        if renodx and not mod:
            return {"ok": False, "error": "That RenoDX mod is no longer in the list; refresh it in Settings."}
        if mod and not self.release.get("addon"):
            return {"ok": False, "error": "RenoDX needs the add-on build (Settings)."}
        if mod and autohdr:
            return {"ok": False, "error": "Use RenoDX or AutoHDR, not both: together they tone-map twice."}
        install_dir = os.path.realpath(game["install_dir"])
        path = os.path.realpath(os.path.join(install_dir, exe))
        if not path.startswith(install_dir + os.sep) or not os.path.isfile(path):
            return {"ok": False, "error": "That executable is not in the game's folder any more; close and reopen this menu."}
        info = reshade_games.pe_info(path)
        if not info:
            return {"ok": False, "error": "That file is not a Windows executable."}
        options = self._current_options(game, launch_options)
        # A game Decky Launch Options runs gets its ReShade option there; we only put the files in place.
        dlo = dlo_installed or reshade_install.dlo_managed(options)
        decky.logger.info(f"enable {appid} '{game['name']}': {exe} {info['bits']}-bit api={api} autohdr={autohdr} "
                          f"renodx={renodx!r} dlo={dlo} options before: {options!r}")
        async with self.lock:
            entry = self.manifest.entries.get(appid)
            try:
                renodx_file = None
                if mod:
                    renodx_file = os.path.basename(
                        await asyncio.to_thread(reshade_renodx.download, mod, info["bits"], self.renodx_root))
                if autohdr:
                    await asyncio.to_thread(self._ensure_autohdr)
                if entry and (entry["exe"], entry["api"], bool(entry.get("autohdr")), entry.get("renodx", "")) != \
                        (exe, api, bool(autohdr), renodx):
                    options = (await asyncio.to_thread(reshade_install.disable, self.manifest, appid,
                                                       options))["launch_options"]
                options = await asyncio.to_thread(
                    reshade_install.enable, self.manifest, game, exe, api, info["bits"],
                    self._sources(api, info["bits"], autohdr, renodx_file), self.shaders_root, options,
                    self.settings["auto_launch_options"] and not dlo, AUTOHDR_ENV if autohdr or mod else (),
                    reshade_install.autohdr_preset() if autohdr else None)
                self.manifest.entries[appid].update(autohdr=bool(autohdr), renodx=renodx, renodx_file=renodx_file)
                await asyncio.to_thread(self.manifest.save)
            # any failure: the panel must still get the options, which a first disable() may already have restored
            except Exception as e:
                decky.logger.exception(f"enable {appid} failed")
                return {"ok": False, "error": str(e), "launch_options": options}
        decky.logger.info(f"enable {appid} done, options after: {options!r}")
        return {"ok": True, "launch_options": options, "dlo": dlo}

    async def disable_game(self, appid: int, launch_options: str) -> dict:
        await _ready.wait()
        game = self._game(appid)
        options = self._current_options(game, launch_options) if game else launch_options
        async with self.lock:
            try:
                result = await asyncio.to_thread(reshade_install.disable, self.manifest, appid, options)
            except Exception as e:  # the game stays set up; Steam's launch options are left as they are
                decky.logger.exception(f"disable {appid} failed")
                return {"ok": False, "error": str(e)}
        decky.logger.info(f"disable {appid}: kept={result['kept']} options {options!r} -> {result['launch_options']!r}")
        left = reshade_install.dlo_leftover(_dlo_original(appid))
        if left:
            decky.logger.warning(f"disable {appid}: Decky Launch Options still stores {left!r}")
            result["dlo_leftover"] = left
        return {"ok": True, **result}

    async def session_started(self, appid: int) -> dict:
        await _ready.wait()
        if appid in self.manifest.entries:
            self.sessions[appid] = time.time()
            decky.logger.info(f"session started: {appid}")
        return {"managed": appid in self.manifest.entries}

    async def session_ended(self, appid: int) -> dict:
        """Whether ReShade ran in the session that just ended: its log in the game folder is the proof.

        One session without it is often a launcher closed early; twice in a row is worth a warning.
        """
        await _ready.wait()
        entry, started = self.manifest.entries.get(appid), self.sessions.pop(appid, None)
        if not entry or started is None:
            return {"managed": bool(entry)}
        loaded = reshade_install.loaded_since(entry, started)
        summary = reshade_diag.reshade_log(entry["target_dir"])
        decky.logger.info(f"session ended: {appid} loaded={loaded} log errors={summary['errors']}")
        async with self.lock:
            entry["missed"] = 0 if loaded else entry.get("missed", 0) + 1
            await asyncio.to_thread(self.manifest.save)
        if loaded or entry["missed"] < 2:
            return {"managed": True, "loaded": loaded}
        decky.logger.warning(f"ReShade did not load in {appid} twice: {entry['exe']} {entry['api']}")
        return {"managed": True, "loaded": False, "warning": (
            f"ReShade did not start in {entry['name']} twice in a row. Pick another executable or graphics API "
            "for it in DeckyReshade, or check that its launch options (or its ReShade choice in Decky Launch Options) "
            "still set WINEDLLOVERRIDES.")}

    # ---- logs ----------------------------------------------------------------------------------------------------

    async def get_logs(self, appid: int = 0) -> dict:
        """The end of the plugin's log and, for a game, of its ReShade.log."""
        await _ready.wait()
        folder = ""
        entry = self.manifest.entries.get(appid)
        if entry:
            folder = entry["target_dir"]
        elif (game := self._game(appid)) and (found := (await self.get_game(appid)))["ok"]:
            folder = os.path.dirname(os.path.join(game["install_dir"], found["exe"]))
        return {"plugin": reshade_diag.tail(reshade_diag.plugin_log_path(decky), 300),
                "reshade": reshade_diag.tail(os.path.join(folder, reshade_install.LOG), 200) if folder else ""}

    def _report(self):
        header = [("Plugin", VERSION), ("System", reshade_diag.os_release()), ("Settings", self.settings),
                  ("ReShade", f"{self._installed()} addon={self.release.get('addon')} "
                              f"latest={self.release.get('latest')} check_error={self.release.get('check_error', '')!r}"),
                  ("AutoHDR files", self._autohdr_ready()),
                  ("Shader packages", ", ".join(reshade_shaders.installed(self.shaders_root)) or "none"),
                  ("Library", f"{len(self.games)} games")]
        games = []
        for appid, e in self.manifest.entries.items():
            details = {"appid": appid, "folder": e["target_dir"], "exe": e["exe"], "bits": e["bits"], "api": e["api"],
                       "env": e.get("env", []), "autohdr": e.get("autohdr", False), "renodx": e.get("renodx", ""),
                       "files": sorted(e["files"]), "launch options set": e.get("launch_applied"),
                       "missed sessions": e.get("missed", 0), "log": reshade_diag.reshade_log(e["target_dir"])}
            games.append((e["name"], details, reshade_diag.tail(os.path.join(e["target_dir"], reshade_install.LOG), 80)))
        text = reshade_diag.report(header, games, reshade_diag.tail(reshade_diag.plugin_log_path(decky), 400))
        folder = reshade_updates.downloads_dir(_home())
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("DeckyReshade-report-%Y%m%d-%H%M%S.txt"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    async def save_report(self) -> dict:
        """A text report in the Downloads folder, for a bug report."""
        await _ready.wait()
        try:
            async with self.lock:  # the manifest is not read while a game is being changed
                path = await asyncio.to_thread(self._report)
        except Exception as e:
            decky.logger.exception("report failed")
            return {"error": f"The report could not be saved: {e}"}
        decky.logger.info(f"report saved: {path}")
        return {"path": path}

    # ---- plugin updates ------------------------------------------------------------------------------------------

    async def check_for_updates(self) -> dict:
        return await asyncio.to_thread(reshade_updates.check, VERSION)

    async def perform_update(self, expected_version: str) -> dict:
        return await asyncio.to_thread(reshade_updates.download, VERSION, expected_version,
                                       reshade_updates.downloads_dir(_home()))

    async def _unload(self):
        pass

    async def _uninstall(self):
        # Decky runs this on every plugin *update* too (an update is uninstall + install), so tearing games down here
        # would switch ReShade off everywhere on each update. "Turn off ReShade in all games" in the panel is the
        # cleanup before a real uninstall.
        decky.logger.info(f"uninstall/update: leaving {len(self.manifest.entries)} game(s) set up")
