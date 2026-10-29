// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk

// The backend's answers and calls. Every call answers { ok, error?, state?, ... } (DeckyKit D2); callers go
// through settle() so a dead backend is an answer too, never a rejected promise.
import { callable } from "@decky/api";
import { UpdateCheck, UpdateDownload } from "./about";
import { Result } from "./result";

export const APIS = ["dxgi", "d3d9", "d3d10", "d3d11", "d3d12", "opengl32", "dinput8"] as const;
export const DXGI_APIS: readonly string[] = ["dxgi", "d3d10", "d3d11", "d3d12"];
export const API_LABEL: Record<string, string> = {
  dxgi: "DirectX 10/11/12 (dxgi)",
  d3d9: "Direct3D 8/9 (d3d9)",
  d3d10: "Direct3D 10 (d3d10)",
  d3d11: "Direct3D 11 (d3d11)",
  d3d12: "Direct3D 12 (d3d12)",
  opengl32: "OpenGL (opengl32)",
  dinput8: "Any API, loaded via dinput8 (fallback)",
  vulkan: "Vulkan (not supported yet)",
};
// The RenoDX wiki's legend, in words (UI.md §9: no emoji in states); other statuses show the mod's own note.
export const RENODX_STATUS: Record<string, string> = {
  working: "Working, playable",
  wip: "In progress, lacking testing, or may have deal-breaking issues",
};
// In the dense mod list a symbol stands for the status: ✓ working, ⚠ anything else.
export const renodxBadge = (status?: string | null) => (status === "working" ? "✓" : status ? "⚠" : "");
// What a pinned version is for; the newest is what "latest" falls back to.
export const VERSION_NOTE: Record<string, string> = { "6.5.1": "for DXVK HDR games whose ReShade menu breaks" };

export interface Package { id: string; name: string; description: string; default: boolean; required: boolean }
export interface Enabled { appid: number; name: string; api: string; exe: string; bits: number; autohdr: boolean; renodx: string }
export interface RenodxMod { name: string; maintainer: string; status: string; note: string; files: string[]; page: string; host: string }
export interface LogSummary { found: boolean; modified: number; version: string; errors: string[]; warnings: number }

export interface State {
  version: string;
  home: string;
  reshade: {
    // latest: what reshade.me offers; known: the newest version the plugin can check (what "latest" installs);
    // newer_than_known: a release that comes with a plugin update
    installed: string | null; addon: boolean; latest: string | null; known: string; newer_than_known: string | null;
    update_available: boolean; check_error: string; versions: string[]; autohdr_ready: boolean;
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

export interface GameInfo extends Result<never> {
  unsupported?: boolean; // a refusal that lasts (no Windows executable): no Try again
  candidates?: { exe: string; bits: number; running?: boolean }[];
  exe?: string;
  bits?: number;
  detected_api?: string;
  detected_how?: "imports" | "strings" | "default";
  anticheat?: boolean;
  enabled?: boolean;
  api?: string | null;
  autohdr?: boolean;
  renodx?: { installed: string; auto: string; mod: RenodxMod | null };
  log?: LogSummary;
}

export interface ToggleResult extends Result<never> {
  launch_options?: string; kept?: string[]; dlo?: boolean; dlo_leftover?: string;
}

export const getState = callable<[], Result<State>>("get_state");
export const scanGames = callable<[], Result<State>>("scan_games");
export const setup = callable<[boolean, string, boolean], Result<State>>("setup");
export const checkReshade = callable<[], Result<State>>("check_reshade");
export const updateReshade = callable<[], Result<State>>("update_reshade");
export const setSetting = callable<[string, boolean], Result<State>>("set_setting");
export const setVersion = callable<[string], Result<State>>("set_version");
export const loadPackages = callable<[], Result<State>>("load_packages");
export const setPackage = callable<[string, boolean], Result<State>>("set_package");
export const updateShaders = callable<[], Result<State>>("update_shaders");
export const removeData = callable<[], Result<State>>("remove_data");
export const refreshRenodx = callable<[], Result<State>>("refresh_renodx");
export const getGame = callable<[number, string, string], GameInfo>("get_game");
export const enableGame = callable<[number, string, string, boolean, string, string, boolean], ToggleResult>("enable_game");
export const disableGame = callable<[number, string], ToggleResult>("disable_game");
export const getRenodxMods = callable<[], Result<never> & { mods?: { name: string; status: string }[] }>("get_renodx_mods");
export const sessionStarted = callable<[number], Result<never> & { managed?: boolean }>("session_started");
export const sessionEnded = callable<[number], Result<never> & { managed?: boolean; loaded?: boolean; warning?: string }>("session_ended");
export const getLogs = callable<[number, string], Result<never> & { plugin?: string; reshade?: string }>("get_logs");
export const saveReport = callable<[], Result<never> & { path?: string }>("save_report");
export const checkForUpdates = callable<[], UpdateCheck>("check_for_updates");
export const performUpdate = callable<[string], UpdateDownload>("perform_update");
