// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

import { callable, definePlugin, toaster } from "@decky/api";
import {
  ButtonItem, ConfirmModal, DropdownItem, Field, Focusable, PanelSection, PanelSectionRow, Router, ScrollPanelGroup,
  showModal, Spinner, staticClasses, ToggleField,
} from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useRef, useState } from "react";

declare const SteamClient: any;

const APIS = ["dxgi", "d3d9", "d3d10", "d3d11", "d3d12", "opengl32", "dinput8"] as const;
const DXGI_APIS: readonly string[] = ["dxgi", "d3d10", "d3d11", "d3d12"];
const API_LABEL: Record<string, string> = {
  dxgi: "DirectX 10/11/12 (dxgi)",
  d3d9: "Direct3D 8/9 (d3d9)",
  d3d10: "Direct3D 10 (d3d10)",
  d3d11: "Direct3D 11 (d3d11)",
  d3d12: "Direct3D 12 (d3d12)",
  opengl32: "OpenGL (opengl32)",
  dinput8: "Any API, loaded via dinput8 (fallback)",
  vulkan: "Vulkan (not supported yet)",
};
// The RenoDX wiki's legend, with its emoji.
const RENODX_STATUS: Record<string, string> = {
  working: "✅ Working, playable",
  wip: "🚧 In progress, lacking testing, or may have deal-breaking issues",
};
const renodxBadge = (status?: string | null) => (status === "working" ? "✅" : status === "wip" ? "🚧" : status ? "⚠️" : "");
// What a pinned version is for; the newest is what "latest" falls back to.
const VERSION_NOTE: Record<string, string> = { "6.5.1": "for DXVK HDR games whose ReShade menu breaks" };

interface Package { id: string; name: string; description: string; default: boolean; required: boolean }
interface Enabled { appid: number; name: string; api: string; exe: string; bits: number; autohdr: boolean; renodx: string }
interface RenodxMod { name: string; maintainer: string; status: string; note: string; files: string[]; page: string }
interface LogSummary { found: boolean; modified: number; version: string; errors: string[]; warnings: number }

interface State {
  version: string;
  reshade: {
    installed: string | null; addon: boolean; latest: string | null; update_available: boolean; check_error: string;
    versions: string[]; autohdr_ready: boolean;
  };
  job: { task: string; error: string };
  settings: { addon: boolean; version: string; auto_launch_options: boolean };
  launch_words: Record<string, string>;
  autohdr_env: string[];
  renodx: { count: number; fetched_at: number; error: string };
  scanned: boolean;
  games: { appid: number; name: string; nonsteam: boolean; renodx: string | null }[];
  enabled: Enabled[];
  shaders: { installed: string[]; packages: Package[] | null };
}

interface GameInfo {
  ok: boolean;
  error?: string;
  candidates?: { exe: string; bits: number; running?: boolean }[];
  exe?: string;
  bits?: number;
  detected_api?: string;
  detected_how?: "imports" | "strings" | "default";
  anticheat?: boolean;
  nonsteam?: boolean;
  enabled?: boolean;
  api?: string | null;
  autohdr?: boolean;
  renodx?: { installed: string; auto: string; mod: RenodxMod | null };
  log?: LogSummary;
}

type ToggleResult = { ok: boolean; error?: string; launch_options?: string; kept?: string[]; dlo?: boolean; dlo_leftover?: string };

const getState = callable<[], State>("get_state");
const scanGames = callable<[], State>("scan_games");
const setup = callable<[boolean, string, boolean], State>("setup");
const checkReshade = callable<[], State>("check_reshade");
const updateReshade = callable<[], State>("update_reshade");
const setSetting = callable<[string, boolean], State>("set_setting");
const setVersion = callable<[string], State>("set_version");
const loadPackages = callable<[], State>("load_packages");
const setPackage = callable<[string, boolean], State>("set_package");
const updateShaders = callable<[], State>("update_shaders");
const removeData = callable<[], State>("remove_data");
const getGame = callable<[number, string, string], GameInfo>("get_game");
const enableGame = callable<[number, string, string, boolean, string, string, boolean], ToggleResult>("enable_game");
const refreshRenodx = callable<[], State>("refresh_renodx");
const getRenodxMods = callable<[], { mods: { name: string; status: string }[] }>("get_renodx_mods");
const disableGame = callable<[number, string], ToggleResult>("disable_game");
const sessionStarted = callable<[number], { managed: boolean }>("session_started");
const sessionEnded = callable<[number], { managed: boolean; loaded?: boolean; warning?: string }>("session_ended");
const getLogs = callable<[number], { plugin: string; reshade: string }>("get_logs");
const saveReport = callable<[], { path?: string; error?: string }>("save_report");

interface UpdateInfo { current_version?: string; latest_version?: string; update_available?: boolean; asset_name?: string; error?: string }
const checkForUpdates = callable<[], UpdateInfo>("check_for_updates");
const performUpdate = callable<[string], { path?: string; version?: string; error?: string }>("perform_update");

const notify = (title: string, body: string) => toaster.toast({ title, body, duration: 6000 });

const muted = { fontSize: "12px", color: "var(--gpColor-TextMuted, rgba(255,255,255,.6))", overflowWrap: "anywhere" } as const;
const errorBox = { padding: "8px", borderRadius: "4px", background: "rgba(248,113,113,.14)", color: "var(--gpColor-Red, #f87171)", overflowWrap: "anywhere" } as const;
const okText = { color: "var(--gpColor-Green, #4ade80)" } as const;
const warnText = { color: "var(--gpColor-Yellow, #facc15)" } as const;

const versionLabel = (v: string, newest: string | undefined) =>
  v === "latest" ? "Latest, auto-updated" : `${v}${VERSION_NOTE[v] ? `, ${VERSION_NOTE[v]}` : v === newest ? ", newest known" : ""}`;

const ago = (epoch: number) => {
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};

// Current launch options straight from Steam. Rejects instead of guessing, so the user's own options are never lost.
const readLaunchOptions = (appid: number) =>
  new Promise<string>((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (!done) { done = true; reg?.unregister?.(); reject(new Error("Steam did not return the launch options")); }
    }, 3000);
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, (details: any) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      setTimeout(() => reg?.unregister?.(), 0);
      if (typeof details?.strLaunchOptions === "string") resolve(details.strLaunchOptions);
      else reject(new Error("Steam did not return the launch options"));
    });
  });

// Turn ReShade on or off for one game and apply the launch options the backend worked out. Returns whether it worked.
const applyGame = async (appid: number, name: string, nonsteam: boolean, on: boolean, exe = "", api = "",
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
  try {
    const res = await (on ? enableGame(appid, exe, api, autohdr, renodx, current, dloInstalled()) : disableGame(appid, current));
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
  } catch (e) {
    notify(name, String(e));
    return false;
  }
};

// Decky Launch Options' public integration: a "ReShade" tab with one dropdown, Off or an API, per game, plus AutoHDR's
// variable. Its runner merges WINEDLLOVERRIDES with the user's other options. Stable ids let a second export replace
// the first.
const exportToDlo = (words: Record<string, string>, autohdrEnv: string[]) =>
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

const dloInstalled = () => !!(window as any).hasDeckyLaunchOptions;

// The first time a game needs it, offer the ReShade tab to Decky Launch Options (it asks the user to confirm); again
// only when the options change. Browser storage can be missing: then it is offered each time, which is harmless.
let lastState: State | null = null;
const offerToDlo = () => {
  if (!lastState) return;
  const key = JSON.stringify([lastState.launch_words, lastState.autohdr_env]);
  try {
    if (localStorage.getItem("deckyreshade-dlo-offered") === key) return;
    localStorage.setItem("deckyreshade-dlo-offered", key);
  } catch {
    // no storage: offer anyway
  }
  exportToDlo(lastState.launch_words, lastState.autohdr_env);
};

// A log in a scrollable dialog (the D-pad scrolls it once focused).
const showText = (title: string, text: string) => {
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

const confirm = (title: string, text: string, ok: string, action: () => void) =>
  showModal(<ConfirmModal strTitle={title} strDescription={text} strOKButtonText={ok} bDestructiveWarning onOK={action} />);

const ANTICHEAT_WARNING = "Anti-cheat detected: ReShade in online games can get you kicked or banned. " +
  "Turning it on is at your own risk.";

// ---- first-run wizard ----------------------------------------------------------------------------------------------

// Survives the QAM remounting the panel.
let wizard = { step: 0, addon: true, version: "latest", autohdr: true };

// Steps: 0 welcome, 1 build, 2 version, 3 AutoHDR, last: summary; 9 downloading, 10 how to use, 11 finished.
const inWizard = (s: State) => !s.reshade.installed || wizard.step === 9 || wizard.step === 10;

const Wizard: FC<{ state: State; busy: boolean; run: (call: () => Promise<State>) => Promise<void>; onDone: () => void }> =
  ({ state, busy, run, onDone }) => {
  const [w, setW] = useState(wizard);
  const set = (next: Partial<typeof wizard>) => { wizard = { ...wizard, ...next }; setW(wizard); };
  const { job, reshade } = state;
  const steps = w.addon ? 4 : 3;

  // The download finished: show how to use it until the user is done reading. A failure before ReShade was in place
  // goes back to the summary to try again; a later one (a shader package) is shown by the main panel.
  useEffect(() => {
    if (w.step !== 9 || busy || job.task) return;
    if (job.error && reshade.installed) {
      set({ step: 11 });
      onDone();
    } else if (reshade.installed) set({ step: 10 });
    else set({ step: steps });  // failed or never started (the call itself failed): back to the summary
  }, [w.step, busy, job.task, job.error, reshade.installed]);

  const title = (n: number, text: string) => `Setup ${n}/${steps} · ${text}`;
  const back = (to: number) => (
    <PanelSectionRow><ButtonItem layout="below" onClick={() => set({ step: to })}>Back</ButtonItem></PanelSectionRow>
  );

  if (w.step === 0)
    return (
      <PanelSection title="Welcome to DeckyReshade">
        <PanelSectionRow>
          <Field label="ReShade for your games, from Gaming Mode" description={
            "Setup takes a minute: pick a ReShade build and version, then everything is downloaded (about 15 MB). " +
            "No game is changed until you turn ReShade on for it."} />
        </PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => set({ step: 1 })}>Start setup</ButtonItem></PanelSectionRow>
      </PanelSection>
    );

  if (w.step === 1)
    return (
      <PanelSection title={title(1, "ReShade build")}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => set({ addon: true, step: 2 })}
            description="Recommended. Needed for AutoHDR and depth add-ons (3D, SBS). ReShade itself turns this build off in online multiplayer games.">
            {w.addon ? "✓ " : ""}With add-ons
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => set({ addon: false, autohdr: false, step: 2 })}
            description="For online games. Effects work, add-ons such as AutoHDR do not.">
            {!w.addon ? "✓ " : ""}Standard
          </ButtonItem>
        </PanelSectionRow>
        {back(0)}
      </PanelSection>
    );

  if (w.step === 2)
    return (
      <PanelSection title={title(2, "ReShade version")}>
        <PanelSectionRow>
          <DropdownItem layout="below" childrenContainerWidth="max" label="Version" selectedOption={w.version}
            description="Latest is checked once a day and every game gets new versions by itself. Pick a fixed version only if a game needs it; you can change it later."
            rgOptions={["latest", ...reshade.versions].map(v => ({ data: v, label: versionLabel(v, reshade.versions[0]) }))}
            onChange={o => set({ version: o.data })} />
        </PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => set({ step: w.addon ? 3 : steps })}>Next</ButtonItem></PanelSectionRow>
        {back(1)}
      </PanelSection>
    );

  if (w.step === 3 && w.addon)
    return (
      <PanelSection title={title(3, "AutoHDR")}>
        <PanelSectionRow>
          <ToggleField label="Download AutoHDR" checked={w.autohdr} onChange={on => set({ autohdr: on })}
            description="Turns SDR games into HDR on HDR screens (Steam Deck OLED and other OLED handhelds). Needs HDR on in Steam's display settings and a DirectX 10/11/12 game. You turn it on per game." />
        </PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => set({ step: steps })}>Next</ButtonItem></PanelSectionRow>
        {back(2)}
      </PanelSection>
    );

  if (w.step === 10)
    return (
      <PanelSection title="ReShade is ready">
        <PanelSectionRow>
          <Field label="How to use it" description={<ol style={{ margin: 0, paddingLeft: "18px" }}>
            <li>Start a game and open this menu: the game is picked for you.</li>
            <li>Turn on <b>ReShade in this game</b>{w.autohdr ? " (and AutoHDR, if you want it)" : ""}.</li>
            <li>Restart the game and press <b>Home</b> to open ReShade. No keyboard? Map Home to a back button in the game's controller layout.</li>
            <li>If ReShade does not appear, the game's section shows why and lets you pick another executable or API.</li>
          </ol>} />
        </PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => { set({ step: 11 }); onDone(); }}>Done</ButtonItem></PanelSectionRow>
      </PanelSection>
    );

  // Summary and download
  const installing = w.step === 9 || busy || !!job.task;
  return (
    <PanelSection title={title(steps, "Download")}>
      <PanelSectionRow>
        <Field label="Your choices" description={<>
          <div>Build: {w.addon ? "with add-ons" : "standard"}</div>
          <div>Version: {versionLabel(w.version, reshade.versions[0])}</div>
          {w.addon && <div>AutoHDR: {w.autohdr ? "yes" : "no"}</div>}
          <div>Shaders: standard effects and SweetFX (more can be added later)</div>
        </>} />
      </PanelSectionRow>
      {job.error && !installing && <PanelSectionRow><div style={errorBox}>{job.error}</div></PanelSectionRow>}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={installing}
          onClick={() => { set({ step: 9 }); run(() => setup(w.addon, w.version, w.autohdr && w.addon)); }}>
          {installing ? <span>{job.task || "Starting…"} <Spinner style={{ width: "16px", verticalAlign: "middle" }} /></span>
            : job.error ? "Try again" : "Download and set up"}
        </ButtonItem>
      </PanelSectionRow>
      {!installing && back(w.addon ? 3 : 2)}
    </PanelSection>
  );
};

// ---- main panel: a short list of categories, each opening its own page (as in Legion Go 2 Companion) ---------------

type Page = "games" | "game" | "shaders" | "reshade" | "troubleshooting" | "about";

// The QAM remounts the panel on every open; keep where the user was so it opens there again.
let lastPage: Page | null = null;
let lastGame: number | null = null; // the game page's game
let gameFromList = false; // the game page was opened from Games (else from the main page)
let lastLink = ""; // the link that opened the current page, focused again on the way back
// A job error the user closed; a new error (a different text) shows again.
let dismissedError = "";

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
const SectionLink: FC<{ id: string; icon: string; title: string; description: ReactNode; note?: ReactNode; onClick: () => void }> =
  ({ id, icon, title, description, note, onClick }) => {
    const ref = useRef<HTMLDivElement>(null);
    // Coming back from a page puts the focus on the row that opened it, once.
    useEffect(() => { if (id === lastLink) ref.current?.focus(); }, []);
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

const PageHeader: FC<{ title: string; back: string; onBack: () => void }> = ({ title, back, onBack }) => {
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

const PageShell: FC<{ children: ReactNode }> = ({ children }) => (
  <div style={{ width: "100%", maxWidth: "100%", minWidth: 0, overflowX: "hidden", boxSizing: "border-box" }}>{children}</div>
);

const gameSummary = (g?: Enabled) => !g ? "ReShade off"
  : `ReShade on · ${API_LABEL[g.api] ?? g.api}${g.autohdr ? " · AutoHDR" : ""}${g.renodx ? " · RenoDX" : ""}`;
const renodxNote = (status: string | null) => status ? `RenoDX mod: ${RENODX_STATUS[status] ?? "⚠️ see notes"}` : undefined;

const Content: FC = () => {
  const [state, setStateRaw] = useState<State | null>(lastState);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPageRaw] = useState<Page | null>(lastPage);
  const [gameId, setGameId] = useState<number | null>(lastGame);
  const [, rerender] = useState(0);

  const setState = useCallback((s: State) => { lastState = s; setStateRaw(s); }, []);
  const refresh = useCallback(() => getState().then(s => { setState(s); setError(""); }, e => setError(String(e))),
    [setState]);

  useEffect(() => {
    // The library is scanned on every open (cheap: manifests and shortcuts), so new games and shortcuts show up.
    getState().then(s => {
      setState(s);
      scanGames().then(setState, () => {});
    }, e => setError(String(e)));
  }, [setState]);

  // Poll while a download runs (and while any call is out: a job only shows up in the state it returns at its end).
  useEffect(() => {
    if (!state?.job.task && !busy) return;
    const t = setInterval(refresh, 700);
    return () => clearInterval(t);
  }, [state?.job.task, busy, refresh]);

  const run = async (call: () => Promise<State>) => {
    setBusy(true);
    try {
      setState(await call());
    } catch (e) {
      notify("DeckyReshade", String(e));
    }
    setBusy(false);
  };

  const open = (next: Page | null, link?: string) => {
    if (link) lastLink = link;
    lastPage = next;
    setPageRaw(next);
  };
  const openGame = (appid: number, fromList: boolean) => {
    lastGame = appid;
    gameFromList = fromList;
    setGameId(appid);
    open("game", fromList ? `game-${appid}` : "this-game");
  };

  const nonsteam = (appid: number) => !!state?.games.find(g => g.appid === appid)?.nonsteam;

  const turnOffAll = async () => {
    setBusy(true);
    let ok = 0;
    const games = state?.enabled ?? [];
    for (const g of games) if (await applyGame(g.appid, g.name, nonsteam(g.appid), false)) ok++;
    notify("DeckyReshade", `${ok} of ${games.length} game${games.length === 1 ? "" : "s"} restored to how they were.`);
    setBusy(false);
    refresh();
  };

  const report = async () => {
    const res = await saveReport().catch(e => ({ error: String(e) }) as { path?: string; error?: string });
    if (res.path) showText("Report saved", `${res.path}\n\nAttach this file when you report a problem.`);
    else notify("DeckyReshade", res.error ?? "The report could not be saved.");
  };

  if (!state) return <PanelSection>{error ? <Field label="Backend unavailable">{error}</Field> : <Spinner />}</PanelSection>;

  if (inWizard(state)) return <Wizard state={state} busy={busy} run={run} onDone={() => rerender(n => n + 1)} />;

  const { reshade, job, settings } = state;
  const working = busy || !!job.task;
  const enabled = (appid: number) => state.enabled.find(g => g.appid === appid);
  const running = Router.MainRunningApp;
  const runningGame = running ? state.games.find(g => g.appid === running.appid) : undefined;

  // A download in progress or a failed one, at the top of every page.
  const status = (job.task || (job.error && job.error !== dismissedError)) ? (
    <PanelSection>
      {job.task && <PanelSectionRow><Field label={job.task}><Spinner style={{ width: "20px" }} /></Field></PanelSectionRow>}
      {job.error && job.error !== dismissedError && (
        <>
          <PanelSectionRow><div style={errorBox}>{job.error}</div></PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => { dismissedError = job.error; rerender(n => n + 1); }}>Dismiss</ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  ) : null;

  const versionNote = <>
    ReShade {reshade.installed} · {reshade.addon ? "add-on build" : "standard build"} · {settings.version === "latest" ? "updates automatically" : "fixed version"}
    {reshade.update_available && <div style={warnText}>ReShade {reshade.latest} is available</div>}
  </>;

  if (!page) {
    const renodxGames = state.games.filter(g => g.renodx).length;
    return (
      <PageShell>
        {status}
        <PanelSection title="ReShade">
          {runningGame && <SectionLink id="this-game" icon="game" title={`This game: ${runningGame.name}`}
            description={gameSummary(enabled(runningGame.appid))} note={renodxNote(runningGame.renodx)}
            onClick={() => openGame(runningGame.appid, false)} />}
          <SectionLink id="games" icon="games" title="Games"
            description="Your library: turn ReShade, AutoHDR or a RenoDX mod on per game"
            note={`${state.enabled.length} with ReShade · ${renodxGames} with a RenoDX mod · ${state.games.length} games`}
            onClick={() => open("games", "games")} />
          <SectionLink id="shaders" icon="shaders" title="Shaders" description="Effect packages shared by every game"
            note={`${state.shaders.installed.length} package${state.shaders.installed.length === 1 ? "" : "s"} installed`}
            onClick={() => open("shaders", "shaders")} />
          <SectionLink id="reshade" icon="version" title="ReShade version" description="Version, add-on build, updates, launch options"
            note={versionNote} onClick={() => open("reshade", "reshade")} />
        </PanelSection>
        <PanelSection title="Plugin">
          <SectionLink id="troubleshooting" icon="troubleshooting" title="Troubleshooting"
            description="Logs and a report for when ReShade does not work" onClick={() => open("troubleshooting", "troubleshooting")} />
          <SectionLink id="about" icon="about" title="About" description={`DeckyReshade · v${state.version} · plugin updates`}
            onClick={() => open("about", "about")} />
        </PanelSection>
      </PageShell>
    );
  }

  if (page === "game" && gameId !== null) {
    const game = state.games.find(g => g.appid === gameId);
    return (
      <PageShell>
        <PageHeader title={game?.name ?? "Game"} back={gameFromList ? "Games" : "ReShade"}
          onBack={() => open(gameFromList ? "games" : null)} />
        {status}
        {game ? <GamePage key={game.appid} game={game} state={state} working={working} setBusy={setBusy} refresh={refresh} />
          : <PanelSection><PanelSectionRow><div style={errorBox}>This game is not in the library any more.</div></PanelSectionRow></PanelSection>}
      </PageShell>
    );
  }

  if (page === "games") {
    const others = state.games.filter(g => !enabled(g.appid))
      .sort((a, b) => (b.appid === runningGame?.appid ? 1 : 0) - (a.appid === runningGame?.appid ? 1 : 0));
    return (
      <PageShell>
        <PageHeader title="Games" back="ReShade" onBack={() => open(null)} />
        {status}
        {state.enabled.length > 0 && (
          <PanelSection title="With ReShade">
            {state.enabled.map(g => (
              <SectionLink key={g.appid} id={`game-${g.appid}`} icon="game" title={g.name} description={gameSummary(g)}
                note={g.exe} onClick={() => openGame(g.appid, true)} />
            ))}
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={working} onClick={turnOffAll}
                description="Removes ReShade's DLLs and launch options from every game. Your ReShade settings, presets and logs stay in the game folders. Do this before uninstalling.">
                Turn off ReShade in all games
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        )}
        <PanelSection title={state.scanned ? "All games" : "Scanning your library…"}>
          {others.map(g => (
            <SectionLink key={g.appid} id={`game-${g.appid}`} icon="game"
              title={`${g.appid === runningGame?.appid ? "▶ " : ""}${g.name}`}
              description={g.nonsteam ? "Non-Steam game" : "ReShade off"} note={renodxNote(g.renodx)}
              onClick={() => openGame(g.appid, true)} />
          ))}
          {state.scanned && !others.length && <PanelSectionRow><div style={muted}>No other games found.</div></PanelSectionRow>}
        </PanelSection>
      </PageShell>
    );
  }

  if (page === "shaders") return (
    <PageShell>
      <PageHeader title="Shaders" back="ReShade" onBack={() => open(null)} />
      {status}
      <ShadersPage state={state} working={working} run={run} />
    </PageShell>
  );

  if (page === "reshade") return (
    <PageShell>
      <PageHeader title="ReShade version" back="ReShade" onBack={() => open(null)} />
      {status}
      <PanelSection title="Version">
        <PanelSectionRow>
          <Field label={`ReShade ${reshade.installed}`} description={<>
            <div>{reshade.addon ? "Add-on build" : "Standard build"} · {settings.version === "latest" ? "updates automatically" : "fixed version"}</div>
            {reshade.update_available ? <div style={warnText}>ReShade {reshade.latest} is available.</div>
              : reshade.check_error ? <div style={warnText}>{reshade.check_error}</div>
              : settings.version === "latest" && reshade.latest ? <div style={okText}>Up to date</div> : null}
          </>} />
        </PanelSectionRow>
        {reshade.update_available ? (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={working} onClick={() => run(updateReshade)}
              description="Every game set up here gets the new version at its next start.">
              Update to ReShade {reshade.latest}
            </ButtonItem>
          </PanelSectionRow>
        ) : settings.version === "latest" && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={working} onClick={() => run(checkReshade)}>Check for a new ReShade now</ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <DropdownItem layout="below" childrenContainerWidth="max" label="Version" disabled={working} selectedOption={settings.version}
            description="Changing it moves every game to that version."
            rgOptions={["latest", ...reshade.versions].map(v => ({ data: v, label: versionLabel(v, reshade.versions[0]) }))}
            onChange={o => run(() => setVersion(o.data))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Add-on build" checked={settings.addon} disabled={working}
            description="Needed for AutoHDR, RenoDX and depth add-ons. ReShade turns this build off in online games; use the standard build there."
            onChange={on => run(() => setSetting("addon", on))} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Launch options">
        <PanelSectionRow>
          <ToggleField label="Set launch options automatically" checked={settings.auto_launch_options} disabled={working}
            description={`Turning ReShade on adds ${state.launch_words.dxgi} (with the chosen API) to the game's launch options, next to anything already there. Off: add it yourself. With Decky Launch Options installed, it decides instead (ReShade tab).`}
            onChange={on => run(() => setSetting("auto_launch_options", on))} />
        </PanelSectionRow>
        {dloInstalled() && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => exportToDlo(state.launch_words, state.autohdr_env)}
              description="Adds a ReShade tab to Decky Launch Options with one choice per game (Off or a graphics API) and the HDR variable for AutoHDR and RenoDX.">
              Add ReShade to Decky Launch Options
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title="RenoDX mod list">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={working} onClick={() => run(refreshRenodx)}
            description={<>
              <div>{state.renodx.count ? `${state.renodx.count} RenoDX mods known${state.renodx.fetched_at ? `, list from ${ago(state.renodx.fetched_at)}` : ""}. Refreshed once a day.` : "The RenoDX mod list has not been loaded yet."}</div>
              {state.renodx.error && <div style={warnText}>{state.renodx.error}</div>}
            </>}>
            Refresh RenoDX list
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </PageShell>
  );

  if (page === "troubleshooting") return (
    <PageShell>
      <PageHeader title="Troubleshooting" back="ReShade" onBack={() => open(null)} />
      {status}
      <PanelSection title="Logs">
        <PanelSectionRow>
          <Field label="ReShade's own log" description="Each game's page has Show ReShade log: what ReShade did in that game and which effects failed." />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => getLogs(0).then(l => showText("DeckyReshade log", l.plugin), e => notify("DeckyReshade", String(e)))}
            description="Everything the plugin did: downloads, games turned on or off, launch options before and after, errors.">
            Show plugin log
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={report}
            description="Saves the plugin log, settings and every game's ReShade log to one file in Downloads, to attach to a bug report.">
            Save report to Downloads
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Start over">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={working}
            onClick={() => state.enabled.length
              ? notify("DeckyReshade", "Turn ReShade off in all games first (Games); they still use these files.")
              : confirm("Remove downloaded files?", "ReShade, the shader compiler, AutoHDR, RenoDX mods and all shader packages are deleted from this device. Setup starts again next time.",
                  "Remove", () => { wizard = { ...wizard, step: 0 }; open(null); run(removeData); })}
            description="Deletes ReShade, add-ons and shaders from this device. Games must be turned off first.">
            Remove downloaded files
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </PageShell>
  );

  return (
    <PageShell>
      <PageHeader title="About" back="ReShade" onBack={() => open(null)} />
      <PanelSection title="DeckyReshade">
        <PanelSectionRow>
          <Field label={`Version ${state.version}`} description="ReShade for Steam and non-Steam games under Proton, set up from Gaming Mode." />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Author" description="Rayek · BSD-3-Clause open-source plugin." />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Downloaded on your device" description="ReShade by crosire (reshade.me); AutoHDR add-on by EndlesslyFlowering; AdvancedAutoHDR by Pumbo; RenoDX mods by their authors; shaders by theirs." />
        </PanelSectionRow>
      </PanelSection>
      <Updates version={state.version} />
    </PageShell>
  );
};

const ShadersPage: FC<{ state: State; working: boolean; run: (call: () => Promise<State>) => Promise<void> }> =
  ({ state, working, run }) => {
    useEffect(() => { if (!state.shaders.packages) run(loadPackages); }, []);
    const installed = state.shaders.installed;
    return (
      <>
        <PanelSection title="Installed">
          <PanelSectionRow>
            <Field label={`${installed.length} package${installed.length === 1 ? "" : "s"} installed`}
              description="Shared by every game; changes reach them at their next start. In game, ReShade lists their effects." />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={working || !installed.length} onClick={() => run(updateShaders)}
              description="Downloads the newest version of every installed package.">
              Update shaders
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
        <PanelSection title="Packages">
          {!state.shaders.packages && <PanelSectionRow><Spinner /></PanelSectionRow>}
          {state.shaders.packages?.map(p => (
            <PanelSectionRow key={p.id}>
              <ToggleField label={p.name} description={p.description} disabled={working || p.required}
                checked={installed.includes(p.id)} onChange={on => run(() => setPackage(p.id, on))} />
            </PanelSectionRow>
          ))}
        </PanelSection>
      </>
    );
  };

const LastRun: FC<{ log?: LogSummary; enabled: boolean }> = ({ log, enabled }) => {
  if (!log?.found)
    return enabled ? <div style={muted}>ReShade has not started in this game yet. Restart the game after turning it on.</div> : null;
  return (
    <div style={muted}>
      <div style={log.errors.length ? warnText : okText}>
        Last start {ago(log.modified)}{log.version ? `, ReShade ${log.version}` : ""}:{" "}
        {log.errors.length ? `${log.errors.length} error${log.errors.length === 1 ? "" : "s"}` : "no errors"}
        {log.warnings ? `, ${log.warnings} warning${log.warnings === 1 ? "" : "s"}` : ""}
      </div>
      {log.errors.slice(-2).map((e, i) => <div key={i}>{e}</div>)}
    </div>
  );
};

// The installable RenoDX mods, for picking one by hand; loaded once per panel lifetime.
let renodxMods: { name: string; status: string }[] | null = null;

const GamePage: FC<{ game: State["games"][number]; state: State; working: boolean; setBusy: (b: boolean) => void; refresh: () => void }> =
  ({ game, state, working, setBusy, refresh }) => {
    const [info, setInfo] = useState<GameInfo | null>(null);
    const [api, setApi] = useState<string | null>(null); // null: the detected one
    const [renodx, setRenodx] = useState(""); // the mod chosen for this game, by name
    const [mods, setMods] = useState(renodxMods);
    const [loading, setLoading] = useState(false);

    const wanted = useRef(0); // the newest load; an older one finishing late is dropped
    const load = useCallback(async (exe = "", renodxName = "") => {
      const ticket = ++wanted.current;
      setLoading(true);
      try {
        const next = await getGame(game.appid, exe, renodxName);
        if (wanted.current !== ticket) return;
        setInfo(next);
        setApi(next.enabled ? next.api ?? null : null);
        setRenodx(next.renodx?.installed || renodxName || next.renodx?.auto || "");
      } catch (e) {
        setInfo({ ok: false, error: String(e) });
      }
      setLoading(false);
    }, [game.appid]);

    useEffect(() => { load(); }, [load]);
    useEffect(() => {
      if (!renodxMods && state.renodx.count) getRenodxMods().then(r => { renodxMods = r.mods; setMods(r.mods); }, () => {});
    }, [state.renodx.count]);

    if (loading && !info) return <PanelSection><PanelSectionRow><Spinner /></PanelSectionRow></PanelSection>;
    if (!info) return null;
    if (!info.ok) return <PanelSection><PanelSectionRow><div style={errorBox}>{info.error}</div></PanelSectionRow></PanelSection>;

    const detected = info.detected_api ?? "dxgi";
    const effective = api ?? detected;
    const supported = (APIS as readonly string[]).includes(effective);
    const addon = state.reshade.addon;
    const autohdrPossible = addon && DXGI_APIS.includes(effective);
    const renodxOn = !!info.renodx?.installed;
    const mod = info.renodx?.mod ?? null;
    const modFits = !!mod && mod.files.includes(String(info.bits));

    // Apply a change; when ReShade is already on, the game is set up again with the new choice.
    const apply = async (on: boolean, change: { exe?: string; api?: string; autohdr?: boolean; renodx?: string } = {}) => {
      const exe = change.exe ?? info.exe ?? "";
      const chosen = change.api ?? effective;
      const hdr = (change.autohdr ?? !!info.autohdr) && addon && DXGI_APIS.includes(chosen);
      setBusy(true);
      await applyGame(game.appid, game.name, game.nonsteam, on, exe, chosen, hdr, change.renodx ?? info.renodx?.installed ?? "");
      await load(exe);
      setBusy(false);
      refresh();
    };

    const row = (child: ReactNode) => <PanelSectionRow>{child}</PanelSectionRow>;
    const busyHere = working || loading;
    return (
      <>
        <PanelSection title="ReShade">
          {row(
            <ToggleField label="ReShade in this game" checked={!!info.enabled} disabled={busyHere || (!info.enabled && !supported)}
              description={<LastRun log={info.log} enabled={!!info.enabled} />} onChange={on => apply(on)} />,
          )}
          {info.anticheat && row(<div style={errorBox}>{ANTICHEAT_WARNING}</div>)}
          {!info.enabled && row(<div style={muted}>Then restart the game and press Home to open ReShade.</div>)}
          {dloInstalled() && row(<div style={muted}>Launch options are up to Decky Launch Options: in its ReShade tab, pick this game's graphics API (and ReShade HDR for AutoHDR or RenoDX).</div>)}
        </PanelSection>

        <PanelSection title="HDR">
          {row(
            <ToggleField label="AutoHDR" checked={!!info.autohdr} disabled={busyHere || !autohdrPossible || renodxOn}
              description={!addon ? "Needs the add-on build (ReShade version page)."
                : !DXGI_APIS.includes(effective) ? "Works only with DirectX 10/11/12 games."
                : renodxOn ? "Off while the RenoDX mod is on: use one or the other."
                : `Turns SDR into HDR on HDR screens; turn on HDR in Steam's display settings too. Adds ${state.autohdr_env.join(" ")}.${state.reshade.autohdr_ready ? "" : " Downloads the add-on first (about 150 KB)."}`}
              onChange={on => info.enabled ? apply(true, { autohdr: on }) : setInfo({ ...info, autohdr: on })} />,
          )}
          {row(
            <Field label="RenoDX mod" description={mod ? <>
              <div style={mod.status === "working" ? okText : warnText}>{RENODX_STATUS[mod.status] ?? `⚠️ ${mod.note}`}</div>
              <div>{mod.name} · by {mod.maintainer}{mod.status !== "other" && mod.note ? ` · ${mod.note}` : ""}</div>
            </> : state.renodx.count ? "No RenoDX mod in the list matches this game; you can pick one below."
              : "The RenoDX list is not loaded yet (ReShade version page → Refresh RenoDX list)."} />,
          )}
          {row(
            <ToggleField label="Use the RenoDX mod" checked={renodxOn}
              disabled={busyHere || !addon || !!info.autohdr || (!renodxOn && (!info.enabled && !supported || !renodx || (!!mod && !modFits)))}
              description={!addon ? "Needs the add-on build (ReShade version page)."
                : info.autohdr ? "Off while AutoHDR is on: use one or the other."
                : !renodx ? "Pick a mod below."
                : mod && !modFits ? (mod.files.length ? `This mod is only ${mod.files.map(b => `${b}-bit`).join(" and ")}; the executable is ${info.bits}-bit.`
                  : `Only on Nexus Mods or Discord, install it by hand: ${mod.page}`)
                : `Downloads the mod from its author and puts it next to ReShade. Adds ${state.autohdr_env.join(" ")}; turn on HDR in Steam's display settings.`}
              onChange={on => apply(on || !!info.enabled, { renodx: on ? renodx : "" })} />,
          )}
          {renodxOn && row(
            <ButtonItem layout="below" disabled={busyHere} onClick={() => apply(true)} description="Downloads the newest snapshot of the mod again.">
              Update RenoDX mod
            </ButtonItem>,
          )}
          {mods && mods.length > 0 && row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Another RenoDX mod" disabled={busyHere} selectedOption={renodx || null}
              strDefaultLabel="None" description="Only if the matched one is wrong or none was found."
              rgOptions={mods.map(m => ({ data: m.name, label: `${renodxBadge(m.status)} ${m.name}${m.name === info.renodx?.auto ? " (matched)" : ""}` }))}
              onChange={o => renodxOn ? apply(true, { renodx: o.data }) : load(info.exe ?? "", o.data)} />,
          )}
        </PanelSection>

        <PanelSection title="Advanced">
          {row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Executable" disabled={busyHere} selectedOption={info.exe}
              description={`${info.bits}-bit. ReShade goes into this file's folder; pick the one that runs the game.`}
              rgOptions={(info.candidates ?? []).map(c => ({ data: c.exe, label: `${c.exe} (${c.bits}-bit)${c.running ? ", running now" : ""}` }))}
              onChange={o => info.enabled ? apply(true, { exe: o.data }) : load(o.data, renodx)} />,
          )}
          {row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Graphics API" disabled={busyHere} selectedOption={api ?? "auto"}
              description={info.detected_how === "default" ? "Could not be read from the game; DirectX 10/11/12 is the most common."
                : detected === "vulkan" ? "Vulkan games are not supported. If the game also has a DirectX mode, pick that here."
                : "If ReShade does not appear, try another one; dinput8 works with most games as a last resort."}
              rgOptions={[{ data: "auto", label: `Auto: ${API_LABEL[detected] ?? detected}` }, ...APIS.map(a => ({ data: a, label: API_LABEL[a] }))]}
              onChange={o => {
                const chosen = o.data === "auto" ? null : o.data as string;
                setApi(chosen);
                const next = chosen ?? detected;
                if (info.enabled && (APIS as readonly string[]).includes(next)) apply(true, { api: next });
              }} />,
          )}
          {row(
            <ButtonItem layout="below" disabled={!info.log?.found}
              onClick={() => getLogs(game.appid).then(l => showText(`ReShade log · ${game.name}`, l.reshade), e => notify("DeckyReshade", String(e)))}>
              Show ReShade log
            </ButtonItem>,
          )}
        </PanelSection>
      </>
    );
  };

// ---- plugin updates ------------------------------------------------------------------------------------------------

// Survives the QAM remounting the panel, like the panel state.
let updateView: { info: UpdateInfo | null; checking: boolean; downloading: boolean; path: string | null } =
  { info: null, checking: false, downloading: false, path: null };

const versionTag = (value: string) => (
  <span style={{ fontWeight: 700, color: "var(--gpColor-White, #fff)", background: "rgba(102,192,244,.18)", borderRadius: "4px", padding: "1px 6px" }}>
    v{value}
  </span>
);

// Same flow as FSR4 Injector and the Companion plugins: check GitHub, download the verified release ZIP to Downloads,
// install it by hand.
const Updates: FC<{ version: string }> = ({ version }) => {
  const [view, setViewRaw] = useState(updateView);
  const setView = (next: Partial<typeof updateView>) => { updateView = { ...updateView, ...next }; setViewRaw(updateView); };
  const { info, checking, downloading, path } = view;

  const check = async () => {
    if (updateView.checking || updateView.downloading) return;
    setView({ checking: true, info: null, path: null });
    try {
      setView({ info: await checkForUpdates() });
    } catch (e) {
      setView({ info: { error: String(e) } });
    }
    setView({ checking: false });
  };

  const download = async () => {
    const expected = updateView.info?.latest_version;
    if (!expected || updateView.checking || updateView.downloading) return;
    setView({ downloading: true });
    try {
      const res = await performUpdate(expected);
      if (res.path && res.version === expected) setView({ path: res.path });
      else setView({ info: { ...(updateView.info ?? {}), error: res.error ?? "The download did not finish." } });
    } catch (e) {
      setView({ info: { ...(updateView.info ?? {}), error: String(e) } });
    }
    setView({ downloading: false });
  };

  return (
    <PanelSection title="Plugin updates">
      <PanelSectionRow>
        <div style={muted}>
          Installed: {versionTag(info?.current_version ?? version)}
          {info?.latest_version && !info.error && <>{" · "}Latest: {versionTag(info.latest_version)}</>}
        </div>
      </PanelSectionRow>
      {info?.error && <PanelSectionRow><div style={errorBox}>{info.error}</div></PanelSectionRow>}
      {info && !info.error && !info.update_available && !path && (
        <PanelSectionRow><div style={{ fontSize: "12px", ...okText }}>Up to date</div></PanelSectionRow>
      )}
      {info?.update_available && info.asset_name && !path && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={checking || downloading} onClick={download}
            description="Downloads the release ZIP from GitHub to the Downloads folder and checks it.">
            {downloading ? "Downloading…" : `Download v${info.latest_version}`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {path && (
        <PanelSectionRow>
          <Field focusable label="Update downloaded" description={<span>
            Saved to <span style={{ fontFamily: "monospace", overflowWrap: "anywhere" }}>{path}</span>. To install:
            Decky → Settings → Developer → Install Plugin from ZIP. Your games stay set up.
          </span>} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={checking || downloading} onClick={check}
          description="Compares the installed version with the latest GitHub release.">
          {checking ? "Checking…" : "Check for updates"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};

// A shader-like prism.
const ReshadeIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round" style={{ width: "1em", height: "1em" }}>
    <path d="M12 3 3 20h18z" />
    <path d="M12 3v17" />
  </svg>
);

export default definePlugin(() => {
  // Never fail silently: when a game set up here exits, the backend checks that ReShade actually ran.
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(async (n: any) => {
    try {
      if (n?.bRunning) {
        await sessionStarted(n.unAppID);
        return;
      }
      const res = await sessionEnded(n.unAppID);
      if (res.warning) notify("ReShade did not start", res.warning);
    } catch {
      // backend restarting; nothing to report
    }
  });

  return {
    name: "DeckyReshade",
    titleView: <div className={staticClasses.Title}>ReShade</div>,
    content: <Content />,
    icon: <ReshadeIcon />,
    onDismount() {
      lifetime?.unregister?.();
    },
  };
});
