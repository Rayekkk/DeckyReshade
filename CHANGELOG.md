# Changelog

## 0.1.0 - unreleased

First version.

- Guided first setup: ReShade build (add-on build by default), version and AutoHDR, then one download.
- Per game from the Quick Access Menu, starting with the game that is running: ReShade on or off, the executable
  and graphics API read from the game itself (32/64-bit, DirectX 8-12, OpenGL, dinput8 as a fallback), all changeable.
- Non-Steam games (Windows shortcuts and emulators) work like Steam games.
- AutoHDR per game: the AutoHDR add-on, Pumbo's AdvancedAutoHDR and DXVK_HDR=1, with a first preset.
- RenoDX per game: the mod list from the RenoDX wiki with each mod's status (✅/🚧), matched to the library,
  installed and updated from its author's snapshot builds.
- ReShade from reshade.me: latest with automatic updates, or a fixed known version (6.3.3 to 6.8.0).
- Launch options are merged with what is already there and restored exactly when ReShade is turned off.
- Shader packages from ReShade's own list, shared by all games, with updates.
- Logs: when ReShade last started in a game and its errors, ReShade's and the plugin's log in the panel, and a report
  saved to Downloads. Warns when ReShade did not start in a game twice in a row.
- Downloaded files can be removed from the panel.
- Decky Launch Options integration: a ReShade tab (Off or an API per game, AutoHDR) can be added there, and games it
  runs keep their launch options under its control.
