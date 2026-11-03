// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The panel: the setup wizard until ReShade is in place, then a main list of pages (UI.md §1 level B), About last.
import { definePlugin, useQuickAccessVisible } from "@decky/api";
import { Field, PanelSection, PanelSectionRow, Router, Spinner, staticClasses } from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { AboutPage, INSTALL_HINT, UpdateController, UpdateSection } from "./about";
import { API_LABEL, checkForUpdates, Enabled, getState, performUpdate, scanGames, sessionEnded, sessionStarted, State } from "./api";
import { GamePage } from "./game";
import { ReshadePage, ShadersPage, TroubleshootingPage } from "./pages";
import { settle } from "./result";
import { applyGame, errorStyle, ICONS, muted, NAME, panel, takeResume, warnText } from "./shared";
import { ActionButton, infoRow, notify, PageHeader, PageShell, SectionLink, statusPlaceholder } from "./ui";
import { inWizard, Run, Wizard } from "./wizard";

type Page = "games" | "game" | "shaders" | "reshade" | "troubleshooting" | "about";

// One updater per plugin load: a check or download keeps running while the QAM is closed or the page changes.
let updates: UpdateController | null = null;
const updater = () => (updates ??= new UpdateController({ check: checkForUpdates, download: performUpdate }, "deckyreshade"));

const gameSummary = (g?: Enabled) => !g ? "ReShade off"
  : `ReShade on · ${API_LABEL[g.api] ?? g.api}${g.autohdr ? " · AutoHDR" : ""}${g.renodx ? " · RenoDX" : ""}`;
const renodxNote = (status: string | null) =>
  status ? `RenoDX mod: ${status === "working" ? "working" : status === "wip" ? "in progress" : "see its notes"}` : undefined;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Every open of the menu starts on the main page (in game: with This game at the top), as in Legion Go 2 Companion;
// back from a dropdown menu or a dialog, which Decky unmounts the panel for, it is on the page it was.
const Content: FC = () => {
  const visible = useQuickAccessVisible();
  const [resumed] = useState(takeResume);
  const [state, setStateRaw] = useState<State | null>(panel.lastState);
  const [error, setError] = useState("");
  const [failure, setFailure] = useState("");  // the last refused action, until the next action or page (UI.md §5)
  const [busy, setBusy] = useState(false);
  const [page, setPageRaw] = useState<Page | null>((resumed?.page as Page | null) ?? null);
  const [gameId, setGameId] = useState<number | null>(resumed?.gameId ?? null);
  const [gameFromList, setGameFromList] = useState(resumed?.gameFromList ?? false); // opened from Games (else main)
  panel.nav = { page, gameId, gameFromList };
  const [back, setBack] = useState("");  // the row of the page just left: focused once on the way back
  const openers = useRef<Partial<Record<Page, string>>>({});  // the row that opened each page
  const [, rerender] = useState(0);

  const setState = useCallback((s: State) => { panel.lastState = s; setStateRaw(s); }, []);
  const refresh = useCallback(() => settle(getState()).then(r => {
    if (r.state) { setState(r.state); setError(""); } else setError(r.error ?? "No answer from the backend.");
  }), [setState]);

  // The library is scanned on every open (cheap: manifests and shortcuts), so new games and shortcuts show up.
  const load = useCallback(() => settle(getState()).then(r => {
    if (!r.state) return setError(r.error ?? "No answer from the backend.");
    setState(r.state);
    settle(scanGames()).then(s => s.state && setState(s.state));
  }), [setState]);
  useEffect(() => { load(); }, [load]);

  // Poll while a download runs (and while any call is out: a job only shows up in the state it returns at its end).
  useEffect(() => {
    if (!state?.job.task && !busy) return;
    const t = setInterval(refresh, 700);
    return () => clearInterval(t);
  }, [state?.job.task, busy, refresh]);

  // A failed job is shown by the job box; any other refusal there too, and as a toast.
  const run: Run = async call => {
    setBusy(true);
    setFailure("");
    const r = await settle(call());
    if (r.state) setState(r.state);
    if (!r.ok && r.error !== r.state?.job.error) {
      notify(NAME, r.error ?? "Failed");
      setFailure(r.error ?? "Failed");
    }
    setBusy(false);
    return r;
  };

  const open = (next: Page, link: string) => {
    openers.current[next] = link;
    setBack("");
    setFailure("");
    setPageRaw(next);
  };
  const goBack = (to: Page | null) => {
    setBack(page ? openers.current[page] ?? "" : "");
    setFailure("");
    setPageRaw(to);
  };
  const openGame = (appid: number, fromList: boolean) => {
    setGameFromList(fromList);
    setGameId(appid);
    open("game", fromList ? `game-${appid}` : "this-game");
  };
  const focus = (id: string) => visible && back === id;

  const turnOffAll = async () => {
    setBusy(true);
    setFailure("");
    let ok = 0;
    const games = state?.enabled ?? [];
    for (const g of games) if (!await applyGame(g.appid, g.name, false)) ok++;
    notify(NAME, `${ok} of ${plural(games.length, "game")} restored to how they were.`);
    setBusy(false);
    refresh();
  };

  if (!state) return <>
    {statusPlaceholder({ title: NAME, label: `${NAME} unavailable`, error, onRetry: () => { setError(""); load(); } })}
    {/* A plugin that cannot start can still be updated. */}
    {error && <UpdateSection controller={updater()} version={__PLUGIN_VERSION__} />}
  </>;

  if (inWizard(state)) return <Wizard state={state} busy={busy} run={run} onDone={() => rerender(n => n + 1)} />;

  const { reshade, job, settings } = state;
  const working = busy || !!job.task;
  const enabled = (appid: number) => state.enabled.find(g => g.appid === appid);
  const running = Router.MainRunningApp;
  const runningGame = running ? state.games.find(g => g.appid === running.appid) : undefined;

  // A download in progress, a failed one or a refused action, at the top of every page.
  const shown = failure || (job.error !== panel.dismissedError ? job.error : "");
  const status = (job.task || shown) ? (
    <PanelSection>
      {job.task && <PanelSectionRow><Field label={job.task}><Spinner style={{ width: "20px" }} /></Field></PanelSectionRow>}
      {shown && <>
        {infoRow("Could not complete", <div role="alert" style={errorStyle}>{shown}</div>)}
        <PanelSectionRow>
          <ActionButton onClick={() => { panel.dismissedError = job.error; setFailure(""); }}>Dismiss</ActionButton>
        </PanelSectionRow>
      </>}
    </PanelSection>
  ) : null;

  const subpage = (title: string, body: ReactNode) => (
    <PageShell onBack={() => goBack(null)}>
      <PageHeader title={title} back="ReShade" onBack={() => goBack(null)} focus={visible} />
      {status}
      {body}
    </PageShell>
  );

  if (!page) {
    const renodxGames = state.games.filter(g => g.renodx).length;
    const installed = state.shaders.installed.length;
    return (
      <PageShell>
        {status}
        <PanelSection title="ReShade">
          {runningGame && <SectionLink icon={ICONS.game} title={`This game: ${runningGame.name}`} focus={focus("this-game")}
            description={gameSummary(enabled(runningGame.appid))} note={renodxNote(runningGame.renodx)}
            onOpen={() => openGame(runningGame.appid, false)} />}
          <SectionLink icon={ICONS.games} title="Games" focus={focus("games")}
            description={`${state.enabled.length} with ReShade · ${renodxGames} with a RenoDX mod · ${plural(state.games.length, "game")}`}
            onOpen={() => open("games", "games")} />
          <SectionLink icon={ICONS.shaders} title="Shaders" focus={focus("shaders")}
            description={`${plural(installed, "package")} installed`} onOpen={() => open("shaders", "shaders")} />
          <SectionLink icon={ICONS.version} title="ReShade version" focus={focus("reshade")}
            description={`ReShade ${reshade.installed} · ${reshade.addon ? "add-on build" : "standard build"} · ${settings.version === "latest" ? "updates automatically" : "fixed version"}`}
            note={reshade.update_available && <span style={warnText}>ReShade {reshade.known} is available.</span>}
            onOpen={() => open("reshade", "reshade")} />
        </PanelSection>
        <PanelSection title="Plugin">
          <SectionLink icon={ICONS.troubleshooting} title="Troubleshooting" focus={focus("troubleshooting")}
            description="Logs and a report for when ReShade does not work." onOpen={() => open("troubleshooting", "troubleshooting")} />
          <SectionLink icon={ICONS.about} title="About" focus={focus("about")} description={`Version ${state.version} · updates`}
            onOpen={() => open("about", "about")} />
        </PanelSection>
      </PageShell>
    );
  }

  if (page === "game" && gameId !== null) {
    const game = state.games.find(g => g.appid === gameId);
    const up = () => goBack(gameFromList ? "games" : null);
    return (
      <PageShell onBack={up}>
        <PageHeader title={game?.name ?? "Game"} back={gameFromList ? "Games" : "ReShade"} onBack={up} focus={visible} />
        {status}
        {game ? <GamePage key={game.appid} game={game} state={state} working={working} setBusy={setBusy} refresh={refresh}
          fail={setFailure} />
          : <PanelSection>{infoRow("Game not found", "This game is not in the library any more.")}</PanelSection>}
      </PageShell>
    );
  }

  if (page === "games") {
    const others = state.games.filter(g => !enabled(g.appid))
      .sort((a, b) => (b.appid === runningGame?.appid ? 1 : 0) - (a.appid === runningGame?.appid ? 1 : 0));
    return subpage("Games", <>
      {state.enabled.length > 0 && (
        <PanelSection title="With ReShade">
          {state.enabled.map(g => (
            <SectionLink key={g.appid} icon={ICONS.game} title={g.name} description={gameSummary(g)} note={g.exe}
              focus={focus(`game-${g.appid}`)} onOpen={() => openGame(g.appid, true)} />
          ))}
          <PanelSectionRow>
            <ActionButton disabled={working} onClick={turnOffAll}
              description="Removes ReShade's DLLs and Wine settings from every game; launch options you added yourself stay. Your ReShade settings, presets and logs stay in the game folders. Do this before uninstalling.">
              Turn off ReShade in all games
            </ActionButton>
          </PanelSectionRow>
        </PanelSection>
      )}
      <PanelSection title={state.scanned ? "All games" : "Scanning your library…"}>
        {others.map(g => (
          <SectionLink key={g.appid} icon={ICONS.game} title={`${g.appid === runningGame?.appid ? "▶ " : ""}${g.name}`}
            description={g.nonsteam ? "Non-Steam game" : "ReShade off"} note={renodxNote(g.renodx)}
            focus={focus(`game-${g.appid}`)} onOpen={() => openGame(g.appid, true)} />
        ))}
        {state.scanned && !others.length
          && infoRow("No other games found", <span style={muted}>Games you install show up the next time you open this menu.</span>)}
      </PanelSection>
    </>);
  }

  if (page === "shaders") return subpage("Shaders", <ShadersPage state={state} working={working} run={run} />);
  if (page === "reshade") return subpage("ReShade version", <ReshadePage state={state} working={working} run={run} />);
  if (page === "troubleshooting")
    return subpage("Troubleshooting", <TroubleshootingPage state={state} working={working} run={run} onRemoved={() => goBack(null)} />);
  return (
    <PageShell onBack={() => goBack(null)}>
      <PageHeader title="About" back="ReShade" onBack={() => goBack(null)} focus={visible} />
      <AboutPage name={NAME} version={state.version} license="BSD-3-Clause"
        description="ReShade for Steam and non-Steam games under Proton, set up from Gaming Mode."
        notes="Copyright (c) 2026 Rayekkk. Dependency notices are included in the plugin package."
        credits={[["Downloaded on your device", "ReShade by crosire (reshade.me); AutoHDR add-on by EndlesslyFlowering; " +
          "AdvancedAutoHDR by Pumbo; RenoDX mods by their authors; shaders by theirs."]]}
        updates={updater()} home={state.home} install={`${INSTALL_HINT} Your games stay set up.`} />
    </PageShell>
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
  const lifetime = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(async n => {
    if (n?.bRunning) {
      await settle(sessionStarted(n.unAppID));
      return;
    }
    const res = await settle(sessionEnded(n.unAppID));  // a backend restarting just answers ok: false
    if (res.warning) notify("ReShade did not start", res.warning);
  });

  return {
    name: "DeckyReshade",
    titleView: <div className={staticClasses.Title}>ReShade</div>,
    content: <Content />,
    icon: <ReshadeIcon />,
    onDismount() {
      if (typeof lifetime === "function") lifetime();
      else lifetime?.unregister();
      updates?.dispose();
      updates = null;
    },
  };
});
