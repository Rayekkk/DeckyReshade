# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""HTTPS reads and downloads with size limits and verified TLS, shared by everything that goes online.

A download is written through a temp file and only renamed into place once it is complete (and matches its
SHA-256 when one is given), so a dropped connection or a full SD card never leaves half a file behind.
"""

import hashlib
import http.client
import os
import ssl
import urllib.error
import urllib.request

TIMEOUT = 30
CHUNK = 1 << 16
USER_AGENT = "DeckyReshade"
CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")


class NetError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ssl_context():
    """Verified TLS. Decky's frozen Python has no CA store of its own, so use certifi (bundled with Decky) or the
    system bundle; verification is never turned off."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    for cafile in CA_FILES:
        if os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _open(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl_context())


def _describe(url, e):
    host = url.split("/")[2] if url.count("/") >= 2 else url
    if isinstance(e, urllib.error.HTTPError):
        return f"{host} answered HTTP {e.code}"
    return f"could not reach {host} ({getattr(e, 'reason', e)})"


def get(url, limit, headers=None):
    """The body of url, at most limit bytes."""
    try:
        with _open(url, headers) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise NetError(_describe(url, e)) from e
    if len(data) > limit:
        raise NetError(f"{url} sent more data than expected")
    return data


def download(url, dest, limit, sha256=None):
    """Save url to dest; returns its SHA-256. With sha256 given, anything else is refused and nothing is kept."""
    tmp = dest + ".part"
    digest, count = hashlib.sha256(), 0
    try:
        with _open(url) as response, open(tmp, "wb") as f:
            expected = response.getheader("Content-Length")
            while chunk := response.read(CHUNK):
                count += len(chunk)
                if count > limit:
                    raise NetError(f"{url} is larger than expected")
                digest.update(chunk)
                f.write(chunk)
        # a connection dropped mid-file ends the read quietly; files without a known hash need this check
        if expected and expected.isdigit() and count != int(expected):
            raise NetError(f"the download of {url} stopped early")
        if sha256 and digest.hexdigest() != sha256:
            raise NetError(f"{url} does not match its known SHA-256")
        os.replace(tmp, dest)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise NetError(_describe(url, e)) from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return digest.hexdigest()
