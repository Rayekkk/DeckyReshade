# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""What the panel shows when something does not work: ReShade's own log per game, the plugin's log, and a report.

ReShade writes ReShade.log next to its DLL on every start ("| ERROR |" lines name failed effects, a missing compiler,
an unsupported API). Its absence after a session means ReShade never loaded, which is a wrong executable, API or
Wine setting rather than a ReShade problem.
"""

import os
import re
import time

from reshade_install import LOG

MAX_READ = 2 << 20
_VERSION = re.compile(r"ReShade version '(\d+\.\d+\.\d+)")
# the AutoHDR add-on put the swap chain in scRGB or HDR10 (DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709 is SDR)
_AUTOHDR_ON = re.compile(r"DXGI swapchain colour space DXGI_COLOR_SPACE_RGB_FULL_(G10_NONE_P709|G2084_NONE_P2020) set")


def tail(path, lines=200):
    """The last lines of a text file, '' when it cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - (256 << 10)))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def reshade_log(folder):
    """Summary of a game's ReShade.log: {found, modified (epoch s), version, errors: [last few], warnings: count,
    autohdr: "on" | "off" | "no_hdr" | ""}.

    The version is on the first line; errors and warnings come from the last MAX_READ bytes, so a long log still
    shows its newest ones. autohdr: what the AutoHDR add-on did with the game's swap chain ("" without the add-on):
    switched it to HDR, could not (some games create and drop a device the add-on loses track of: Cult of the Lamb),
    or found no HDR display (HDR off in Steam's display settings)."""
    path = os.path.join(folder, LOG)
    try:
        modified = os.path.getmtime(path)
        with open(path, "rb") as f:
            first = f.read(4096).decode("utf-8", "replace")
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - MAX_READ))
            last = f.read()
    except OSError:
        return {"found": False, "modified": 0, "version": "", "errors": [], "warnings": 0, "autohdr": ""}
    if size > MAX_READ:
        last = last.split(b"\n", 1)[-1]  # the first line read is cut in half
    version = next((m.group(1) for m in map(_VERSION.search, first.splitlines()) if m), "")
    errors, warnings, autohdr = [], 0, ""
    for line in last.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) < 3:
            continue
        level, message = parts[1], parts[2]
        if message.startswith("[AutoHDR]") and autohdr != "on":
            if _AUTOHDR_ON.search(message):
                autohdr = "on"
            elif "no HDR support" in message:
                autohdr = "no_hdr"
            elif not autohdr:
                autohdr = "off"
        if level == "ERROR" and message not in errors:
            errors.append(message)
        elif level == "WARN":
            warnings += 1
    return {"found": True, "modified": modified, "version": version, "errors": errors[-5:], "warnings": warnings,
            "autohdr": autohdr}


def plugin_log_path(decky):
    """The plugin's own log file, written by decky.logger."""
    path = getattr(decky, "DECKY_PLUGIN_LOG", "")
    if path and os.path.isfile(path):
        return path
    folder = getattr(decky, "DECKY_PLUGIN_LOG_DIR", "")
    try:
        logs = [os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".log")]
    except OSError:
        return ""
    return max(logs, key=os.path.getmtime) if logs else ""


def os_release(path="/etc/os-release"):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            values = dict(line.strip().split("=", 1) for line in f if "=" in line)
    except OSError:
        return "unknown"
    return " ".join(values.get(k, "").strip('"') for k in ("NAME", "VERSION_ID", "BUILD_ID")).strip() or "unknown"


def report(header, games, plugin_log):
    """A plain-text report to attach to a bug report.

    header: [(label, value)]; games: [(title, {key: value}, ReShade.log tail)]; plugin_log: its tail.
    """
    out = [f"DeckyReshade report, {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    out += [f"{label}: {value}" for label, value in header]
    for title, details, log in games:
        out += ["", f"== {title}"]
        out += [f"{key}: {value}" for key, value in details.items()]
        out += ["-- ReShade.log (end)", log or "(none)"]
    out += ["", "== Plugin log (end)", plugin_log or "(none)", ""]
    return "\n".join(out)
