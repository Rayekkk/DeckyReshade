# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""RenoDX: per-game HDR mods that run as ReShade add-ons (github.com/clshortfuse/renodx).

The list of mods is the "Mods" page of the RenoDX wiki: a Markdown table of name, maintainer, download badges and a
status (:white_check_mark: working, :construction: in progress, or a word such as "Abandoned"; a link title holds a
note). Only the main list is read; engine-wide mods need per-game tweaking and are left out. A mod can be installed
here when the table links its .addon64/.addon32 file directly (the authors' GitHub Pages or GitHub releases); mods only
on Nexus Mods or Discord are shown with their status but must be installed by hand.

Snapshot builds change often and carry no checksum, so a download is accepted when it comes over HTTPS from one of
those hosts and is a Windows DLL of the expected bitness.
"""

import os
import re
import unicodedata
import urllib.parse

import reshade_net as net
from reshade_games import pe_info

LIST_URL = "https://raw.githubusercontent.com/wiki/clshortfuse/renodx/Mods.md"
MAX_LIST = 4 << 20
MAX_ADDON = 64 << 20
_FILE = re.compile(r"\((https://[^)\s]+?/([\w.-]+?\.addon(32|64)))\)")
_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_NOTE = re.compile(r'\(#\s*"([^"]*)"\)')


class RenoDXError(Exception):
    pass


def key(name):
    """A name reduced for matching: 'God of War Ragnarök™' -> 'godofwarragnarok'."""
    name = re.sub("[™®©]", "", name)  # NFKD would turn ™ into "TM"
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def base_key(name):
    """key() without bracketed parts: 'God of War (2018)' and 'Path of Exile 2 (DX11)' match the store names."""
    return key(re.sub(r"\([^)]*\)", "", name))


def trusted(url):
    """The hosts RenoDX authors publish snapshot builds on."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and (host.endswith(".github.io") or
                                        (host == "github.com" and "/releases/download/" in parts.path))


def host(url):
    """Where a mod's file comes from, shown before it is installed: 'oopydoopy.github.io', 'github.com/mqhaji' (whose
    releases), or '' for none."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    owner = parts.path.strip("/").split("/")[0] if parts.hostname == "github.com" else ""
    return f"{parts.hostname}/{owner}" if owner else parts.hostname or ""


def _status(cell):
    note = _NOTE.search(cell)
    if "white_check_mark" in cell or "✅" in cell:  # the shortcode or the emoji itself
        return "working", note.group(1) if note else ""
    if "construction" in cell or "\U0001f6a7" in cell:
        return "wip", note.group(1) if note else ""
    return "other", re.sub(r"[\[\]*_`]", "", _LINK.sub(r"\1", cell)).strip()


def parse(text):
    """Mods of the main list: {name, maintainer, status: working|wip|other, note, files: {"64"|"32": url}, page}."""
    try:
        section = text.split("\n# List", 1)[1]
    except IndexError as e:
        raise RenoDXError("The RenoDX mod list has a layout this plugin does not understand.") from e
    section = re.split(r"\n#{1,2} ", section, maxsplit=1)[0]  # up to the multi-game mods
    mods = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not line.startswith("|") or cells[0] in ("Name", "") or cells[0].startswith(":-"):
            continue
        name = _LINK.sub(r"\1", cells[0]).strip()
        files = {bits: url for url, _, bits in _FILE.findall(cells[2]) if trusted(url)}
        # badges are images inside links: [![Nexus Mods](badge)](page)
        page = next((url for url in re.findall(r"\]\((https?://[^)\s]+)\)", cells[2])
                     if "img.shields.io" not in url and not url.endswith((".addon64", ".addon32"))), "")
        status, note = _status(cells[3])
        if name:
            mods.append({"name": name, "maintainer": cells[1], "status": status, "note": note, "files": files,
                         "page": page})
    if not mods:
        raise RenoDXError("The RenoDX mod list is empty.")
    return mods


def fetch_list():
    try:
        return parse(net.get(LIST_URL, MAX_LIST).decode("utf-8", "replace"))
    except net.NetError as e:
        raise RenoDXError(f"Could not load the RenoDX mod list: {e}.") from e


def match(name, mods):
    """The mod for a game name: the same name first, then the same name without bracketed parts; None if none."""
    for reduce in (key, base_key):
        wanted = reduce(name)
        found = next((m for m in mods if wanted and reduce(m["name"]) == wanted), None)
        if found:
            return found
    return None


def download(mod, bits, folder):
    """Fetch a mod's add-on for one bitness into folder; returns its path."""
    url = mod["files"].get(str(bits))
    if not url:
        have = " and ".join(f"{b}-bit" for b in sorted(mod["files"])) or "no direct download"
        raise RenoDXError(f"{mod['name']}: the RenoDX list has {have}, but this game is {bits}-bit.")
    filename = _FILE.search(f"({url})").group(2)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    new = path + ".new"  # a failed update keeps the copy that worked
    try:
        net.download(url, new, MAX_ADDON)
    except net.NetError as e:
        raise RenoDXError(f"The RenoDX mod could not be downloaded: {e}.") from e
    if (pe_info(new) or {}).get("bits") != bits:
        os.remove(new)
        raise RenoDXError(f"The RenoDX download for {mod['name']} is not a {bits}-bit add-on.")
    os.replace(new, path)
    return path
