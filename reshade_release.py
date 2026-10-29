# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""ReShade itself, fetched from reshade.me on the device, and the shader compiler it needs under Proton.

ReShade is not published on GitHub; its homepage links the current installer as
/downloads/ReShade_Setup_<version>[_Addon].exe, and that link is the version check. The installer is a Windows
program with a ZIP archive appended, which Python's zipfile opens as is (no 7-Zip), and holds ReShade32.dll and
ReShade64.dll. Each DLL is accepted only when its PE header says it is the 32- or 64-bit build its name claims.

KNOWN lists the releases this plugin installs (one per minor version, e.g. 6.5.1 for DXVK HDR games), each with the
SHA-256 of both installers, checked on download. reshade.me publishes no checksums, so only these versions are ever
installed: "latest" means the newest of them (FALLBACK). The homepage still tells when ReShade has a newer release,
which the panel shows; it becomes installable once its sums are added here and the plugin is released. A failed check
never breaks anything: games keep the ReShade they have.

Proton's own d3dcompiler_47 cannot compile ReShade's effects, so Microsoft's is used, from Mozilla's fxc2 repository at
a fixed commit and checked against its SHA-256. The AutoHDR add-on (EndlesslyFlowering, MIT) comes from its GitHub
release, also pinned by SHA-256.
"""

import os
import re
import shutil
import zipfile

import dk_fs
import dk_net
from dk_update import ASSET_HOSTS as GITHUB_DOWNLOADS
from reshade_games import MACHINE_BITS

HOME_URL = "https://reshade.me/"
SETUP_URL = "https://reshade.me/downloads/ReShade_Setup_{version}{suffix}.exe"
# version -> {addon build?: SHA-256 of ReShade_Setup_<version>[_Addon].exe}
KNOWN = {
    "6.8.0": {False: "207aea16205fbf952bc8fe1879966672454cf04002e7ad34237c7990a5b3c0b4",
              True: "afe4c8f13048306307983b8b3d41d5bf00a86820440b0e57dea10950e1176445"},
    "6.7.3": {False: "56791fd065358e899c581ebefe2ad871399b7c7ae83fb85e1154c08a75a44147",
              True: "c78db69bd127e98054bd496fb422655f4a1cc664e28f8d12ce9835b2647bc571"},
    "6.6.2": {False: "807e145eab98903b20f1fc743598a74e3a3be7394ab015b7f64231228168f04e",
              True: "208d710e21e15cd871fe37256bf97aad587620b4602c389453b7e099b7ba3217"},
    "6.5.1": {False: "c384e89427865e119db4daf18c2c225b951a4cd07dbff92b65caf68c2a95ace0",
              True: "3be164186103dcf126af3d75d8efdf850c4ed9f88919505c16a52e6d0ef135a7"},
    "6.4.1": {False: "0b974b8263b4a96276b83e86736729197eaa967ca7b3014b6dbc342f25be21ef",
              True: "130800ad62ee9743f85f24542a7b97fd29b2c18d427f5ad3540cddfeb6ce6e62"},
    "6.3.3": {False: "4ddbdc032a914b567dd8f8caa59a5b785c32b490c0ba3c5040f544824c980a6c",
              True: "7999737f7bd01f0f380311ca4f48c5a3ddce046043b23481f9e0027c9f562b37"},
}
_FXC2 = "https://raw.githubusercontent.com/mozilla/fxc2/9aba9b11079303d5577e0e3eb455f4d00f3b5946/dll/"
COMPILERS = {
    64: {"url": _FXC2 + "d3dcompiler_47.dll", "size": 4346120,
         "sha256": "4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3"},
    32: {"url": _FXC2 + "d3dcompiler_47_32.dll", "size": 3657992,
         "sha256": "2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851"},
}
_AUTOHDR = "https://github.com/EndlesslyFlowering/AutoHDR-ReShade/releases/download/2025.06.04/"
AUTOHDR = {
    64: {"url": _AUTOHDR + "AutoHDR.addon64", "size": 51200,
         "sha256": "e4fc8cb75e6ff5315179eff0cfdbd3386f333a2d2d4911ee199094c887ae8a10"},
    32: {"url": _AUTOHDR + "AutoHDR.addon32", "size": 44544,
         "sha256": "189f09998d7767cf164443f4e5e7bd3af3c16c412ffbfa90bc9e94dd4d559e54"},
}
DLLS = {64: "ReShade64.dll", 32: "ReShade32.dll"}
MAX_PAGE = 2 << 20
MAX_SETUP = 64 << 20
MAX_DLL = 32 << 20
RESHADE_HOSTS = {"reshade.me"}
COMPILER_HOSTS = {"raw.githubusercontent.com"}
_LINK = re.compile(r"/downloads/ReShade_Setup_(\d{1,3}\.\d{1,3}\.\d{1,3})(?:_Addon)?\.exe")


class ReleaseError(Exception):
    pass


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


VERSIONS = sorted(KNOWN, key=version_tuple, reverse=True)
FALLBACK = VERSIONS[0]  # the newest version with known sums: what "latest" installs


def latest_version(cancel=None):
    """The newest version reshade.me links; raises ReleaseError when it cannot be told."""
    try:
        page = dk_net.get(HOME_URL, MAX_PAGE, hosts=RESHADE_HOSTS, cancel=cancel).decode("utf-8", "replace")
    except dk_net.NetError as e:
        raise ReleaseError(f"Could not check for a new ReShade: {e}.") from e
    versions = _LINK.findall(page)
    if not versions:
        raise ReleaseError("reshade.me no longer shows a download link the plugin understands.")
    return max(versions, key=version_tuple)


def variant(version, addon):
    """Folder name of one ReShade build: '6.8.0' or '6.8.0-addon'."""
    return f"{version}-addon" if addon else version


def dll_path(root, version, addon, bits):
    return os.path.join(root, variant(version, addon), DLLS[bits])


def is_complete(folder):
    return all(os.path.isfile(os.path.join(folder, name)) for name in DLLS.values())


def _machine(data):
    """Bitness from a PE header held in memory, None when it is not one."""
    if data[:2] != b"MZ" or len(data) < 64:
        return None
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if data[pe:pe + 4] != b"PE\0\0":
        return None
    return MACHINE_BITS.get(int.from_bytes(data[pe + 4:pe + 6], "little"))


def extract(setup, folder):
    """Write ReShade32.dll and ReShade64.dll from an installer into folder."""
    try:
        with zipfile.ZipFile(setup) as archive:
            for bits, name in DLLS.items():
                if archive.getinfo(name).file_size > MAX_DLL:
                    raise ReleaseError(f"{name} in the installer is larger than expected.")
                data = archive.read(name)
                if _machine(data) != bits:
                    raise ReleaseError(f"{name} in the installer is not a {bits}-bit Windows DLL.")
                # synced: is_complete only sees that the file exists, so a DLL emptied by a power cut would stay
                dk_fs.write_atomic(os.path.join(folder, name), data)
    except (zipfile.BadZipFile, KeyError) as e:
        raise ReleaseError("The download is not a ReShade installer this plugin can read.") from e


def fetch(root, version, addon, cancel=None):
    """Download one ReShade build into root/<variant>/ unless it is there already; returns that folder. Only versions
    in KNOWN: anything else could not be checked."""
    folder = os.path.join(root, variant(version, addon))
    if is_complete(folder):
        return folder
    if version not in KNOWN:
        raise ReleaseError(f"ReShade {version} has no known SHA-256 in this DeckyReshade version, so it is not "
                           "installed; it comes with a plugin update.")
    part = folder + ".part"
    shutil.rmtree(part, ignore_errors=True)
    os.makedirs(part)
    try:
        setup = os.path.join(part, "setup.exe")
        url = SETUP_URL.format(version=version, suffix="_Addon" if addon else "")
        pinned = KNOWN[version][addon]
        try:
            dk_net.download(url, setup, MAX_SETUP, pinned, hosts=RESHADE_HOSTS, deadline=dk_net.MAX_DEADLINE,
                            cancel=cancel)
        except dk_net.NetError as e:
            raise ReleaseError(f"ReShade {version} could not be downloaded: {e}.") from e
        extract(setup, part)
        os.remove(setup)
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(part, folder)
    except OSError as e:
        raise ReleaseError(f"ReShade could not be saved ({dk_fs.shown(e)}).") from e
    finally:
        shutil.rmtree(part, ignore_errors=True)
    return folder


def compiler_path(root, bits):
    return os.path.join(root, f"d3dcompiler_47.{bits}.dll")


def _fetch_pinned(files, path_for, what, hosts, cancel):
    """Download files ({bits: {url, size, sha256}}) unless a matching copy is there; only verified files are kept."""
    for bits, known in files.items():
        path = path_for(bits)
        try:
            if os.path.getsize(path) == known["size"] and dk_fs.sha256_file(path) == known["sha256"]:
                continue
        except OSError:
            pass  # no usable copy yet: download it
        try:
            dk_net.download(known["url"], path, known["size"], known["sha256"], hosts=hosts, cancel=cancel)
        except dk_net.NetError as e:
            raise ReleaseError(f"{what} could not be downloaded: {e}.") from e


def fetch_compilers(root, cancel=None):
    """Microsoft's d3dcompiler_47 for both bitnesses."""
    _fetch_pinned(COMPILERS, lambda bits: compiler_path(root, bits), "The shader compiler", COMPILER_HOSTS, cancel)


def autohdr_path(root, bits):
    return os.path.join(root, f"AutoHDR.addon{bits}")


def fetch_autohdr(root, cancel=None):
    """The AutoHDR add-on for both bitnesses."""
    _fetch_pinned(AUTOHDR, lambda bits: autohdr_path(root, bits), "The AutoHDR add-on", GITHUB_DOWNLOADS, cancel)


def prune(root, keep):
    """Remove ReShade builds other than the folder names in keep (each game holds its own copy)."""
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if re.fullmatch(r"\d+\.\d+\.\d+(-addon)?(\.part)?", name) and name not in keep:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
