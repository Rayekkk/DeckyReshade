# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""RenoDX: per-game HDR mods that run as ReShade add-ons (github.com/clshortfuse/renodx).

The list of mods is the "Mods" page of the RenoDX wiki: a Markdown table of name, maintainer, download badges and a
status (:white_check_mark: working, :construction: in progress, or a word such as "Abandoned"; a link title holds a
note). Only the main list is read; engine-wide mods need per-game tweaking and are left out. A mod can be installed
here when the table links its .addon64/.addon32 file directly, from the GitHub Pages or GitHub releases of an author
in AUTHORS; mods only on Nexus Mods or Discord, or from anyone else, are shown with their status and a link and must
be installed by hand.

The wiki is open to any GitHub user, so the list alone cannot say what is safe to put into a game. A file is
installed only from a known author's GitHub release (<author>.github.io/<repo>/<file> is published as the release
"snapshot" of github.com/<author>/<repo>), and only when it matches the SHA-256 GitHub reports for that release asset
and is a Windows DLL of the expected bitness. Snapshot builds change daily, so their sums cannot be pinned here;
GitHub's own sum guards against a changed list, a bad mirror or a cut-off download, not against a taken-over author
account.
"""

import os
import re
import unicodedata
import urllib.parse

import dk_fs
import dk_net
from dk_update import ASSET_HOSTS as GITHUB_DOWNLOADS
from reshade_games import pe_info

LIST_URL = "https://raw.githubusercontent.com/wiki/clshortfuse/renodx/Mods.md"
MAX_LIST = 4 << 20
MAX_ADDON = 64 << 20
MAX_RELEASE = 8 << 20  # GitHub's description of a release with 500+ assets is about 1 MB
# GitHub accounts of the RenoDX authors whose add-ons can be installed from here: every account the wiki's mod list
# linked a file from on 2026-10-27 (24 accounts, 275 files). A new author is added here and ships with a plugin release.
AUTHORS = frozenset({
    "akuru-q", "chrisboyer2", "clshortfuse", "commandgenius", "danaforever", "hartapfel", "hboyyt", "itsthesewerrat",
    "izueh", "jhi721", "legoliamneeson", "marat569", "mohannedelfatih", "mqhaji", "notvoosh", "oopydoopy", "pmnoxx",
    "rankftw", "sgtforgery", "skyline330", "souperman9", "steve161803", "theedmaster87", "toru77",
})
_FILE = re.compile(r"\((https://[^)\s]+?/([\w.-]+?\.addon(32|64)))\)")
_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_NOTE = re.compile(r'\(#\s*"([^"]*)"\)')
_PAGES = re.compile(r"https://([A-Za-z0-9-]+)\.github\.io/([\w.-]+)/([\w.-]+\.addon(?:32|64))")
_RELEASE = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([\w.-]+)/releases/download/([\w.-]+)/"
                      r"([\w.-]+\.addon(?:32|64))")
_DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")


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


def source(url):
    """(author, repo, release tag, file) of a mod file a known author publishes on GitHub, else None."""
    if match := _PAGES.fullmatch(url or ""):
        author, repo, tag, name = match[1], match[2], "snapshot", match[3]
    elif match := _RELEASE.fullmatch(url or ""):
        author, repo, tag, name = match.groups()
    else:
        return None
    return (author, repo, tag, name) if author.lower() in AUTHORS else None


def trusted(url):
    return source(url) is not None


def host(url):
    """Where a mod's file comes from, shown before it is installed: 'github.com/mqhaji', or '' for none."""
    found = source(url)
    return f"github.com/{found[0]}" if found else ""


def _status(cell):
    note = _NOTE.search(cell)
    if "white_check_mark" in cell or "✅" in cell:  # the shortcode or the emoji itself
        return "working", note.group(1) if note else ""
    if "construction" in cell or "\U0001f6a7" in cell:
        return "wip", note.group(1) if note else ""
    return "other", re.sub(r"[\[\]*_`]", "", _LINK.sub(r"\1", cell)).strip()


def parse(text):
    """Mods of the main list: {name, maintainer, status: working|wip|other, note, files: {"64"|"32": url}, page}.
    files holds only known authors' files; a mod without any keeps a link (its page, or another file) in page."""
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
        linked = _FILE.findall(cells[2])
        files = {bits: url for url, _, bits in linked if trusted(url)}
        # badges are images inside links: [![Nexus Mods](badge)](page); a file from an unknown author is a link only
        page = next((url for url in re.findall(r"\]\((https?://[^)\s]+)\)", cells[2])
                     if "img.shields.io" not in url and not url.endswith((".addon64", ".addon32"))), "") or \
            next((url for url, _, _ in linked if not trusted(url)), "")
        status, note = _status(cells[3])
        if name:
            mods.append({"name": name, "maintainer": cells[1], "status": status, "note": note, "files": files,
                         "page": page})
    if not mods:
        raise RenoDXError("The RenoDX mod list is empty.")
    return mods


def fetch_list(cancel=None):
    try:
        return parse(dk_net.get(LIST_URL, MAX_LIST, hosts={"raw.githubusercontent.com"}, cancel=cancel)
                     .decode("utf-8", "replace"))
    except dk_net.NetError as e:
        raise RenoDXError(f"Could not load the RenoDX mod list: {e}.") from e


def match(name, mods):
    """The mod for a game name: the same name first, then the same name without bracketed parts; None if none."""
    for reduce in (key, base_key):
        wanted = reduce(name)
        found = next((m for m in mods if wanted and reduce(m["name"]) == wanted), None)
        if found:
            return found
    return None


def _asset(author, repo, tag, name, cancel):
    """(address, size, SHA-256) of a release asset as GitHub describes it; RenoDXError when GitHub cannot vouch for it."""
    api = f"https://api.github.com/repos/{author}/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    try:
        release = dk_fs.parse_json(dk_net.get(api, MAX_RELEASE, hosts={"api.github.com"}, redirects=False,
                                              headers={"Accept": "application/vnd.github+json"}, cancel=cancel),
                                   dk_fs.require_object)
    except dk_net.NetError as e:
        if e.status == 404:
            raise RenoDXError(f"{author} has no RenoDX release named {tag} on GitHub; install the mod by hand.") from e
        raise RenoDXError(f"GitHub could not describe the RenoDX release of {author}: {e}.") from e
    except ValueError as e:
        raise RenoDXError("GitHub returned an unreadable RenoDX release.") from e
    url = f"https://github.com/{author}/{repo}/releases/download/{tag}/{name}"
    assets = [a for a in release.get("assets") or [] if isinstance(a, dict) and a.get("name") == name]
    asset = assets[0] if len(assets) == 1 else {}
    digest, size = _DIGEST.fullmatch(str(asset.get("digest"))), asset.get("size")
    if (not digest or asset.get("state") != "uploaded" or type(size) is not int or not 0 < size <= MAX_ADDON
            or str(asset.get("browser_download_url")).lower() != url.lower()):
        raise RenoDXError(f"{name} is not in {author}'s release with a SHA-256 from GitHub; install the mod by hand.")
    return asset["browser_download_url"], size, digest.group(1).lower()


def download(mod, bits, folder, cancel=None):
    """Fetch a mod's add-on for one bitness into folder, from its author's GitHub release and checked against the
    SHA-256 GitHub reports for it; returns its path."""
    url = mod["files"].get(str(bits))
    if not url:
        have = " and ".join(f"{b}-bit" for b in sorted(mod["files"])) or "no direct download"
        raise RenoDXError(f"{mod['name']}: the RenoDX list has {have}, but this game is {bits}-bit.")
    found = source(url)
    if not found:  # a list saved by an older version can still hold one
        raise RenoDXError(f"{mod['name']} is not from a RenoDX author this plugin knows; install it by hand.")
    address, size, sha256 = _asset(*found, cancel)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, found[3])
    new = path + ".new"  # a failed update keeps the copy that worked
    try:
        dk_net.download(address, new, size, sha256, hosts=GITHUB_DOWNLOADS, cancel=cancel)
    except dk_net.NetError as e:
        raise RenoDXError(f"The RenoDX mod could not be downloaded: {e}.") from e
    if (pe_info(new) or {}).get("bits") != bits:
        os.remove(new)
        raise RenoDXError(f"The RenoDX download for {mod['name']} is not a {bits}-bit add-on.")
    os.replace(new, path)
    return path
