// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The pages behind the main list: shaders, ReShade version, troubleshooting (About is DeckyKit's about.tsx).
import { DropdownItem, PanelSection, PanelSectionRow, Spinner, ToggleField } from "@decky/ui";
import { FC, useEffect, useRef } from "react";
import {
  checkReshade, getLogs, loadPackages, refreshRenodx, removeData, saveReport, setPackage, setSetting, setVersion, State,
  updateReshade, updateShaders,
} from "./api";
import { settle } from "./result";
import { ago, keepPage, NAME, okText, showText, versionLabel, warnText } from "./shared";
import { ActionButton, confirmAction, infoRow, notify } from "./ui";
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
        {infoRow(`${installed.length} package${installed.length === 1 ? "" : "s"} installed`,
          "Shared by every game; changes reach them at their next start. In game, ReShade lists their effects.")}
        <PanelSectionRow>
          <ActionButton disabled={working || !installed.length} onClick={() => run(updateShaders)}
            description="Downloads the newest version of every installed package.">
            Update shaders
          </ActionButton>
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
        {infoRow(`ReShade ${reshade.installed}`, <>
          <div>{reshade.addon ? "Add-on build" : "Standard build"} · {settings.version === "latest" ? "updates automatically" : "fixed version"}</div>
          {reshade.update_available ? <div style={warnText}>ReShade {reshade.known} is available.</div>
            : reshade.check_error ? <div style={warnText}>{reshade.check_error}</div>
            : reshade.newer_than_known ? <div style={warnText}>ReShade {reshade.newer_than_known} is out. It comes with the next DeckyReshade update, which adds its checksums.</div>
            : settings.version === "latest" && reshade.latest ? <div style={okText}>Up to date</div> : null}
        </>)}
        {reshade.update_available ? (
          <PanelSectionRow>
            <ActionButton disabled={working} onClick={() => run(updateReshade)}
              description="Every game set up here gets the new version at its next start.">
              Update to ReShade {reshade.known}
            </ActionButton>
          </PanelSectionRow>
        ) : settings.version === "latest" && (
          <PanelSectionRow>
            <ActionButton disabled={working} onClick={() => run(checkReshade)}>Check for a new ReShade now</ActionButton>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <DropdownItem layout="below" childrenContainerWidth="max" label="Version" disabled={working} selectedOption={settings.version}
            description="Changing it moves every game to that version."
            rgOptions={["latest", ...reshade.versions].map(v => ({ data: v, label: versionLabel(v, reshade.versions[0]) }))}
            onMenuWillOpen={keepPage} onChange={o => run(() => setVersion(o.data))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Add-on build" checked={settings.addon} disabled={working}
            description="Needed for AutoHDR, RenoDX and depth add-ons. ReShade turns this build off in online games; use the standard build there."
            onChange={on => run(() => setSetting("addon", on))} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Launch options">
        <PanelSectionRow>
          <ToggleField label="Use launch options" checked={settings.use_launch_options} disabled={working}
            description={settings.use_launch_options
              ? "You add ReShade's line to each game's launch options: turning a game on copies it, and the game's page has a Copy button. Nothing else is changed outside the game folder."
              : "Off: no launch options needed. ReShade starts by itself; OpenGL games (and Direct3D 10 when picked by hand) get a Wine setting for their executable, made after the game's first start. Turn on if ReShade does not start in a game."}
            onChange={on => run(() => setSetting("use_launch_options", on))} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="RenoDX mod list">
        <PanelSectionRow>
          <ActionButton disabled={working} onClick={() => run(refreshRenodx)}
            description={<>
              <div>{state.renodx.count ? `${state.renodx.count} RenoDX mods known${state.renodx.fetched_at ? `, list from ${ago(state.renodx.fetched_at)}` : ""}. Refreshed once a day.` : "The RenoDX mod list has not been loaded yet."}</div>
              {state.renodx.error && <div style={warnText}>{state.renodx.error}</div>}
            </>}>
            Refresh RenoDX list
          </ActionButton>
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
      else notify(NAME, l.error ?? "The log could not be read.");
    };
    const report = async () => {
      const res = await settle(saveReport());
      if (res.ok && res.path) showText("Report saved", `${res.path}\n\nAttach this file when you report a problem.`);
      else notify(NAME, res.error ?? "The report could not be saved.");
    };
    // The dialog hides the panel, so the outcome is always a toast (UI.md §5); run() already toasts a refusal.
    const remove = async () => {
      resetWizard();
      onRemoved();
      const r = await run(removeData);
      if (r.ok) notify(NAME, "Downloaded files were removed. Setup starts again the next time you open this menu.");
      else if (r.error && r.error === r.state?.job.error) notify(NAME, r.error);
    };
    return (
      <>
        <PanelSection title="Logs">
          {infoRow("ReShade's own log", "Each game's page has Show ReShade log: what ReShade did in that game and which effects failed.")}
          <PanelSectionRow>
            <ActionButton onClick={showLog}
              description="Everything the plugin did: downloads, games turned on or off, Wine settings, errors.">
              Show plugin log
            </ActionButton>
          </PanelSectionRow>
          <PanelSectionRow>
            <ActionButton onClick={report}
              description="Saves the plugin log, settings and every game's ReShade log to one file in Downloads, to attach to a bug report.">
              Save report to Downloads
            </ActionButton>
          </PanelSectionRow>
        </PanelSection>
        <PanelSection title="Start over">
          <PanelSectionRow>
            <ActionButton disabled={working}
              onClick={() => state.enabled.length
                ? notify(NAME, "Turn ReShade off in all games first (Games); they still use these files.")
                : confirmAction("Remove downloaded files?", "ReShade, the shader compiler, AutoHDR, RenoDX mods and all shader packages are deleted from this device. Setup starts again next time. Your games and their ReShade settings stay.",
                    "Remove", () => void remove(), { destructive: true })}
              description="Deletes ReShade, add-ons and shaders from this device. Games must be turned off first.">
              Remove downloaded files
            </ActionButton>
          </PanelSectionRow>
        </PanelSection>
      </>
    );
  };
