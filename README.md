# DeckyReshade

**ReShade for Steam and non-Steam games under Proton, set up and kept up to date from Gaming Mode.**

A [Decky Loader](https://decky.xyz) plugin. Open the Quick Access Menu in a game, turn ReShade on, restart the game,
press Home.

## Features

| Feature | What you get |
|---|---|
| **Guided setup** | On first open the plugin asks which ReShade build (add-ons recommended), which version and whether to get AutoHDR, then downloads everything (about 15 MB) |
| **Per game** | The running game is picked for you. The executable, its bitness (32/64-bit) and the graphics API are read from the game files; you can change both |
| **Non-Steam games** | Windows games and emulators added to Steam as shortcuts work like Steam games |
| **AutoHDR** | HDR for SDR games on HDR screens (Steam Deck OLED and other OLED handhelds), per game, with the AutoHDR add-on and Pumbo's AdvancedAutoHDR |
| **RenoDX** | HDR mods from the [RenoDX list](https://github.com/clshortfuse/renodx/wiki/Mods): each game shows whether a mod exists and its status (✅ working, 🚧 in progress), and installs it with one switch |
| **ReShade versions** | Latest (updated automatically from reshade.me) or a fixed one, e.g. 6.5.1 for DXVK HDR games |
| **Safe launch options** | `WINEDLLOVERRIDES` entries are merged with what is already there (your own, FSR4 Injector's) and restored exactly when you turn ReShade off |
| **Shader packages** | The same list ReShade's own installer offers, shared by all games, updatable |
| **Logs** | Each game shows when ReShade last started and its errors; the plugin log and a one-file report are a tap away |
| **Clean removal** | Only files the plugin wrote (checked by SHA-256) are removed; your ReShade settings and presets stay. Downloaded files can be deleted from the panel |

## Requirements

- SteamOS (or another Linux) with Decky Loader
- A game run through Proton that uses DirectX 8 to 12 or OpenGL. Vulkan games are not supported yet.
- AutoHDR: the add-on build, a DirectX 10/11/12 game, an HDR screen and HDR turned on in Steam's display settings.

## Quick start

1. Decky → DeckyReshade: follow the setup (build, version, AutoHDR, download).
2. Start a game, open the Quick Access Menu → DeckyReshade → **ReShade in this game** (and **AutoHDR** if you want it).
3. Restart the game and press **Home** for ReShade's overlay. No keyboard? Map Home to a back button in the game's
   Steam Input layout.

If ReShade does not show up, the game's section says when it last started and what went wrong. Pick another
**Executable** (the one that actually runs the game) or **Graphics API**; `dinput8` works with most games as a last
resort.

## Builds and versions

- **Add-on build** (default): needed for AutoHDR and depth add-ons. ReShade itself switches add-ons off in online
  multiplayer games; use the standard build for those.
- **Latest**: checked once a day; every game set up gets the new version. A **fixed version** (6.3.3 to 6.8.0, each
  checked against its SHA-256) stays until you change it.

## RenoDX

[RenoDX](https://github.com/clshortfuse/renodx) mods rebuild a game's tone mapping for real HDR. The plugin reads
the mod list on the RenoDX wiki once a day and matches it to your games by name (a game list entry shows
`RenoDX ✅` or `RenoDX 🚧`). In the game's section:

- the status, maintainer and any note from the list are shown; pick another mod by hand if the match is wrong or
  missing,
- **RenoDX HDR mod** downloads the mod's snapshot build from its author and puts it next to ReShade, with
  `DXVK_HDR=1`; **Update RenoDX mod** fetches the newest snapshot,
- mods only on Nexus Mods or Discord show their link to install by hand,
- RenoDX needs the add-on build and replaces AutoHDR (both together would tone-map twice). Turn on HDR in Steam's
  display settings.

Engine-wide mods (Unreal, Unity, Source) need per-game tweaks and are not offered.

## Troubleshooting

- **Show ReShade log** (per game): ReShade's own log from the game folder, with failed effects and missing files.
- **Show plugin log**: everything the plugin did, including each game's launch options before and after.
- **Save report to Downloads**: plugin log, settings and every game's ReShade log in one file for a bug report.
- **Remove downloaded files**: deletes ReShade, add-ons and shaders (games must be turned off first); setup starts again.

## How it works

- ReShade is downloaded from reshade.me. Its homepage links the current installer; that link is the version check.
  The installer is a ZIP archive behind a Windows program, so the plugin reads the two ReShade DLLs straight out of
  it and checks their PE headers. If reshade.me cannot be read, the newest known version (with a pinned SHA-256) is
  used and nothing that is already set up changes.
- Each game gets, next to its executable: ReShade as `dxgi.dll` / `d3d9.dll` / `d3d10.dll` / `d3d11.dll` /
  `d3d12.dll` / `opengl32.dll` / `dinput8.dll`, Microsoft's `d3dcompiler_47.dll` for the same bitness (unless the
  game ships its own), `AutoHDR.addon32/64` when AutoHDR is on, and a `ReShade.ini` pointing at the shared shaders.
  Launch options get `WINEDLLOVERRIDES="d3dcompiler_47=n,b;<api>=n,b"` (plus `DXVK_HDR=1` for AutoHDR).
- Direct3D 8 games use the d3d9 option: Proton's DXVK runs them on top of its Direct3D 9 (experimental).
- Non-Steam shortcuts: the exe comes from the shortcut, its launch options from Steam's `shortcuts.vdf`.
- A file of the same name that is not the plugin's (another ReShade, a mod) stops the setup instead of being
  overwritten.
- Plugin updates (Decky runs uninstall + install) keep games set up. Before uninstalling for good, use
  **Turn off ReShade in all games**.

## Decky Launch Options

With [Decky Launch Options](https://github.com/Rayekkk/DeckyLaunchOptions) installed, **Add ReShade to Decky Launch
Options** (Settings) adds a **ReShade** tab there with one choice per game (Off or a graphics API) and AutoHDR's
variable. Decky Launch Options merges it with your other `WINEDLLOVERRIDES`.

For a game Decky Launch Options runs (its Steam launch options are `~/.dlo/run %command%`), DeckyReshade puts the
files in place but never edits the launch options: Decky Launch Options would replace them with its own. Pick
ReShade → the API in Decky Launch Options for that game; the plugin reminds you when you turn it on.

## Licence

BSD 3-Clause, see [LICENSE](LICENSE). ReShade, add-ons, shaders and Microsoft's compiler are not part of this
package; see [NOTICE](NOTICE).
