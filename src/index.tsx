// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The panel: the setup wizard until ReShade is in place, then a main list of pages (as in Legion Go 2 Companion).
import { definePlugin } from "@decky/api";
import { ButtonItem, Field, PanelSection, PanelSectionRow, Router, Spinner, staticClasses } from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useState } from "react";
import { API_LABEL, Enabled, getState, RENODX_STATUS, scanGames, sessionEnded, sessionStarted, State } from "./api";
import { GamePage } from "./game";
import { AboutPage, ReshadePage, ShadersPage, TroubleshootingPage } from "./pages";
import { settle } from "./result";
import { applyGame, errorBox, muted, notify, PageHeader, PageShell, panel, SectionLink, warnText } from "./shared";
import { inWizard, Run, Wizard } from "./wizard";

type Page = "games" | "game" | "shaders" | "reshade" | "troubleshooting" | "about";

const gameSummary = (g?: Enabled) => !g ? "ReShade off"
  : `ReShade on · ${API_LABEL[g.api] ?? g.api}${g.autohdr ? " · AutoHDR" : ""}${g.renodx ? " · RenoDX" : ""}`;
const renodxNote = (status: string | null) => status ? `RenoDX mod: ${RENODX_STATUS[status] ?? "⚠️ see notes"}` : undefined;

// Every open of the menu starts on the main page (in game: with This game at the top), as in Legion Go 2 Companion.
const Content: FC = () => {
  const [state, setStateRaw] = useState<State | null>(panel.lastState);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPageRaw] = useState<Page | null>(null);
  const [gameId, setGameId] = useState<number | null>(null);
  const [gameFromList, setGameFromList] = useState(false); // opened from Games (else from the main page)
  const [, rerender] = useState(0);

  const setState = useCallback((s: State) => { panel.lastState = s; setStateRaw(s); }, []);
  const refresh = useCallback(() => settle(getState()).then(r => {
    if (r.state) { setState(r.state); setError(""); } else setError(r.error ?? "No answer from the backend.");
  }), [setState]);

  useEffect(() => {
    // The library is scanned on every open (cheap: manifests and shortcuts), so new games and shortcuts show up.
    settle(getState()).then(r => {
      if (!r.state) return setError(r.error ?? "No answer from the backend.");
      setState(r.state);
      settle(scanGames()).then(s => s.state && setState(s.state));
    });
  }, [setState]);

  // Poll while a download runs (and while any call is out: a job only shows up in the state it returns at its end).
  useEffect(() => {
    if (!state?.job.task && !busy) return;
    const t = setInterval(refresh, 700);
    return () => clearInterval(t);
  }, [state?.job.task, busy, refresh]);

  // A failed job is shown by the job box; any other refusal or failure as a toast.
  const run: Run = async call => {
    setBusy(true);
    const r = await settle(call());
    if (r.state) setState(r.state);
    if (!r.ok && r.error !== r.state?.job.error) notify("DeckyReshade", r.error ?? "Failed");
    setBusy(false);
  };

  const open = (next: Page | null, link?: string) => {
    if (link) panel.lastLink = link;
    setPageRaw(next);
  };
  const openGame = (appid: number, fromList: boolean) => {
    setGameFromList(fromList);
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

  if (!state) return <PanelSection>{error ? <Field label="Backend unavailable">{error}</Field> : <Spinner />}</PanelSection>;

  if (inWizard(state)) return <Wizard state={state} busy={busy} run={run} onDone={() => rerender(n => n + 1)} />;

  const { reshade, job, settings } = state;
  const working = busy || !!job.task;
  const enabled = (appid: number) => state.enabled.find(g => g.appid === appid);
  const running = Router.MainRunningApp;
  const runningGame = running ? state.games.find(g => g.appid === running.appid) : undefined;

  // A download in progress or a failed one, at the top of every page.
  const status = (job.task || (job.error && job.error !== panel.dismissedError)) ? (
    <PanelSection>
      {job.task && <PanelSectionRow><Field label={job.task}><Spinner style={{ width: "20px" }} /></Field></PanelSectionRow>}
      {job.error && job.error !== panel.dismissedError && (
        <>
          <PanelSectionRow><div style={errorBox}>{job.error}</div></PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => { panel.dismissedError = job.error; rerender(n => n + 1); }}>Dismiss</ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  ) : null;

  const versionNote = <>
    ReShade {reshade.installed} · {reshade.addon ? "add-on build" : "standard build"} · {settings.version === "latest" ? "updates automatically" : "fixed version"}
    {reshade.update_available && <div style={warnText}>ReShade {reshade.known} is available</div>}
  </>;

  const subpage = (title: string, body: ReactNode, withStatus = true) => (
    <PageShell>
      <PageHeader title={title} back="ReShade" onBack={() => open(null)} />
      {withStatus && status}
      {body}
    </PageShell>
  );

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
    return subpage("Games", <>
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
    </>);
  }

  if (page === "shaders") return subpage("Shaders", <ShadersPage state={state} working={working} run={run} />);
  if (page === "reshade") return subpage("ReShade version", <ReshadePage state={state} working={working} run={run} />);
  if (page === "troubleshooting")
    return subpage("Troubleshooting", <TroubleshootingPage state={state} working={working} run={run} onRemoved={() => open(null)} />);
  return subpage("About", <AboutPage version={state.version} />, false);
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
    },
  };
});
