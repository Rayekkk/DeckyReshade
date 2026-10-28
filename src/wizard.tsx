// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The first-run wizard: build, version, AutoHDR, one download, then how to use it.
import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, Spinner, ToggleField } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { setup, State } from "./api";
import { Result } from "./result";
import { errorBox, versionLabel } from "./shared";

export type Run = (call: () => Promise<Result<State>>) => Promise<void>;

// Survives the QAM remounting the panel.
let wizard = { step: 0, addon: true, version: "latest", autohdr: true };

/** Back to the welcome page (after the downloaded files were removed). */
export const resetWizard = () => { wizard = { ...wizard, step: 0 }; };

// Steps: 0 welcome, 1 build, 2 version, 3 AutoHDR, last: summary; 9 downloading, 10 how to use, 11 finished.
export const inWizard = (s: State) => !s.reshade.installed || wizard.step === 9 || wizard.step === 10;

export const Wizard: FC<{ state: State; busy: boolean; run: Run; onDone: () => void }> = ({ state, busy, run, onDone }) => {
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
            description="Latest is the newest version DeckyReshade has checksums for; every game gets new versions by itself. Pick a fixed version only if a game needs it; you can change it later."
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
            <li>If ReShade does not appear, the game's page shows why and lets you pick another executable or API.</li>
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
