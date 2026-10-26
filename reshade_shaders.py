# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Shader packages, from the same list ReShade's own installer offers (EffectPackages.ini in crosire/reshade-shaders).

The layout is the official installer's: one Shaders and one Textures folder shared by all packages, a package with
an InstallPath subfolder (OtisFX, Depth3D, ...) inside it. Effects include ReShade.fxh from that shared folder, which
is why packages are not kept apart. Every game's ReShade.ini points at these two folders, so one download serves all
games and an update reaches them at once. index.json remembers which files each package brought, so a package can be
removed without taking files another package still needs.
"""

import configparser
import json
import os
import re
import shutil
import urllib.parse
import zipfile

import reshade_net as net

LIST_URL = "https://raw.githubusercontent.com/crosire/reshade-shaders/list/EffectPackages.ini"
ARCHIVE_HOSTS = {"github.com", "codeload.github.com"}
MAX_LIST = 1 << 20
MAX_ARCHIVE = 256 << 20
MAX_EXPANDED = 1 << 30
KEEP = (".fx", ".fxh", ".h", ".hlsl", ".png", ".jpg", ".jpeg", ".dds", ".bmp", ".tga")
_SAFE_PART = re.compile(r"[^/\\:\0]{1,128}")


class ShaderError(Exception):
    pass


def package_id(name):
    """A stable id for a package: 'SweetFX by CeeJay.dk' -> 'sweetfx-by-ceejay-dk'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "package"


def _subfolder(install_path, kind):
    """'.\\reshade-shaders\\Shaders\\OtisFX' -> 'OtisFX'; '' for the shared folder itself or anything odd."""
    parts = [p for p in install_path.replace("\\", "/").split("/") if p not in ("", ".")]
    lower = [p.lower() for p in parts]
    if kind not in lower:
        return ""
    rest = parts[lower.index(kind) + 1:]
    return "/".join(rest) if rest and all(_SAFE_PART.fullmatch(p) and p != ".." for p in rest) else ""


def parse_list(text):
    """Packages in EffectPackages.ini order:
    {id, name, description, url, default, required, shaders, textures (subfolders), deny: [file names]}."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as e:
        raise ShaderError("The shader package list could not be read.") from e
    packages, seen = [], set()
    for section in parser.sections():
        p = parser[section]
        name, url = p.get("PackageName", "").strip(), p.get("DownloadUrl", "").strip()
        parsed = urllib.parse.urlsplit(url)
        if not name or parsed.scheme != "https" or parsed.hostname not in ARCHIVE_HOSTS:
            continue
        pid = package_id(name)
        if pid in seen:
            continue
        seen.add(pid)
        packages.append({"id": pid, "name": name, "description": p.get("PackageDescription", "").strip(),
                         "url": url, "default": p.get("Enabled") == "1", "required": p.get("Required") == "1",
                         "shaders": _subfolder(p.get("InstallPath", ""), "shaders"),
                         "textures": _subfolder(p.get("TextureInstallPath", ""), "textures"),
                         "deny": [f.strip().lower() for f in p.get("DenyEffectFiles", "").split(",") if f.strip()]})
    if not packages:
        raise ShaderError("The shader package list is empty.")
    return packages


def fetch_list():
    try:
        return parse_list(net.get(LIST_URL, MAX_LIST).decode("utf-8", "replace"))
    except net.NetError as e:
        raise ShaderError(f"Could not load the shader package list: {e}.") from e


def destination(member, package):
    """Where an archive entry goes ('Shaders/...' or 'Textures/...'), or None to skip it.

    Repositories keep effects in a folder named Shaders and images in Textures (at any depth); one without a Shaders
    folder gets its effect files kept as they are laid out.
    """
    parts = member.split("/")[1:]  # GitHub archives wrap everything in <repo>-<branch>/
    if not parts or not all(_SAFE_PART.fullmatch(p) and p not in (".", "..") for p in parts):
        return None
    name = parts[-1].lower()
    if not name.endswith(KEEP) or name in package.get("deny", ()):
        return None
    lower = [p.lower() for p in parts[:-1]]
    for kind in ("shaders", "textures"):
        if kind in lower:
            rest = parts[lower.index(kind) + 1:]
            break
    else:
        kind, rest = "shaders", parts
    sub = package.get(kind, "")
    return "/".join([kind.capitalize()] + ([sub] if sub else []) + rest)


def _load_index(root):
    try:
        with open(os.path.join(root, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        return index if isinstance(index, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_index(root, index):
    tmp = os.path.join(root, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)
    os.replace(tmp, os.path.join(root, "index.json"))


def installed(root):
    return sorted(_load_index(root))


def install(root, package):
    """Download one package and put its files into root/Shaders and root/Textures; returns how many files.

    The archive is checked and unpacked to a temp folder first, so a failed download changes nothing.
    """
    part = os.path.join(root, f".{package['id']}.part")
    shutil.rmtree(part, ignore_errors=True)
    os.makedirs(part)
    archive = os.path.join(part, "package.zip")
    try:
        try:
            net.download(package["url"], archive, MAX_ARCHIVE)
        except net.NetError as e:
            raise ShaderError(f"{package['name']} could not be downloaded: {e}.") from e
        files, total = [], 0
        try:
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    rel = None if member.is_dir() else destination(member.filename, package)
                    if not rel:
                        continue
                    total += member.file_size
                    if total > MAX_EXPANDED:
                        raise ShaderError(f"{package['name']} expands beyond the size limit.")
                    dst = os.path.join(part, "files", *rel.split("/"))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with zf.open(member) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out)
                    files.append(rel)
        except zipfile.BadZipFile as e:
            raise ShaderError(f"{package['name']} is not a readable archive.") from e
        if not any(f.lower().endswith(".fx") for f in files):
            raise ShaderError(f"{package['name']} contains no effect files.")
        index = _load_index(root)
        for rel in files:
            dst = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(part, "files", *rel.split("/")), dst)
        stale = set(index.get(package["id"], [])) - set(files)
        index[package["id"]] = sorted(files)
        _drop(root, stale, index)
        _save_index(root, index)
        return len(files)
    except OSError as e:
        raise ShaderError(f"{package['name']} could not be saved: {e}.") from e
    finally:
        shutil.rmtree(part, ignore_errors=True)


def _drop(root, files, index):
    """Delete files no installed package lists any more."""
    still = {f for owned in index.values() for f in owned}
    for rel in files - still:
        if ".." in rel.split("/"):
            continue
        try:
            os.remove(os.path.join(root, *rel.split("/")))
        except OSError:
            pass


def remove(root, pid):
    index = _load_index(root)
    if pid not in index:
        return
    files = set(index.pop(pid))
    _drop(root, files, index)
    _save_index(root, index)
