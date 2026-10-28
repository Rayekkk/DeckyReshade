# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Shader package list, archive layout and shared-file bookkeeping."""

import io
import os
import tempfile
import unittest
import zipfile
from unittest import mock

import _harness  # noqa: F401
import dk_fs
import dk_net
import reshade_shaders as S

LIST = """
[00]
Enabled=1
Required=1
PackageName=Standard effects
InstallPath=.\\reshade-shaders\\Shaders
TextureInstallPath=.\\reshade-shaders\\Textures
DownloadUrl=https://github.com/crosire/reshade-shaders/archive/slim.zip

[01]
PackageName=OtisFX by Otis_Inf
PackageDescription=Cinematic DOF, ...
InstallPath=.\\reshade-shaders\\Shaders\\OtisFX
TextureInstallPath=.\\reshade-shaders\\Textures\\OtisFX
DownloadUrl=https://github.com/FransBouma/OtisFX/archive/master.zip
DenyEffectFiles=Template.fx

[02]
PackageName=Somewhere else
DownloadUrl=https://example.com/pack.zip

[03]
PackageName=Escape
InstallPath=.\\reshade-shaders\\Shaders\\..\\..\\..
DownloadUrl=https://github.com/x/y/archive/master.zip
"""


def archive(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def serve(data):
    def download(url, dest, limit, sha256=None, **kw):
        with open(dest, "wb") as f:
            f.write(data)
    return download


class PackageList(unittest.TestCase):
    def test_parse(self):
        packages = S.parse_list(LIST)
        self.assertEqual([p["id"] for p in packages], ["standard-effects", "otisfx-by-otis-inf", "escape"])
        std, otis, escape = packages
        self.assertTrue(std["default"] and std["required"])
        self.assertEqual((std["shaders"], otis["shaders"], otis["textures"]), ("", "OtisFX", "OtisFX"))
        self.assertEqual(otis["deny"], ["template.fx"])
        self.assertEqual(escape["shaders"], "")  # a path climbing out falls back to the shared folder
        self.assertRaises(S.ShaderError, S.parse_list, "[00]\nPackageName=x\n")


class Layout(unittest.TestCase):
    def test_destination(self):
        otis = {"shaders": "OtisFX", "textures": "OtisFX", "deny": ["template.fx"]}
        plain = {"shaders": "", "textures": "", "deny": []}
        cases = [
            ("OtisFX-master/Shaders/CinematicDOF.fx", otis, "Shaders/OtisFX/CinematicDOF.fx"),
            ("OtisFX-master/Textures/lens.png", otis, "Textures/OtisFX/lens.png"),
            ("OtisFX-master/Shaders/Template.fx", otis, None),
            ("OtisFX-master/README.md", otis, None),
            ("repo-main/src/Effect.fx", plain, "Shaders/src/Effect.fx"),  # no Shaders folder: kept as laid out
            ("repo-main/reshade-shaders/Shaders/Sub/A.fxh", plain, "Shaders/Sub/A.fxh"),
            ("repo-main/../../evil.fx", plain, None),
            ("repo-main/Shaders/C:evil.fx", plain, None),
        ]
        for member, package, want in cases:
            self.assertEqual(S.destination(member, package), want, member)


class InstallRemove(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.std, self.otis = S.parse_list(LIST)[:2]

    def install(self, package, files):
        with mock.patch.object(dk_net, "download", serve(archive(files))):
            return S.install(self.root, package)

    def test_shared_header_stays_while_a_package_needs_it(self):
        self.install(self.std, {"reshade-shaders-slim/Shaders/ReShade.fxh": "std",
                                "reshade-shaders-slim/Shaders/Deband.fx": "x"})
        self.install(self.otis, {"OtisFX-master/Shaders/ReShade.fxh": "otis",
                                 "OtisFX-master/Shaders/CinematicDOF.fx": "x"})
        self.assertEqual(S.installed(self.root), ["otisfx-by-otis-inf", "standard-effects"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Shaders", "OtisFX", "CinematicDOF.fx")))
        S.remove(self.root, self.std["id"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "Shaders", "Deband.fx")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "Shaders", "OtisFX", "ReShade.fxh")))
        self.assertEqual(S.installed(self.root), ["otisfx-by-otis-inf"])

    def test_update_drops_files_the_package_no_longer_has(self):
        self.install(self.std, {"r/Shaders/Old.fx": "x", "r/Shaders/Keep.fx": "x"})
        self.install(self.std, {"r/Shaders/Keep.fx": "y"})
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "Shaders"))), ["Keep.fx"])

    def test_interrupted_install_leaves_no_untracked_files(self):
        real_replace, moved = os.replace, []

        def replace(src, dst, **kw):
            if "Shaders" in dst and moved:
                raise OSError("disk full")
            real_replace(src, dst, **kw)
            moved.append(dst)

        with mock.patch.object(S.os, "replace", replace):
            self.assertRaises(S.ShaderError, self.install, self.std, {"r/Shaders/A.fx": "x", "r/Shaders/B.fx": "x"})
        self.assertEqual(S.installed(self.root), ["standard-effects"])  # recorded before the files moved in
        S.remove(self.root, self.std["id"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "Shaders", "A.fx")))

    def test_bad_download_changes_nothing(self):
        self.install(self.std, {"r/Shaders/Keep.fx": "x"})
        for files in ({"r/README.md": "no effects"}, None):
            data = archive(files) if files else b"<html>rate limited</html>"
            with mock.patch.object(dk_net, "download", serve(data)):
                self.assertRaises(S.ShaderError, S.install, self.root, self.std)
        self.assertEqual(sorted(os.listdir(self.root)), ["Shaders", "index.json", "index.json.last-good"])
        self.assertEqual(S.installed(self.root), ["standard-effects"])


if __name__ == "__main__":
    unittest.main()
