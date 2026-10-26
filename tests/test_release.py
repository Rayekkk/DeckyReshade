# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""ReShade version check, installer unpacking and the pinned fallback."""

import io
import os
import tempfile
import unittest
import zipfile
from unittest import mock

import _harness  # noqa: F401
import reshade_net
import reshade_release as R
from _pe import make_pe


def installer(dll64=None, dll32=None):
    """What reshade.me serves: a Windows program with a ZIP archive appended."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # a fixed date: the same arguments must give the same bytes (tests pin their SHA-256)
        for name, data in (("ReShade64.dll", dll64 if dll64 is not None else make_pe(64)),
                           ("ReShade32.dll", dll32 if dll32 is not None else make_pe(32)), ("ReShade64.json", "{}")):
            z.writestr(zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)), data)
    return make_pe(32, [], b"\0" * 1000) + buf.getvalue()


def serve(data):
    """A stand-in for reshade_net.download that writes data and returns its hash like the real one."""
    def download(url, dest, limit, sha256=None, progress=None):
        with open(dest, "wb") as f:
            f.write(data)
        digest = reshade_net.sha256_file(dest)
        if sha256 and digest != sha256:
            os.remove(dest)
            raise reshade_net.NetError("does not match its known SHA-256")
        download.urls.append(url)
        return digest
    download.urls = []
    return download


class LatestVersion(unittest.TestCase):
    def test_newest_linked_version_wins(self):
        page = (b'<a href="/downloads/ReShade_Setup_6.9.1.exe">x</a><a href="/downloads/ReShade_Setup_6.9.1_Addon.exe">'
                b'</a> older: /downloads/ReShade_Setup_6.10.0_Addon.exe /downloads/ReShade_Setup_6.8.0.exe')
        with mock.patch.object(reshade_net, "get", return_value=page):
            self.assertEqual(R.latest_version(), "6.10.0")

    def test_page_without_links_or_offline_is_an_error_not_a_guess(self):
        with mock.patch.object(reshade_net, "get", return_value=b"<html>new design</html>"):
            self.assertRaises(R.ReleaseError, R.latest_version)
        with mock.patch.object(reshade_net, "get", side_effect=reshade_net.NetError("could not reach reshade.me")):
            self.assertRaises(R.ReleaseError, R.latest_version)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_unpacks_both_dlls(self):
        with mock.patch.object(reshade_net, "download", serve(installer())) as dl:
            folder = R.fetch(self.root, "6.9.0", True)
        self.assertEqual(folder, os.path.join(self.root, "6.9.0-addon"))
        self.assertTrue(R.is_complete(folder))
        self.assertEqual(dl.urls, ["https://reshade.me/downloads/ReShade_Setup_6.9.0_Addon.exe"])
        self.assertEqual(sorted(os.listdir(folder)), ["ReShade32.dll", "ReShade64.dll"])

    def test_already_there_is_not_downloaded_again(self):
        with mock.patch.object(reshade_net, "download", serve(installer())):
            R.fetch(self.root, "6.9.0", False)
        with mock.patch.object(reshade_net, "download", side_effect=AssertionError("downloaded twice")):
            R.fetch(self.root, "6.9.0", False)

    def test_wrong_bitness_or_not_an_installer_leaves_nothing(self):
        for data in (installer(dll64=make_pe(32)), installer(dll32=b"not a dll"), b"<html>error page</html>"):
            with mock.patch.object(reshade_net, "download", serve(data)):
                self.assertRaises(R.ReleaseError, R.fetch, self.root, "6.9.0", False)
            self.assertEqual(os.listdir(self.root), [])

    def test_known_versions_need_their_hash(self):
        for version in R.VERSIONS:
            with mock.patch.object(reshade_net, "download", serve(installer())):
                self.assertRaises(R.ReleaseError, R.fetch, self.root, version, True)
        self.assertEqual(os.listdir(self.root), [])
        self.assertEqual(R.FALLBACK, R.VERSIONS[0])
        self.assertEqual(R.VERSIONS, sorted(R.VERSIONS, key=R.version_tuple, reverse=True))

    def test_prune_keeps_only_the_build_in_use(self):
        for name in ("6.8.0", "6.9.0-addon", "6.9.0.part", "unrelated"):
            os.makedirs(os.path.join(self.root, name))
        open(os.path.join(self.root, "d3dcompiler_47.64.dll"), "w").close()
        R.prune(self.root, {"6.9.0-addon"})
        self.assertEqual(sorted(os.listdir(self.root)), ["6.9.0-addon", "d3dcompiler_47.64.dll", "unrelated"])


class PinnedFiles(unittest.TestCase):
    def test_fetched_with_the_pinned_hash_and_skipped_when_present(self):
        for fetch, files, path_for in ((R.fetch_compilers, R.COMPILERS, R.compiler_path),
                                       (R.fetch_autohdr, R.AUTOHDR, R.autohdr_path)):
            root = tempfile.mkdtemp()
            calls = []

            def download(url, dest, limit, sha256=None, progress=None):
                calls.append((url, sha256))
                with open(dest, "wb") as f:
                    f.write(b"x")
                return sha256

            with mock.patch.object(reshade_net, "download", download):
                fetch(root)
            self.assertEqual(calls, [(c["url"], c["sha256"]) for c in files.values()])
            # files that already match are kept
            known = {path_for(root, bits): c for bits, c in files.items()}
            with mock.patch.object(R.os.path, "getsize", side_effect=lambda p: known[p]["size"]), \
                    mock.patch.object(reshade_net, "sha256_file", side_effect=lambda p: known[p]["sha256"]), \
                    mock.patch.object(reshade_net, "download", side_effect=AssertionError("downloaded again")):
                fetch(root)


if __name__ == "__main__":
    unittest.main()
