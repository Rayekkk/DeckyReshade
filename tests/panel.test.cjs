// SPDX-License-Identifier: BSD-3-Clause
// The panel's real TSX with controlled hooks, RPC calls and timers (DeckyKit's frontend_harness.cjs).
const test = require('node:test');
const assert = require('node:assert/strict');
const { harness, all, find, findText, settle } = require('./frontend_harness.cjs');

const ok = (state, extra = {}) => ({ ok: true, state, ...extra });
const god = { appid: 70, name: 'God of War', nonsteam: false, renodx: 'working' };
const state = (over = {}) => ({
  version: '0.1.0', home: '/home/deck',
  reshade: { installed: '6.8.0', addon: true, latest: '6.8.0', known: '6.8.0', newer_than_known: null,
    update_available: false, check_error: '',
    versions: ['6.8.0', '6.5.1'], autohdr_ready: true },
  job: { task: '', error: '' }, settings: { addon: true, version: 'latest', auto_launch_options: true },
  launch_words: { dxgi: 'WINEDLLOVERRIDES="d3dcompiler_47=n,b;dxgi=n,b"' }, autohdr_env: ['DXVK_HDR=1'],
  renodx: { count: 1, fetched_at: 0, error: '' }, scanned: true,
  games: [god, { appid: 80, name: 'Hades', nonsteam: false, renodx: 'wip' }],
  enabled: [{ appid: 70, name: 'God of War', api: 'dxgi', exe: 'GoW.exe', bits: 64, autohdr: false, renodx: 'God of War (2018)' }],
  shaders: { installed: ['standard-effects'], packages: null }, ...over,
});
const mod = { name: 'God of War (2018)', maintainer: 'Ritsu', status: 'working', note: '', files: ['64'], page: '', host: 'clshortfuse.github.io' };
const gameInfo = (over = {}) => ({
  ok: true, candidates: [{ exe: 'GoW.exe', bits: 64 }], exe: 'GoW.exe', bits: 64, detected_api: 'dxgi', detected_how: 'imports',
  anticheat: false, enabled: true, api: 'dxgi', autohdr: false,
  renodx: { installed: 'God of War (2018)', auto: 'God of War (2018)', mod },
  log: { found: false, modified: 0, version: '', errors: [], warnings: 0 }, ...over,
});

/** The panel with `running` as Steam's running game (set h.running); Steam answers launch options with -novid. */
function panel(globals = {}, options = {}) {
  const applied = [], modals = [];
  const h = harness({
    ...options,
    ui: { Router: { get MainRunningApp() { return h.running; } }, showModal: m => { modals.push(m); } },
    globals: {
      SteamClient: {
        Apps: {
          RegisterForAppDetails(appid, fn) { Promise.resolve().then(() => fn({ strLaunchOptions: '-novid' })); return { unregister() {} }; },
          SetAppLaunchOptions(appid, value) { applied.push([appid, value]); },
        },
        GameSessions: { RegisterForAppLifetimeNotifications() { return { unregister() {} }; } },
      },
      ...globals,
    },
  });
  h.running = null;
  h.applied = applied;
  h.modals = modals;
  return h;
}

const labels = (tree, type) => all(tree).filter(n => n.type === type).map(n => n.props.label);
const button = (tree, label) => all(tree).find(n => n.type === 'ButtonItem'
  && ([].concat(n.props.children).includes(label) || [].concat(n.props.children).join('') === label));
const click = (tree, label) => {
  const b = button(tree, label);
  assert.ok(b, `button ${label}`);
  assert.ok(!b.props.disabled, `${label} enabled`);
  b.props.onClick();
};

/** Open the menu afresh: the state, then the library scan every open starts. */
async function open(h, s) {
  h.remount();
  h.respond('get_state', ok(s));
  await settle();
  h.render();
  h.respond('scan_games', ok(s));
  await settle();
  return h.render();
}

test('main page: categories, and This game only while a game runs', async () => {
  const h = panel();
  let tree = await open(h, state());
  assert.deepEqual(labels(tree, 'Field'), ['Games', 'Shaders', 'ReShade version', 'Troubleshooting', 'About']);
  h.running = { appid: 80 };
  tree = await open(h, state());
  assert.equal(labels(tree, 'Field')[0], 'This game: Hades');
  // reopening the menu in game starts on the main page, not on the page left open last time
  find(tree, 'Field', 'This game: Hades').props.onActivate();
  h.render();
  tree = await open(h, state());
  assert.equal(labels(tree, 'Field')[0], 'This game: Hades');
  assert.ok(!find(tree, 'ToggleField', 'ReShade in this game'), 'opens on the main page');
});

test('Games -> a game page shows where a RenoDX mod comes from before it is installed', async () => {
  const h = panel();
  let tree = await open(h, state());
  find(tree, 'Field', 'Games').props.onActivate();
  tree = h.render();
  assert.ok(find(tree, 'Field', 'God of War'), 'the game list shows the library');
  find(tree, 'Field', 'God of War').props.onActivate();
  h.render();
  h.respond('get_game', gameInfo({ renodx: { installed: '', auto: 'God of War (2018)', mod } }));
  await settle();
  tree = h.render();
  assert.match(String(find(tree, 'ToggleField', 'Use the RenoDX mod').props.description), /clshortfuse\.github\.io/);
});

test('a game page: a failed read offers Try again, a game that cannot be supported only says why', async () => {
  const h = panel();
  let tree = await open(h, state());
  find(tree, 'Field', 'Games').props.onActivate();
  find(h.render(), 'Field', 'God of War').props.onActivate();
  h.render();
  h.fail('get_game', new Error('plugin not loaded'));
  await settle();
  tree = h.render();
  assert.ok(find(tree, 'Field', 'Game details unavailable'));
  click(tree, 'Try again');
  h.render();
  h.respond('get_game', { ok: false, unsupported: true,
    error: "No Windows executable found in this game's folder (a native Linux game?)." });
  await settle();
  tree = h.render();
  assert.match(String(find(tree, 'Field', 'Game not supported').props.description), /native Linux game/);
  assert.equal(button(tree, 'Try again'), undefined, 'retrying cannot help');
});

test('standard build: what is on can be turned off, and a change drops what cannot run', async () => {
  const h = panel();
  h.running = { appid: 80 };
  const standard = state({ reshade: { ...state().reshade, addon: false }, settings: { ...state().settings, addon: false } });
  let tree = await open(h, standard);
  find(tree, 'Field', 'This game: Hades').props.onActivate();
  h.render();
  h.respond('get_game', gameInfo({ autohdr: true }));
  await settle();
  tree = h.render();
  assert.equal(find(tree, 'ToggleField', 'Use the RenoDX mod').props.disabled, false);
  assert.equal(find(tree, 'ToggleField', 'AutoHDR').props.disabled, false);
  find(tree, 'DropdownItem', 'Graphics API').props.onChange({ data: 'd3d11' });
  await settle();
  const enable = h.calls.find(c => c.name === 'enable_game');
  assert.ok(enable, 'changing the API sets the game up again');
  assert.deepEqual(enable.args.slice(0, 6), [80, 'GoW.exe', 'd3d11', false, '', '-novid']);
  h.respond('enable_game', { ok: true, launch_options: 'WINEDLLOVERRIDES=x %command% -novid', dlo: false });
  await settle();
  assert.deepEqual(h.applied, [[80, 'WINEDLLOVERRIDES=x %command% -novid']]);
});

test('a refused change keeps the launch options the backend restored, and says why', async () => {
  const h = panel();
  h.running = { appid: 80 };
  let tree = await open(h, state());
  find(tree, 'Field', 'This game: Hades').props.onActivate();
  h.render();
  h.respond('get_game', gameInfo({ enabled: false, renodx: { installed: '', auto: '', mod: null } }));
  await settle();
  find(h.render(), 'ToggleField', 'ReShade in this game').props.onChange(true);
  await settle();
  h.respond('enable_game', { ok: false, error: 'dxgi.dll already exists in the game folder', launch_options: '-novid' });
  await settle();
  assert.deepEqual(h.applied, [], 'unchanged options are not written');
  assert.deepEqual(h.toasts.map(t => t.body), ['dxgi.dll already exists in the game folder']);
  await settle();
  tree = h.render();
  assert.ok(find(tree, 'Field', 'Could not complete'), 'also on the page, until the next action (UI.md §5)');
  find(tree, 'ToggleField', 'ReShade in this game').props.onChange(true);
  tree = h.render();
  assert.equal(find(tree, 'Field', 'Could not complete'), undefined, 'the next action clears it');
});

test('setup wizard: a failed call goes back to the summary; a finished setup shows how to use it', async () => {
  const w = panel();
  let tree = await open(w, state({ reshade: { ...state().reshade, installed: null } }));
  click(tree, 'Start setup'); tree = w.render();
  click(tree, 'With add-ons'); tree = w.render();
  click(tree, 'Next'); tree = w.render();
  assert.ok(find(tree, 'ToggleField', 'Download AutoHDR'), 'AutoHDR step for the add-on build');
  click(tree, 'Next'); tree = w.render();
  click(tree, 'Download and set up'); w.render();
  assert.deepEqual(w.calls.find(c => c.name === 'setup').args, [true, 'latest', true]);
  w.fail('setup', new Error('backend restarting'));
  await settle();
  w.render(); tree = w.render();
  assert.deepEqual(w.toasts.map(t => t.body), ['backend restarting']);
  click(tree, 'Download and set up');  // back on the summary, enabled: not stuck on "Starting…"
  w.render();
  w.respond('setup', ok(state()));
  await settle();
  w.render(); tree = w.render();
  assert.ok(find(tree, 'Field', 'How to use it'), 'the how-to page after setup');
  click(tree, 'Done'); tree = w.render();
  assert.equal(labels(tree, 'Field')[0], 'Games');
});

test('a failed job is shown once, in the job box, and can be dismissed', async () => {
  const h = panel();
  let tree = await open(h, state());
  find(tree, 'Field', 'ReShade version').props.onActivate();
  tree = h.render();
  click(tree, 'Check for a new ReShade now');
  const failed = state({ job: { task: '', error: 'reshade.me answered HTTP 503' } });
  h.respond('check_reshade', { ok: false, error: 'reshade.me answered HTTP 503', state: failed });
  await settle();
  tree = h.render();
  assert.deepEqual(h.toasts, [], 'not twice: the box shows it');
  assert.ok(findText(tree, 'HTTP 503'));
  click(tree, 'Dismiss');
  assert.equal(findText(h.render(), 'HTTP 503'), undefined);
});

test('no backend: the panel says so instead of spinning forever, can try again and still update', async () => {
  const h = panel();
  assert.ok(find(h.render(), 'Spinner'), 'a spinner while the first state loads');
  h.fail('get_state', new Error('plugin not loaded'));
  await settle();
  let tree = h.render();
  assert.ok(findText(tree, 'plugin not loaded'));
  assert.ok(find(tree, 'Field', 'DeckyReshade unavailable'));
  assert.ok(button(tree, 'Check for updates'), 'Updates stays reachable');
  assert.ok(find(tree, 'Field', 'Installed version 0.0.0-test'), 'the version from the build');
  click(tree, 'Try again');
  assert.ok(find(h.render(), 'Spinner'));
  h.respond('get_state', ok(state()));
  await settle();
  assert.deepEqual(labels(h.render(), 'Field'), ['Games', 'Shaders', 'ReShade version', 'Troubleshooting', 'About']);
});

test('shaders: the package list loads once, after a running job', async () => {
  const h = panel();
  let tree = await open(h, state({ job: { task: 'Updating shaders…', error: '' } }));
  find(tree, 'Field', 'Shaders').props.onActivate();
  h.render();
  assert.equal(h.calls.filter(c => c.name === 'load_packages').length, 0, 'waits for the job');
  h.advance(700);  // the panel polls while a job runs
  h.respond('get_state', ok(state()));
  await settle();
  h.render(); h.render();
  assert.equal(h.calls.filter(c => c.name === 'load_packages').length, 1);
  h.respond('load_packages', ok(state({ shaders: { installed: ['standard-effects'], packages: [
    { id: 'standard-effects', name: 'Standard effects', description: '', default: true, required: false }] } })));
  await settle();
  assert.ok(find(h.render(), 'ToggleField', 'Standard effects').props.checked);
  h.render();
  assert.equal(h.calls.filter(c => c.name === 'load_packages').length, 1, 'once');
});

test('a game Decky Launch Options runs: its ReShade tab is offered once', async () => {
  const h = panel({ hasDeckyLaunchOptions: true });
  h.running = { appid: 80 };
  let tree = await open(h, state());
  find(tree, 'Field', 'This game: Hades').props.onActivate();
  h.render();
  h.respond('get_game', gameInfo({ enabled: false, renodx: { installed: '', auto: '', mod: null } }));
  await settle();
  find(h.render(), 'ToggleField', 'ReShade in this game').props.onChange(true);
  await settle();
  const enable = h.calls.find(c => c.name === 'enable_game');
  assert.equal(enable.args[6], true, 'the backend is told DLO is there');
  h.respond('enable_game', { ok: true, launch_options: '-novid', dlo: true });
  await settle();
  assert.equal(h.events.length, 1);
  assert.equal(h.events[0].type, 'dlo-add-launch-options');
  assert.deepEqual(h.events[0].detail.map(o => o.id).slice(0, 2), ['deckyreshade-off', 'deckyreshade-dxgi']);
});

test('About is the last row; its page has the plugin info first and Updates last', async () => {
  const h = panel();
  let tree = await open(h, state());
  assert.equal(labels(tree, 'Field').at(-1), 'About');
  assert.equal(find(tree, 'Field', 'About').props.description, 'Version 0.1.0 · updates');
  find(tree, 'Field', 'About').props.onActivate();
  tree = h.render();
  const sections = all(tree).filter(n => n.type === 'PanelSection').map(n => n.props.title);
  assert.deepEqual(sections, ['About', 'DeckyReshade', "Rayek's store", 'Updates']);
  assert.ok(find(tree, 'Field', 'Version 0.1.0'));
  assert.ok(find(tree, 'Field', 'Downloaded on your device'));
});

test('plugin updates: no published release is not "up to date"; a newer one can be downloaded', async () => {
  const h = panel();
  let tree = await open(h, state());
  find(tree, 'Field', 'About').props.onActivate();
  click(h.render(), 'Check for updates');
  h.respond('check_for_updates', { ok: true, current_version: '0.1.0', update_available: false, download_available: false,
    no_release: true, message: 'No release has been published yet (or the repository is private).' });
  await settle();
  tree = h.render();
  assert.ok(find(tree, 'Field', 'No public release yet'));
  assert.equal(find(tree, 'Field', 'Up to date'), undefined);
  click(tree, 'Check for updates');
  h.respond('check_for_updates', { ok: true, current_version: '0.1.0', latest_version: '0.2.0', update_available: true,
    download_available: true, asset_name: 'DeckyReshade-0.2.0.zip' });
  await settle();
  click(h.render(), 'Download 0.2.0');
  assert.deepEqual(h.calls.find(c => c.name === 'perform_update').args, ['0.2.0']);
  h.respond('perform_update', { ok: true, path: '/home/deck/Downloads/DeckyReshade-0.2.0.zip', version: '0.2.0' });
  await settle();
  tree = h.render();
  assert.ok(find(tree, 'Field', '0.2.0 downloaded'));
  assert.ok(findText(tree, '~/Downloads/DeckyReshade-0.2.0.zip'), 'the path inside home as ~/');
});

test('B and the back button go back one page, and the row that opened the page takes the focus again', async () => {
  const h = panel({}, { keep: ['SectionLink'] });
  let tree = await open(h, state());
  const row = title => all(tree).find(n => n.type?.name === 'SectionLink' && n.props.title === title);
  row('Games').props.onOpen();
  tree = h.render();
  row('Hades').props.onOpen();
  tree = h.render();
  const shell = all(tree).find(n => n.type === 'Focusable' && n.props.onCancelButton);
  let stopped = 0;
  shell.props.onCancelButton({ preventDefault() {}, stopPropagation() { stopped++; } });
  assert.equal(stopped, 1, 'B does not close the menu');
  tree = h.render();
  assert.equal(row('Hades').props.focus, true, 'back on Games, on the game');
  assert.equal(row('God of War').props.focus, false);
  click(tree, '‹ ReShade');
  tree = h.render();
  assert.equal(row('Games').props.focus, true, 'back on the main page, on Games');
  tree = await open(h, state());
  assert.equal(row('Games').props.focus, false, 'reopening the menu moves no focus');
});

test('Remove downloaded files asks first, as a destructive action, and reports the outcome', async () => {
  const h = panel();
  let tree = await open(h, state({ enabled: [] }));
  find(tree, 'Field', 'Troubleshooting').props.onActivate();
  click(h.render(), 'Remove downloaded files');
  assert.equal(h.modals.length, 1);
  const dialog = h.modals[0].props;
  assert.equal(dialog.strTitle, 'Remove downloaded files?');
  assert.equal(dialog.strOKButtonText, 'Remove');
  assert.equal(dialog.strCancelButtonText, 'Cancel');
  assert.equal(dialog.bDestructiveWarning, true);
  assert.equal(h.calls.filter(c => c.name === 'remove_data').length, 0, 'nothing before OK');
  dialog.onOK();
  await settle();
  h.respond('remove_data', ok(state({ enabled: [], reshade: { ...state().reshade, installed: null } })));
  await settle();
  assert.deepEqual(h.toasts.map(t => t.title), ['DeckyReshade']);
  assert.match(h.toasts[0].body, /removed/);
  assert.ok(button(h.render(), 'Start setup'), 'the setup wizard again');
});

test('a newer ReShade without known checksums is announced, never offered', async () => {
  const h = panel();
  const newer = state({ reshade: { ...state().reshade, latest: '6.9.0', newer_than_known: '6.9.0' } });
  let tree = await open(h, newer);
  find(tree, 'Field', 'ReShade version').props.onActivate();
  tree = h.render();
  const notice = findText(tree, ' is out. It comes with the next DeckyReshade update');
  assert.ok(notice && notice.props.children.includes('6.9.0'));
  assert.equal(button(tree, 'Update to ReShade 6.9.0'), undefined);
  const update = state({ reshade: { ...state().reshade, installed: '6.7.3', update_available: true } });
  tree = await open(h, update);
  find(tree, 'Field', 'ReShade version').props.onActivate();
  assert.ok(button(h.render(), 'Update to ReShade 6.8.0'), 'the newest version with known checksums');
});
