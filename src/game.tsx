// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// One game: ReShade on or off, AutoHDR, a RenoDX mod, the executable and graphics API, ReShade's log.
import { DropdownItem, Field, Navigation, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { FC, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  API_LABEL, APIS, DXGI_APIS, GameInfo, getGame, getLogs, getRenodxMods, LogSummary, RENODX_STATUS, RenodxMod, renodxBadge,
  State,
} from "./api";
import { settle } from "./result";
import {
  ago, applyGame, Choice, copyLaunchOptions, errorStyle, keepPage, muted, NAME, okText, panel, pick, showText, warnText,
} from "./shared";
import { ActionButton, colors, notify, statusPlaceholder } from "./ui";

const ANTICHEAT_WARNING = "Anti-cheat detected: ReShade in online games can get you kicked or banned. " +
  "Turning it on is at your own risk.";

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

// What the AutoHDR add-on did in the game's last start (ReShade.log).
const AUTOHDR_RESULT: Record<string, ReactNode> = {
  on: <div style={okText}>The last start was in HDR.</div>,
  off: <div style={warnText}>The last start stayed in SDR: the AutoHDR add-on does not work with every game.</div>,
  no_hdr: <div style={warnText}>The last start stayed in SDR: HDR is off in Steam's display settings.</div>,
};

// Steam's own HDR switch (Settings → Display); undefined when this Steam does not say.
const steamHdr = () => (window as unknown as { settingsStore?: { m_ClientSettings?: { gamescope_hdr_enabled?: boolean } } })
  .settingsStore?.m_ClientSettings?.gamescope_hdr_enabled;

// What the RenoDX list says about this game (settings for the RenoDX menu, steps, why it does not work), framed in the
// colour of its status: green working, yellow still being tested, red anything else (broken, abandoned, superseded).
const NOTE_COLORS = { working: [colors.ok, colors.okSurface], wip: [colors.warning, colors.warningSurface] } as const;
const ModNote: FC<{ mod: RenodxMod }> = ({ mod }) => {
  const [line, surface] = NOTE_COLORS[mod.status as keyof typeof NOTE_COLORS] ?? [colors.error, colors.errorSurface];
  return (
    <div style={{ border: `1px solid ${line}`, borderRadius: "4px", padding: "6px 8px", marginTop: "6px", background: surface,
      color: colors.text, fontSize: "12px", overflowWrap: "anywhere" }}>
      {mod.note}
    </div>
  );
};

// The installable RenoDX mods, for picking one by hand; loaded once per panel lifetime.
let renodxMods: { name: string; status: string }[] | null = null;

// `fail` shows a refused change at the top of the page until the next action (UI.md §5).
export const GamePage: FC<{ game: State["games"][number]; state: State; working: boolean; setBusy: (b: boolean) => void;
  refresh: () => void; fail: (why: string) => void }> =
  ({ game, state, working, setBusy, refresh, fail }) => {
    // what the user chose here, kept while a dropdown menu outside the QAM has the panel unmounted (shared.tsx)
    const draft = (panel.drafts[game.appid] ??= {});
    const [info, setInfo] = useState<GameInfo | null>(null);
    const [api, setApiRaw] = useState<string | null>(draft.api ?? null); // null: the detected one
    const setApi = (a: string | null) => { draft.api = a; setApiRaw(a); };
    const [renodx, setRenodx] = useState(""); // the mod chosen for this game, by name
    const [mods, setMods] = useState(renodxMods);
    const [loading, setLoading] = useState(false);
    const [picks, setPicks] = useState(0);
    const choose = useRef<((c: Choice) => void) | null>(null);

    const wanted = useRef(0); // the newest load; an older one finishing late is dropped
    // keepApi: the page comes back after a remount, with the API picked before it
    const load = useCallback(async (exe = "", renodxName = "", keepApi = false) => {
      const ticket = ++wanted.current;
      Object.assign(draft, { exe, renodx: renodxName });
      setLoading(true);
      const next = await settle(getGame(game.appid, exe, renodxName));
      if (wanted.current !== ticket) return;
      setInfo(next);
      if (next.ok) {
        setApi(next.enabled ? next.api ?? null : keepApi ? draft.api ?? null : null);
        setRenodx(next.renodx?.installed || renodxName || next.renodx?.auto || "");
      }
      setLoading(false);
    }, [game.appid]);

    useEffect(() => { load(draft.exe ?? "", draft.renodx ?? "", true); }, [load]);
    useEffect(() => {
      const listener = () => setPicks(n => n + 1);
      panel.onPick = listener;
      return () => { if (panel.onPick === listener) panel.onPick = null; };
    }, []);
    // a dropdown choice, also one made while this page was unmounted, once the game is loaded
    useEffect(() => {
      const chosen = panel.pick;
      if (!info?.ok || loading || chosen?.appid !== game.appid || !choose.current) return;
      panel.pick = null;
      choose.current(chosen.choice);
    }, [info, loading, picks]);
    useEffect(() => {
      if (!renodxMods && state.renodx.count)
        settle(getRenodxMods()).then(r => { if (r.mods) { renodxMods = r.mods; setMods(r.mods); } });
    }, [state.renodx.count]);

    // A spinner while loading; a failed read says why and offers Try again, a game that cannot be supported only
    // says why (UI.md §4).
    if (info?.unsupported) return <PanelSection>
      <PanelSectionRow><Field focusable label="Game not supported" description={info.error} /></PanelSectionRow>
    </PanelSection>;
    if (!info?.ok) return statusPlaceholder({ label: "Game details unavailable",
      error: loading || !info ? "" : info.error ?? "Failed", onRetry: () => void load() });

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
      // the standard build cannot run RenoDX: a change made without the add-on build takes it out
      const reno = addon ? change.renodx ?? info.renodx?.installed ?? "" : "";
      setBusy(true);
      fail("");
      const why = await applyGame(game.appid, game.name, on, exe, chosen, hdr, reno);
      fail(why);
      // the line to paste changes only with the API: copied when it is new to this game
      if (!why && on && state.settings.use_launch_options && (!info.enabled || info.api !== chosen))
        await copyLaunchOptions(game.name, chosen);
      await load(exe);
      setBusy(false);
      refresh();
    };

    choose.current = c => {
      // ReShade off: only the page changes, keeping an API picked by hand
      if (c.exe !== undefined) return void (info.enabled ? apply(true, { exe: c.exe }) : load(c.exe, renodx, true));
      if (c.renodx !== undefined)
        return void (renodxOn ? apply(true, { renodx: c.renodx }) : load(info.exe ?? "", c.renodx, true));
      setApi(c.api ?? null);
      const next = c.api ?? detected;
      if (info.enabled && (APIS as readonly string[]).includes(next)) apply(true, { api: next });
    };

    const showLog = async () => {
      const l = await settle(getLogs(game.appid, info.exe ?? ""));
      if (l.ok) showText(`ReShade log · ${game.name}`, l.reshade ?? "");
      else notify(NAME, l.error ?? "The log could not be read.");
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
          {info.anticheat && row(<div style={errorStyle}>{ANTICHEAT_WARNING}</div>)}
          {!info.enabled && row(<div style={muted}>Then restart the game and press Home to open ReShade.</div>)}
          {state.settings.use_launch_options && supported && row(
            <ActionButton disabled={busyHere} onClick={() => copyLaunchOptions(game.name, effective)}
              description={<span style={{ overflowWrap: "anywhere" }}>Add to the game's launch options: {state.launch_options[effective]}</span>}>
              Copy launch options
            </ActionButton>,
          )}
        </PanelSection>

        <PanelSection title="HDR">
          {steamHdr() === false && row(
            <ActionButton onClick={() => { Navigation.Navigate("/settings/display"); Navigation.CloseSideMenus(); }}
              description={<span style={warnText}>HDR is off in Steam's display settings; AutoHDR and RenoDX need it on.</span>}>
              Open display settings
            </ActionButton>,
          )}
          {row(
            <ToggleField label="AutoHDR" checked={!!info.autohdr} disabled={busyHere || (!info.autohdr && (!autohdrPossible || renodxOn))}
              description={!addon ? "Needs the add-on build (ReShade version page)."
                : !DXGI_APIS.includes(effective) ? "Works only with DirectX 10/11/12 games."
                : renodxOn ? "Off while the RenoDX mod is on: use one or the other."
                : <>
                  {info.autohdr && info.log?.found && AUTOHDR_RESULT[info.log.autohdr ?? ""]}
                  <div>Turns SDR into HDR on HDR screens.{state.reshade.autohdr_ready ? "" : " Downloads the add-on first (about 150 KB)."}</div>
                </>}
              onChange={on => info.enabled ? apply(true, { autohdr: on }) : setInfo({ ...info, autohdr: on })} />,
          )}
          {row(
            <Field label="RenoDX mod" description={mod ? <>
              <div style={mod.status === "working" ? okText : mod.status === "wip" ? warnText : errorStyle}>
                {RENODX_STATUS[mod.status] ?? (mod.note ? "Not marked working in the RenoDX list." : "See the mod's page for its status.")}
              </div>
              <div>{mod.name} · by {mod.maintainer}</div>
              {mod.note && <ModNote mod={mod} />}
            </> : state.renodx.count ? "No RenoDX mod in the list matches this game; you can pick one below."
              : "The RenoDX list is not loaded yet (ReShade version page → Refresh RenoDX list)."} />,
          )}
          {row(
            <ToggleField label="Use the RenoDX mod" checked={renodxOn}
              disabled={busyHere || (!renodxOn && (!addon || !!info.autohdr || !info.enabled && !supported || !renodx || (!!mod && !modFits)))}
              description={!addon ? "Needs the add-on build (ReShade version page)."
                : info.autohdr ? "Off while AutoHDR is on: use one or the other."
                : !renodx ? "Pick a mod below."
                : mod && !modFits ? (mod.files.length ? `This mod is only ${mod.files.map(b => `${b}-bit`).join(" and ")}; the executable is ${info.bits}-bit.`
                  : mod.engine ? `Not installable from here: the ${mod.engine} mod needs steps for this game that DeckyReshade cannot take (see the note), or is not marked working yet; install it by hand: ${mod.page}`
                  : `Not installable from here (only on Nexus Mods or Discord, or from an author DeckyReshade does not know yet); install it by hand: ${mod.page}`)
                : mod?.engine_ini ? `Downloads the ${mod.engine} mod from ${mod.host || "its author"}, turns on HDR in the game's Engine.ini (read-only, as the RenoDX list asks) and sets Upgrade Path to Off; turning the mod off puts both back. Start the game once before, so it makes its settings folder.`
                : mod?.engine ? `Downloads the ${mod.engine} mod from ${mod.host || "its author"}: made for the whole engine and tried on this game by its users.${mod.settings ? " Sets Upgrade Path to Off, as the RenoDX list asks." : " A setting the note names goes in the RenoDX menu in ReShade (Home)."}`
                : `Downloads the mod from ${mod?.host || "its author"} and puts it next to ReShade. If the game has its own HDR setting, turn it on there.`}
              onChange={on => apply(on || !!info.enabled, { renodx: on ? renodx : "" })} />,
          )}
          {renodxOn && row(
            <ActionButton disabled={busyHere} onClick={() => apply(true)} description="Downloads the newest snapshot of the mod again.">
              Update RenoDX mod
            </ActionButton>,
          )}
          {mods && mods.length > 0 && row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Another RenoDX mod" disabled={busyHere} selectedOption={renodx || null}
              strDefaultLabel="None" description="Only if the matched one is wrong or none was found."
              rgOptions={mods.map(m => ({ data: m.name, label: `${renodxBadge(m.status)} ${m.name}${m.name === info.renodx?.auto ? " (matched)" : ""}` }))}
              onMenuWillOpen={keepPage} onChange={o => pick(game.appid, { renodx: o.data })} />,
          )}
        </PanelSection>

        <PanelSection title="Advanced">
          {row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Executable" disabled={busyHere} selectedOption={info.exe}
              description={`${info.bits}-bit. ReShade goes into this file's folder; pick the one that runs the game.`}
              rgOptions={(info.candidates ?? []).map(c => ({ data: c.exe, label: `${c.exe} (${c.bits}-bit)${c.running ? ", running now" : ""}` }))}
              onMenuWillOpen={keepPage} onChange={o => pick(game.appid, { exe: o.data })} />,
          )}
          {row(
            <DropdownItem layout="below" childrenContainerWidth="max" label="Graphics API" disabled={busyHere} selectedOption={api ?? "auto"}
              description={info.detected_how === "default" ? "Could not be read from the game; DirectX 10/11/12 is the most common."
                : detected === "vulkan" ? "Vulkan games are not supported. If the game also has a DirectX mode, pick that here."
                : "If ReShade does not appear, try another one; dinput8 works with most games as a last resort."}
              rgOptions={[{ data: "auto", label: `Auto: ${API_LABEL[detected] ?? detected}` }, ...APIS.map(a => ({ data: a, label: API_LABEL[a] }))]}
              onMenuWillOpen={keepPage} onChange={o => pick(game.appid, { api: o.data === "auto" ? null : o.data as string })} />,
          )}
          {row(
            <ActionButton disabled={!info.log?.found} onClick={showLog}>
              Show ReShade log
            </ActionButton>,
          )}
        </PanelSection>
      </>
    );
  };
