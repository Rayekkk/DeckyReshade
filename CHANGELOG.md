# Changelog

All notable changes to DeckyReshade, newest first.

## [0.1.0] - Unreleased

### ✨ Added

**Plugin**
- First release.

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
- Per game, the mod list from the RenoDX wiki with each mod's status (working, in progress), matched to
  the library.
- Mods are installed and updated from their author's snapshot builds.
- The engine-wide Unreal Engine and Unity mods for the games their own lists name, with each game's
  note; ones that need steps the plugin cannot take (a build from Discord, DLSS) are links.
- An Unreal Engine game whose list asks for Engine.ini gets its HDR lines (read-only) and Upgrade Path
  Off; turning the mod off puts its Engine.ini back.

**ReShade**
- The newest version DeckyReshade has checksums for, with automatic updates, or a fixed known version
  (6.3.3 to 6.8.0).

**Launch options**
- None needed: ReShade starts by itself, and OpenGL and Direct3D 10 games get a Wine setting for their
  executable, removed again with ReShade. Works the same with Decky Launch Options.
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

### 🔧 Changed

**Updates**
- When no DeckyReshade release is published (or the repository is private), the panel says so instead
  of "Up to date".

**Panel**
- Looks and reads like the other plugins; the rows of the main page show how things stand ("1 with
  ReShade · 2 games", "ReShade 6.8.0 · add-on build").
- About stays the last row of the main page; on its page the plugin info comes first and Updates at the
  bottom ("Checking GitHub…", "Download 0.2.0", a downloaded update shown as `~/Downloads/…`).
- B goes back one page instead of closing the menu, and the row you came from is selected again.
- Picking from a list (executable, graphics API, RenoDX mod, ReShade version) or closing ReShade's log
  keeps you on the same page, and the choice is applied.
- When the plugin cannot start, the panel says "DeckyReshade unavailable" with a Try again button, and
  plugin updates are still reachable below it.
- A game page that cannot be read offers Try again; a game without a Windows executable (a native Linux
  game) says "Game not supported" and why, with nothing to retry.
- A refused change (a game, a setting, a shader package) is also shown at the top of the page until your
  next action, not only in a message.
- Removing the downloaded files asks with a warning and reports when it is done.
- RenoDX statuses are words ("Working, playable", "In progress…") instead of emoji; the mod list marks
  them with ✓ and ⚠.
- A change asked for while a download is running is answered with a message instead of being ignored.

**Shaders**
- The package list loads like any other download, shown at the top of the panel, and waits for a
  download that is already running.

**Games**
- If the plugin's list of games set up is damaged, it is restored from its last good copy.
- When it cannot be restored, the panel says so and no game is changed, so ReShade's files are never
  left behind unrecorded.

**Errors**
- Messages in the panel carry no file paths: a file that cannot be written says why (for example
  "Permission denied"), and an unexpected error shows its kind and points to the Decky log.

**Settings**
- A setting that cannot be saved (for example on a full disk) stays as it was and the panel says why.

**RenoDX**
- A mod is installed only from the GitHub release of a RenoDX author DeckyReshade knows, and only when
  the file matches the checksum GitHub publishes for it.
- The mod list is a wiki anyone can edit, so a mod from anyone else is shown with its link, to install
  by hand.

**ReShade**
- Only versions whose checksums DeckyReshade knows are installed; *Latest* is the newest of them.
- When reshade.me has a newer ReShade, the panel says so, and it arrives with the next DeckyReshade
  update.
