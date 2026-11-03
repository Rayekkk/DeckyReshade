// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// What every page uses: text styles, turning a game on or off, copying launch options, the log dialog and page icons.
import { ConfirmModal, Focusable, ScrollPanelGroup, showModal } from "@decky/ui";
import { ReactNode } from "react";
import { disableGame, enableGame, State, VERSION_NOTE } from "./api";
import { Result, settle } from "./result";
import { colors, notify } from "./ui";

export const NAME = "DeckyReshade";

// A game's choices made on its page but not applied (ReShade off), and one choice from a dropdown.
export type Choice = { exe?: string; api?: string | null; renodx?: string };

// Survives the QAM remounting the panel: the last state and a job error the user closed (a new error, a different
// text, shows again). Steam shows dropdown menus and dialogs outside the QAM, and Decky 3.3.1 unmounts the panel
// while they are open: with `resume` set (keepPage) the panel comes back on `nav`, the page it showed, with `drafts`,
// and `pick` takes a dropdown choice made meanwhile to the game page mounted after it.
export const panel = {
  lastState: null as State | null, dismissedError: "",
  nav: null as { page: string | null; gameId: number | null; gameFromList: boolean } | null, resume: false,
  drafts: {} as Record<number, Choice>,
  pick: null as { appid: number; choice: Choice } | null, onPick: null as (() => void) | null,
  later: null as Later | null, onRun: null as ((call: Later) => void) | null,
};
type Later = () => Promise<Result<State>>;

/** Before a dropdown menu or a dialog: the panel comes back on this page. For DropdownItem's onMenuWillOpen. */
export const keepPage = (show?: () => void) => { panel.resume = true; show?.(); };

/** The page to come back to on the panel's first render, or null when the QAM was opened afresh (drafts go). */
export const takeResume = () => {
  const nav = panel.resume ? panel.nav : null;
  panel.resume = false;
  if (!nav) {
    panel.drafts = {};
    panel.pick = null;
    panel.later = null;
  }
  return nav;
};

/** A main-panel call from a dropdown (the ReShade version), run by the panel mounted now or the one mounted next. */
export const runLater = (call: Later) => {
  if (panel.onRun) panel.onRun(call);
  else panel.later = call;
};

/** A game page's dropdown choice, for the page that is mounted now or the one mounted next. */
export const pick = (appid: number, choice: Choice) => {
  panel.pick = { appid, choice };
  panel.onPick?.();
};

// Text in a row's description; the colors are DeckyKit's one palette (ui.tsx).
export const muted = { fontSize: "12px", color: colors.muted, overflowWrap: "anywhere" } as const;
export const errorStyle = { color: colors.error, overflowWrap: "anywhere" } as const;
export const okText = { color: colors.ok } as const;
export const warnText = { color: colors.warning } as const;

export const versionLabel = (v: string, newest: string | undefined) =>
  v === "latest" ? "Latest, auto-updated" : `${v}${VERSION_NOTE[v] ? `, ${VERSION_NOTE[v]}` : v === newest ? ", newest known" : ""}`;

export const ago = (epoch: number) => {
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};

// The Steam client does not always grant the async clipboard API to plugins; fall back to a selected textarea.
const copyText = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
};

// With "Use launch options" the user pastes ReShade's line into the game's launch options; this copies it.
export const copyLaunchOptions = async (name: string, api: string) => {
  const line = panel.lastState?.launch_options[api];
  if (!line) return;
  notify(name, await copyText(line)
    ? "Launch options copied. Paste them in the game's Properties → General → Launch options."
    : `Could not copy. Add this to the game's launch options: ${line}`);
};

// Turn ReShade on or off for one game. Returns why it failed (also shown as a toast titled with the game), "" when
// it worked.
export const applyGame = async (appid: number, name: string, on: boolean, exe = "", api = "", autohdr = false,
  renodx = "") => {
  const res = await settle(on ? enableGame(appid, exe, api, autohdr, renodx) : disableGame(appid));
  if (!res.ok) {
    notify(name, res.error ?? "Failed");
    return res.error ?? "Failed";
  }
  if (res.kept?.length) notify(name, `Left files you changed in place: ${res.kept.join(", ")}.`);
  return "";
};

// A log in a scrollable dialog (the D-pad scrolls it once focused).
export const showText = (title: string, text: string) => {
  keepPage();
  showModal(
    <ConfirmModal strTitle={title} bAlertDialog strOKButtonText="Close"
      strDescription={
        <ScrollPanelGroup>
          <Focusable style={{ maxHeight: "55vh", overflowY: "auto" }} onActivate={() => {}}>
            <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "11px", margin: 0 }}>
              {text || "(empty)"}
            </pre>
          </Focusable>
        </ScrollPanelGroup>
      } />,
  );
};

// ---- page chrome: a short list of pages, each opened from a row of the main page (UI.md §1 level B) -------------

// Icon paths for the page rows (ui.tsx Icon draws them).
export const ICONS: Record<string, ReactNode> = {
  game: <><rect x="2.5" y="7" width="19" height="11" rx="5.5" /><path d="M7.5 10.5v4M5.5 12.5h4" /><path d="M15.5 11.5h.01M17.5 13.5h.01" /></>,
  games: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>,
  shaders: <><path d="M12 3a9 9 0 1 0 0 18c.9 0 1.5-.7 1.5-1.5 0-1.1-1-1.4-1-2.4 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5C21 6.3 17 3 12 3z" /><path d="M7.5 11h.01M10.5 7.5h.01M15 7.5h.01" /></>,
  version: <><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" /><circle cx="15" cy="6" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="17" cy="18" r="2" /></>,
  troubleshooting: <><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3.5 17.5l3 3 5.8-5.8a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" /></>,
  about: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5h.01" /></>,
};
