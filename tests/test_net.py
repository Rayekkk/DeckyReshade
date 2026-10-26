# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Downloads: complete files only."""

import http.client
import io
import os
import tempfile
import unittest
from unittest import mock

import _harness  # noqa: F401
import reshade_net as N


class _Response(io.BytesIO):
    def __init__(self, data, length=None, fail=None):
        super().__init__(data)
        self.length, self.fail = length, fail

    def getheader(self, name):
        return str(self.length) if name == "Content-Length" and self.length is not None else None

    def read(self, n=-1):
        if self.fail and self.tell() >= len(self.getvalue()):
            raise self.fail
        return super().read(n)


class Download(unittest.TestCase):
    def test_only_complete_files_are_kept(self):
        dest = os.path.join(tempfile.mkdtemp(), "file")
        with mock.patch.object(N, "_open", return_value=_Response(b"abc", 3)):
            N.download("https://x.github.io/f", dest, 10)
        self.assertTrue(os.path.exists(dest))
        os.remove(dest)
        for response in (_Response(b"ab", 3),  # the connection dropped: fewer bytes than announced
                         _Response(b"ab", fail=http.client.IncompleteRead(b"")),  # a chunked body cut off
                         _Response(b"x" * 11)):  # more than allowed
            with mock.patch.object(N, "_open", return_value=response):
                self.assertRaises(N.NetError, N.download, "https://x.github.io/f", dest, 10)
            self.assertEqual(os.listdir(os.path.dirname(dest)), [])


if __name__ == "__main__":
    unittest.main()
