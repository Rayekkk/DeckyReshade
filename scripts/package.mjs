#!/usr/bin/env node
/**
 * Builds the release zip that Decky's "Install Plugin from ZIP" accepts.
 *
 * Same approach as FSR4Injector: files are staged into build/<PLUGIN_DIR_NAME>/, timestamps are fixed so the same
 * files give the same archive, and zipping goes through 7-Zip on Windows or `zip` elsewhere (Compress-Archive writes
 * backslash separators that break extraction on Linux).
 *
 * No ReShade or Microsoft binary may end up in the archive: the user's device fetches them (see reshade_release.py).
 */

import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, utimesSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(repoRoot, "plugin.json"), "utf8"));
const PLUGIN_DIR_NAME = "DeckyReshade";
const version = manifest.version;

const buildDir = join(repoRoot, "build");
const stageDir = join(buildDir, PLUGIN_DIR_NAME);
const zipPath = join(repoRoot, `${PLUGIN_DIR_NAME}-${version}.zip`);
const pendingZip = join(buildDir, "release.zip");

/** Runtime payload plus what the licences require. */
const CONTENTS = [
  "main.py",
  ...readdirSync(repoRoot).filter(name => /^reshade_\w+\.py$/.test(name)).sort(),
  "plugin.json",
  "package.json",
  "README.md",
  "CHANGELOG.md",
  "LICENSE",
  "NOTICE",
  "dist",
];
const REQUIRED_IN_ZIP = ["main.py", "reshade_diag.py", "reshade_games.py", "reshade_install.py", "reshade_net.py", "reshade_release.py",
  "reshade_renodx.py", "reshade_shaders.py", "reshade_updates.py", "plugin.json", "dist/index.js", "LICENSE", "NOTICE",
  "third_party/decky-api/LICENSE"];
const FORBIDDEN_IN_ZIP = [/\.dll$/i, /\.exe$/i, /__pycache__/, /node_modules/];

function fail(message) {
  console.error(`error: ${message}`);
  process.exit(1);
}

if (!existsSync(join(repoRoot, "dist", "index.js"))) fail("dist/index.js is missing - run `npm run build` first");
const pkgVersion = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8")).version;
if (pkgVersion !== version) fail(`version mismatch: plugin.json=${version} package.json=${pkgVersion}`);

rmSync(buildDir, { recursive: true, force: true });
mkdirSync(stageDir, { recursive: true });

for (const entry of CONTENTS) {
  const from = join(repoRoot, entry);
  if (!existsSync(from)) fail(`required file missing: ${entry}`);
  mkdirSync(dirname(join(stageDir, entry)), { recursive: true });
  cpSync(from, join(stageDir, entry), {
    recursive: true,
    filter: src => !["__pycache__", ".DS_Store", "node_modules"].includes(basename(src)) && !src.endsWith(".pyc"),
  });
}

// @decky/api is compiled into dist/index.js; ship its licence and source with it.
const apiDir = join(repoRoot, "node_modules", "@decky", "api");
const apiStage = join(stageDir, "third_party", "decky-api");
mkdirSync(apiStage, { recursive: true });
for (const entry of ["LICENSE", "package.json", "dist", "src", "README.md"]) {
  if (existsSync(join(apiDir, entry))) cpSync(join(apiDir, entry), join(apiStage, entry), { recursive: true });
  else if (entry !== "README.md") fail(`@decky/api ${entry} is missing`);
}

const FIXED_TIME = new Date(2000, 0, 1);
const entries = [PLUGIN_DIR_NAME, ...readdirSync(stageDir, { recursive: true })
  .map(path => `${PLUGIN_DIR_NAME}/${path.replaceAll("\\", "/")}`)].sort();
for (const entry of entries) utimesSync(join(buildDir, entry), FIXED_TIME, FIXED_TIME);

const sevenZipPath = ["C:\\Program Files\\7-Zip\\7z.exe", "C:\\Program Files (x86)\\7-Zip\\7z.exe"].find(existsSync);
try {
  if (sevenZipPath) {
    execFileSync(sevenZipPath, ["a", "-tzip", "-mx=9", "-mtm=off", pendingZip, PLUGIN_DIR_NAME],
      { cwd: buildDir, stdio: "ignore" });
  } else {
    execFileSync("zip", ["-X", "-9", "-q", pendingZip, "-@"],
      { cwd: buildDir, input: entries.join("\n"), stdio: ["pipe", "inherit", "inherit"] });
  }
} catch (err) {
  fail(sevenZipPath ? `7-Zip failed: ${err.message}` : `no zip tool found (install 7-Zip or zip): ${err.message}`);
}

// Check the archive itself, not the staging folder: what users get is what matters.
const listing = (sevenZipPath
  ? execFileSync(sevenZipPath, ["l", "-slt", pendingZip], { encoding: "utf8" })
      .split(/\r?\n/).filter(l => l.startsWith("Path = ")).map(l => l.slice(7)).slice(1)
  : execFileSync("unzip", ["-Z1", pendingZip], { encoding: "utf8" }).split(/\r?\n/))
  .map(p => p.replaceAll("\\", "/")).filter(Boolean);
for (const path of REQUIRED_IN_ZIP)
  if (!listing.includes(`${PLUGIN_DIR_NAME}/${path}`)) fail(`archive is missing ${path}`);
for (const path of listing)
  if (path !== PLUGIN_DIR_NAME && !path.startsWith(`${PLUGIN_DIR_NAME}/`)) fail(`archive entry outside the plugin folder: ${path}`);
for (const path of listing)
  for (const rule of FORBIDDEN_IN_ZIP) if (rule.test(path)) fail(`archive must not contain ${path}`);

renameSync(pendingZip, zipPath);
rmSync(buildDir, { recursive: true, force: true });
console.log(`packaged v${version} (${listing.length} entries) -> ${zipPath}`);
