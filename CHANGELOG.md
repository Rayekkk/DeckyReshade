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

**Non-Steam games**
- Windows shortcuts and emulators work like Steam games.

**AutoHDR**
- Per game, the AutoHDR add-on, Pumbo's AdvancedAutoHDR and DXVK_HDR=1, with a first preset.

**RenoDX**
- Per game, the mod list from the RenoDX wiki with each mod's status (working, in progress), matched to
  the library.
- Mods are installed and updated from their author's snapshot builds.

**ReShade**
- The newest version DeckyReshade has checksums for, with automatic updates, or a fixed known version
  (6.3.3 to 6.8.0).

**Launch options**
- Merged with what is already there and restored exactly when ReShade is turned off.

**Shaders**
- Packages from ReShade's own list, shared by all games, with updates.

**Logs**
- When ReShade last started in a game and its errors, ReShade's and the plugin's log in the panel, and a
  report saved to Downloads.
- A warning when ReShade did not start in a game twice in a row.

**Downloads**
- Downloaded files can be removed from the panel.

**Decky Launch Options**
- A ReShade tab (Off or an API per game, AutoHDR) can be added there, and games it runs
  keep their launch options under its control.

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
