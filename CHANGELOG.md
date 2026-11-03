# Changelog

All notable changes to DeckyReshade, newest first.

## [1.0.0] - 2026-11-03

### ✨ Added

**Plugin**
- Initial release, tested on Lenovo Legion Go 2 with SteamOS 3.9.5.

**Setup**
- A guided first setup: ReShade build (add-on build by default), version and AutoHDR, then one download.

**Games**
- Set up per game from the Quick Access Menu, starting with the game that is running: ReShade on or off.
- The executable and graphics API are read from the game itself (32/64-bit, DirectX 8-12, OpenGL,
  dinput8 as a fallback) and can all be changed.
- A game moved to another library is followed there, and one that was uninstalled leaves the list by
  itself; a game on an SD card that is out stays set up.
- A game that ships a shader compiler too old for DirectX 12 effects (Windows 8.1's) gets a newer one;
  the game's own is kept beside it and put back when ReShade is turned off.

**Non-Steam games**
- Windows shortcuts and emulators work like Steam games.

**AutoHDR**
- Per game, the AutoHDR add-on (switched on for the game) and Pumbo's AdvancedAutoHDR, with a first
  preset; a start that stayed in SDR is shown on the game's page and said once.
- The HDR part of a game's page says when HDR is off in Steam, with a button to the setting.

**RenoDX**
- Per game, the mod list from the RenoDX wiki with each mod's status and note, matched to the library;
  a mod is installed only from a known author's GitHub release that matches GitHub's checksum.
- The engine-wide Unreal Engine and Unity mods for the games their own lists name; ones that need steps
  the plugin cannot take (a build from Discord, DLSS) are links.
- An Unreal Engine game whose list asks for Engine.ini gets its HDR lines (read-only) and Upgrade Path
  Off; turning the mod off puts its Engine.ini back.

**ReShade**
- The newest version DeckyReshade has checksums for, with automatic updates, or a fixed known version
  (6.3.3 to 6.8.0); a newer ReShade on reshade.me is announced and comes with a plugin update.

**Launch options**
- None needed: ReShade starts by itself, and OpenGL games (and Direct3D 10 when picked by hand) get a
  Wine setting for their executable, removed again with ReShade.
- **Use launch options** in Settings leaves Wine alone instead: turning a game on copies its launch options
  line, and the game's page has a Copy button.

**Shaders**
- Packages from ReShade's own list, shared by all games, with updates.

**Logs**
- When ReShade last started in a game and its errors, ReShade's and the plugin's log in the panel, and a
  report saved to Downloads.
- A warning when ReShade did not start in a game twice in a row.

**Downloads**
- Downloaded files can be removed from the panel.

**About**
- **Use Rayek's store** makes Rayek's store Decky's store channel after you confirm, so Decky's Store tab
  lists Rayek's plugins and offers their updates.
