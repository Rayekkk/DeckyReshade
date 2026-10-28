// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The pages behind the main list: shaders, ReShade version, troubleshooting, about (with plugin updates).
import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, Spinner, ToggleField } from "@decky/ui";
import { FC, useEffect, useRef, useState } from "react";
import {
  checkForUpdates, checkReshade, getLogs, loadPackages, performUpdate, refreshRenodx, removeData, saveReport,
  setPackage, setSetting, setVersion, State, updateReshade, UpdateInfo, updateShaders,
} from "./api";
import { settle } from "./result";
import { ago, confirm, dloInstalled, errorBox, exportToDlo, muted, notify, okText, showText, versionLabel, warnText } from "./shared";
import { resetWizard, Run } from "./wizard";

export const ShadersPage: FC<{ state: State; working: boolean; run: Run }> = ({ state, working, run }) => {
  // The list loads as a job; while another job runs it waits for it instead of being refused, once per open.
  const asked = useRef(false);
  useEffect(() => {
    if (state.shaders.packages || working || asked.current) return;
    asked.current = true;
    run(loadPackages);
  }, [state.shaders.packages, working]);
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

export const ReshadePage: FC<{ state: State; working: boolean; run: Run }> = ({ state, working, run }) => {
  const { reshade, settings } = state;
  return (
    <>
      <PanelSection title="Version">
        <PanelSectionRow>
          <Field label={`ReShade ${reshade.installed}`} description={<>
            <div>{reshade.addon ? "Add-on build" : "Standard build"} · {settings.version === "latest" ? "updates automatically" : "fixed version"}</div>
            {reshade.update_available ? <div style={warnText}>ReShade {reshade.known} is available.</div>
              : reshade.check_error ? <div style={warnText}>{reshade.check_error}</div>
              : reshade.newer_than_known ? <div style={warnText}>ReShade {reshade.newer_than_known} is out. It comes with the next DeckyReshade update, which adds its checksums.</div>
              : settings.version === "latest" && reshade.latest ? <div style={okText}>Up to date</div> : null}
          </>} />
        </PanelSectionRow>
        {reshade.update_available ? (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={working} onClick={() => run(updateReshade)}
              description="Every game set up here gets the new version at its next start.">
              Update to ReShade {reshade.known}
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
    </>
  );
};

export const TroubleshootingPage: FC<{ state: State; working: boolean; run: Run; onRemoved: () => void }> =
  ({ state, working, run, onRemoved }) => {
    const showLog = async () => {
      const l = await settle(getLogs(0, ""));
      if (l.ok) showText("DeckyReshade log", l.plugin ?? "");
      else notify("DeckyReshade", l.error ?? "The log could not be read.");
    };
    const report = async () => {
      const res = await settle(saveReport());
      if (res.ok && res.path) showText("Report saved", `${res.path}\n\nAttach this file when you report a problem.`);
      else notify("DeckyReshade", res.error ?? "The report could not be saved.");
    };
    return (
      <>
        <PanelSection title="Logs">
          <PanelSectionRow>
            <Field label="ReShade's own log" description="Each game's page has Show ReShade log: what ReShade did in that game and which effects failed." />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={showLog}
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
                    "Remove", () => { resetWizard(); onRemoved(); run(removeData); })}
              description="Deletes ReShade, add-ons and shaders from this device. Games must be turned off first.">
              Remove downloaded files
            </ButtonItem>
          </PanelSectionRow>
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

// Same flow as FSR4 Injector and the Companion plugins (DeckyKit's dk_update): check GitHub, download the verified
// release ZIP to Downloads, install it by hand.
const Updates: FC<{ version: string }> = ({ version }) => {
  const [view, setViewRaw] = useState(updateView);
  const setView = (next: Partial<typeof updateView>) => { updateView = { ...updateView, ...next }; setViewRaw(updateView); };
  const { info, checking, downloading, path } = view;

  const check = async () => {
    if (updateView.checking || updateView.downloading) return;
    setView({ checking: true, info: null, path: null });
    setView({ info: await settle(checkForUpdates()), checking: false });
  };

  const download = async () => {
    const expected = updateView.info?.latest_version;
    if (!expected || updateView.checking || updateView.downloading) return;
    setView({ downloading: true });
    const res = await settle(performUpdate(expected));
    if (res.ok && res.path && res.version === expected) setView({ path: res.path });
    else setView({ info: { ...(updateView.info ?? { ok: false }), ok: false, error: res.error ?? "The download did not finish." } });
    setView({ downloading: false });
  };

  return (
    <PanelSection title="Plugin updates">
      <PanelSectionRow>
        <div style={muted}>
          Installed: {versionTag(info?.current_version ?? version)}
          {info?.ok && info.latest_version && <>{" · "}Latest: {versionTag(info.latest_version)}</>}
        </div>
      </PanelSectionRow>
      {info && !info.ok && <PanelSectionRow><div style={errorBox}>{info.error}</div></PanelSectionRow>}
      {info?.ok && info.message && <PanelSectionRow><div style={{ fontSize: "12px", ...warnText }}>{info.message}</div></PanelSectionRow>}
      {info?.ok && !info.update_available && !info.no_release && !path && (
        <PanelSectionRow><div style={{ fontSize: "12px", ...okText }}>Up to date</div></PanelSectionRow>
      )}
      {info?.ok && info.download_available && !path && (
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

export const AboutPage: FC<{ version: string }> = ({ version }) => (
  <>
    <PanelSection title="DeckyReshade">
      <PanelSectionRow>
        <Field label={`Version ${version}`} description="ReShade for Steam and non-Steam games under Proton, set up from Gaming Mode." />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Author" description="Rayek · BSD-3-Clause open-source plugin." />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Downloaded on your device" description="ReShade by crosire (reshade.me); AutoHDR add-on by EndlesslyFlowering; AdvancedAutoHDR by Pumbo; RenoDX mods by their authors; shaders by theirs." />
      </PanelSectionRow>
    </PanelSection>
    <Updates version={version} />
  </>
);
