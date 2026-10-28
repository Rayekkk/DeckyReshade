// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// What every page uses: styles, toasts, launch options, Decky Launch Options, dialogs and the page chrome.
import { toaster } from "@decky/api";
import { ButtonItem, ConfirmModal, Field, Focusable, PanelSection, PanelSectionRow, ScrollPanelGroup, showModal } from "@decky/ui";
import { FC, ReactNode, useEffect, useRef } from "react";
import { API_LABEL, APIS, disableGame, enableGame, State, VERSION_NOTE } from "./api";
import { settle } from "./result";

// Survives the QAM remounting the panel: the last state, the link that opened the current page (focused again on
// the way back), and a job error the user closed (a new error, a different text, shows again).
export const panel = { lastState: null as State | null, lastLink: "", dismissedError: "" };

export const notify = (title: string, body: string) => toaster.toast({ title, body, duration: 6000 });

export const muted = { fontSize: "12px", color: "var(--gpColor-TextMuted, rgba(255,255,255,.6))", overflowWrap: "anywhere" } as const;
export const errorBox = { padding: "8px", borderRadius: "4px", background: "rgba(248,113,113,.14)", color: "var(--gpColor-Red, #f87171)", overflowWrap: "anywhere" } as const;
export const okText = { color: "var(--gpColor-Green, #4ade80)" } as const;
export const warnText = { color: "var(--gpColor-Yellow, #facc15)" } as const;

export const versionLabel = (v: string, newest: string | undefined) =>
  v === "latest" ? "Latest, auto-updated" : `${v}${VERSION_NOTE[v] ? `, ${VERSION_NOTE[v]}` : v === newest ? ", newest known" : ""}`;

export const ago = (epoch: number) => {
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};

const unregister = (u: SteamUnregister | undefined) => (typeof u === "function" ? u() : u?.unregister());

// Current launch options straight from Steam. Rejects instead of guessing, so the user's own options are never lost.
const readLaunchOptions = (appid: number) =>
  new Promise<string>((resolve, reject) => {
    let done = false;
    let reg: SteamUnregister | undefined;
    const timer = setTimeout(() => {
      if (!done) { done = true; unregister(reg); reject(new Error("Steam did not return the launch options")); }
    }, 3000);
    reg = SteamClient.Apps.RegisterForAppDetails(appid, details => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => unregister(reg), 0);
      if (typeof details?.strLaunchOptions === "string") resolve(details.strLaunchOptions);
      else reject(new Error("Steam did not return the launch options"));
    });
  });

export const dloInstalled = () => !!(window as unknown as { hasDeckyLaunchOptions?: boolean }).hasDeckyLaunchOptions;

// Decky Launch Options' public integration: a "ReShade" tab with one dropdown, Off or an API, per game, plus AutoHDR's
// variable. Its runner merges WINEDLLOVERRIDES with the user's other options. Stable ids let a second export replace
// the first.
export const exportToDlo = (words: Record<string, string>, autohdrEnv: string[]) =>
  window.dispatchEvent(new CustomEvent("dlo-add-launch-options", {
    detail: [
      { id: "deckyreshade-off", group: "ReShade", name: "ReShade", valueId: "deckyreshade-api", valueName: "Off",
        on: "", off: "", enableGlobally: false, fallbackValue: true },
      ...APIS.map(a => ({ id: `deckyreshade-${a}`, group: "ReShade", name: "ReShade", valueId: "deckyreshade-api",
        valueName: API_LABEL[a], on: words[a], off: "", enableGlobally: false })),
      { id: "deckyreshade-autohdr", group: "ReShade", name: "ReShade HDR (AutoHDR, RenoDX)", on: autohdrEnv.join(" "),
        off: "", enableGlobally: false },
    ],
  }));

// The first time a game needs it, offer the ReShade tab to Decky Launch Options (it asks the user to confirm); again
// only when the options change. Browser storage can be missing: then it is offered each time, which is harmless.
const offerToDlo = () => {
  const state = panel.lastState;
  if (!state) return;
  const key = JSON.stringify([state.launch_words, state.autohdr_env]);
  try {
    if (localStorage.getItem("deckyreshade-dlo-offered") === key) return;
    localStorage.setItem("deckyreshade-dlo-offered", key);
  } catch {
    // no storage: offer anyway
  }
  exportToDlo(state.launch_words, state.autohdr_env);
};

// Turn ReShade on or off for one game and apply the launch options the backend worked out. Returns whether it worked.
export const applyGame = async (appid: number, name: string, nonsteam: boolean, on: boolean, exe = "", api = "",
  autohdr = false, renodx = "") => {
  let current = "";
  try {
    current = await readLaunchOptions(appid);
  } catch (e) {
    // a shortcut's options come from shortcuts.vdf in the backend; a Steam game's must never be guessed
    if (!nonsteam) {
      notify(name, `${String(e)}. Nothing was changed, so your launch options are kept; try again.`);
      return false;
    }
  }
  const res = await settle(on ? enableGame(appid, exe, api, autohdr, renodx, current, dloInstalled()) : disableGame(appid, current));
  // also on failure: switching executable or API may have turned the old setup off first
  if (res.launch_options !== undefined && res.launch_options !== current)
    SteamClient.Apps.SetAppLaunchOptions(appid, res.launch_options);
  if (!res.ok) {
    notify(name, res.error ?? "Failed");
    return false;
  }
  if (res.kept?.length) notify(name, `Left files you changed in place: ${res.kept.join(", ")}`);
  if (on && res.dlo) {
    offerToDlo();
    notify(name, `ReShade files are in place. Launch options are up to Decky Launch Options: in its ReShade tab, choose ${API_LABEL[api] ?? api}${autohdr || renodx ? " and turn on ReShade HDR" : ""} for this game.`);
  }
  if (res.dlo_leftover)
    notify(name, "Decky Launch Options still adds ReShade's WINEDLLOVERRIDES to this game: set ReShade to Off for it there (harmless until then).");
  return true;
};

// A log in a scrollable dialog (the D-pad scrolls it once focused).
export const showText = (title: string, text: string) => {
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

export const confirm = (title: string, text: string, ok: string, action: () => void) =>
  showModal(<ConfirmModal strTitle={title} strDescription={text} strOKButtonText={ok} bDestructiveWarning onOK={action} />);

// ---- page chrome: a short list of categories, each opening its own page (as in Legion Go 2 Companion) ------------

const Chevron: FC = () => (
  <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
    style={{ display: "block", width: "1em", height: "1em", flexShrink: 0 }}>
    <path d="m9 18 6-6-6-6" />
  </svg>
);

const ICONS: Record<string, ReactNode> = {
  game: <><rect x="2.5" y="7" width="19" height="11" rx="5.5" /><path d="M7.5 10.5v4M5.5 12.5h4" /><path d="M15.5 11.5h.01M17.5 13.5h.01" /></>,
  games: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>,
  shaders: <><path d="M12 3a9 9 0 1 0 0 18c.9 0 1.5-.7 1.5-1.5 0-1.1-1-1.4-1-2.4 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5C21 6.3 17 3 12 3z" /><path d="M7.5 11h.01M10.5 7.5h.01M15 7.5h.01" /></>,
  version: <><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" /><circle cx="15" cy="6" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="17" cy="18" r="2" /></>,
  troubleshooting: <><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3.5 17.5l3 3 5.8-5.8a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" /></>,
  about: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5h.01" /></>,
};

const Icon: FC<{ name: string }> = ({ name }) => (
  <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" style={{ display: "block", width: "1.2em", height: "1.2em", flexShrink: 0 }}>
    {ICONS[name]}
  </svg>
);

// A row that opens a page: icon, name, what it is for and, below, how things stand.
export const SectionLink: FC<{ id: string; icon: string; title: string; description: ReactNode; note?: ReactNode; onClick: () => void }> =
  ({ id, icon, title, description, note, onClick }) => {
    const ref = useRef<HTMLDivElement>(null);
    // Coming back from a page puts the focus on the row that opened it, once.
    useEffect(() => { if (id === panel.lastLink) ref.current?.focus(); }, []);
    return (
      <PanelSectionRow>
        <Field ref={ref} label={title} icon={<Icon name={icon} />} bottomSeparator="standard" verticalAlignment="center"
          description={note ? <>{description}<div style={{ fontSize: "11px", opacity: 0.75, marginTop: "2px" }}>{note}</div></> : description}
          childrenLayout="inline" childrenContainerWidth="min" focusable highlightOnFocus onActivate={onClick}>
          <Chevron />
        </Field>
      </PanelSectionRow>
    );
  };

export const PageHeader: FC<{ title: string; back: string; onBack: () => void }> = ({ title, back, onBack }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.querySelector<HTMLButtonElement>("button")?.focus(); }, []);
  return (
    <PanelSection title={title}>
      <PanelSectionRow>
        <div ref={ref}><ButtonItem layout="below" onClick={onBack}>‹ {back}</ButtonItem></div>
      </PanelSectionRow>
    </PanelSection>
  );
};

export const PageShell: FC<{ children: ReactNode }> = ({ children }) => (
  <div style={{ width: "100%", maxWidth: "100%", minWidth: 0, overflowX: "hidden", boxSizing: "border-box" }}>{children}</div>
);
