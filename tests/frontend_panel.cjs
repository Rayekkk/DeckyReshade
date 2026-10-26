// SPDX-License-Identifier: BSD-3-Clause
// Execute the actual TSX with controlled hooks, RPC completion and timers (same approach as FSR4 Injector and the
// Companion plugins). Pages swap whole components, so hook state belongs to a component (its place in the tree and
// its key), not to a running hook count.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), ts = require(path.join(root, 'node_modules/typescript'));
const settle = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };

function harness() {
  const slots = new Map(), effects = new Map(), pending = [], calls = [], toasts = [], applied = [], events = [];
  const router = { MainRunningApp: null };
  const window = { hasDeckyLaunchOptions: false, dispatchEvent: e => events.push(e) };
  const frames = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const slot = () => { const f = frames[frames.length - 1]; return `${f.id}:${f.cursor++}`; };
  const hooks = {
    useState(value) { const k = slot(); if (!slots.has(k)) slots.set(k, typeof value === 'function' ? value() : value);
      return [slots.get(k), v => slots.set(k, typeof v === 'function' ? v(slots.get(k)) : v)]; },
    useRef(value) { const k = slot(); if (!slots.has(k)) slots.set(k, { current: value }); return slots.get(k); },
    useCallback(fn, deps) { const k = slot(), old = slots.get(k); if (!old || !same(old.deps, deps)) slots.set(k, { fn, deps });
      return slots.get(k).fn; },
    useEffect(fn, deps) { const k = slot(), old = effects.get(k); if (!old || !same(old.deps, deps)) pending.push(() => {
      old?.cleanup?.(); effects.set(k, { deps, cleanup: fn() });
    }); },
  };
  // A function component runs where it is created, in a frame named after its parent, its type and its key.
  const call = (type, props, key) => {
    const parent = frames[frames.length - 1];
    const name = type.name || 'anon', count = parent.children[name] = (parent.children[name] ?? 0) + 1;
    frames.push({ id: `${parent.id}/${name}#${props?.id ?? key ?? count}`, cursor: 0, children: {} });
    try { return type(props ?? {}); } finally { frames.pop(); }
  };
  const el = (type, props, key) => (typeof type === 'function' ? call(type, props, key) : { type, props });
  const jsx = { jsx: el, jsxs: el, Fragment: 'Fragment' };
  const callable = name => (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject, settled: false }));
  const SteamClient = {
    GameSessions: { RegisterForAppLifetimeNotifications() { return { unregister() {} }; } },
    Apps: {
      RegisterForAppDetails(appid, fn) { Promise.resolve().then(() => fn({ strLaunchOptions: '-novid' })); return { unregister() {} }; },
      SetAppLaunchOptions(appid, value) { applied.push([appid, value]); },
    },
  };
  const source = fs.readFileSync(path.join(root, 'src', 'index.tsx'), 'utf8') + '\nexport { Content };';
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(output, {
    module: mod, exports: mod.exports, console, SteamClient, setTimeout, clearTimeout, setInterval, clearInterval, window,
    localStorage: { getItem: () => null, setItem() {} },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    require(name) {
      if (name === 'react') return hooks;
      if (name === 'react/jsx-runtime') return jsx;
      if (name === '@decky/api') return { callable, definePlugin: fn => fn, toaster: { toast: v => toasts.push(v) } };
      if (name === '@decky/ui') return new Proxy({}, { get: (object, key) => key === 'Router' ? router : key === 'staticClasses' ? {} : key });
      throw Error(name);
    },
  });
  const plugin = mod.exports;
  const render = () => {
    frames.length = 0;
    frames.push({ id: 'Content', cursor: 0, children: {} });
    const tree = plugin.Content({});
    frames.pop();
    pending.splice(0).forEach(fn => fn());
    return tree;
  };
  return {
    render, calls, toasts, applied, router, window,
    // The Quick Access Menu mounts the panel afresh on every open.
    remount() { for (const e of effects.values()) e.cleanup?.(); effects.clear(); slots.clear(); pending.length = 0; return render(); },
    async respond(name, value) {
      const c = calls.find(x => x.name === name && !x.settled); assert.ok(c, `pending ${name}`);
      c.settled = true; c.resolve(value); await settle(); return c;
    },
    pending(name) { return calls.some(c => c.name === name && !c.settled); },
  };
}

function all(node, out = []) {
  if (Array.isArray(node)) node.forEach(n => all(n, out));
  else if (node && typeof node === 'object') { out.push(node); all(node.props?.children, out); all(node.props?.description, out); }
  return out;
}
const find = (tree, type, label) => all(tree).find(n => n.type === type && n.props?.label === label);
const labels = (tree, type) => all(tree).filter(n => n.type === type).map(n => n.props.label);

const god = { appid: 70, name: 'God of War', nonsteam: false, renodx: 'working' };
const state = (over = {}) => ({
  version: '0.1.0',
  reshade: { installed: '6.8.0', addon: true, latest: '6.8.0', update_available: false, check_error: '',
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

async function open(h, s) {
  h.remount();
  await h.respond('get_state', s);
  h.render();
  await h.respond('scan_games', s);
  return h.render();
}

(async () => {
  const h = harness();

  // The main page: categories, and This game only while a game runs.
  let tree = await open(h, state());
  assert.deepEqual(labels(tree, 'Field'), ['Games', 'Shaders', 'ReShade version', 'Troubleshooting', 'About']);
  h.router.MainRunningApp = { appid: 80 };
  tree = await open(h, state());
  assert.equal(labels(tree, 'Field')[0], 'This game: Hades');

  // Games → a game's page, with the RenoDX source shown before it is installed.
  find(tree, 'Field', 'Games').props.onActivate();
  tree = h.render();
  assert.ok(find(tree, 'Field', 'God of War'), 'the game list shows the library');
  find(tree, 'Field', 'God of War').props.onActivate();
  h.render();
  await h.respond('get_game', gameInfo({ renodx: { installed: '', auto: 'God of War (2018)', mod } }));
  tree = h.render();
  assert.match(String(find(tree, 'ToggleField', 'Use the RenoDX mod').props.description), /clshortfuse\.github\.io/);

  // Reopening the menu in game starts on the main page with This game, not on the page left open last time.
  tree = await open(h, state());
  assert.equal(labels(tree, 'Field')[0], 'This game: Hades');
  assert.ok(!find(tree, 'ToggleField', 'ReShade in this game'), 'opens on the main page');

  // Standard build: RenoDX and AutoHDR that are on can still be turned off, and a change drops what cannot run.
  const standard = state({ reshade: { ...state().reshade, addon: false }, settings: { ...state().settings, addon: false } });
  tree = await open(h, standard);
  find(tree, 'Field', 'This game: Hades').props.onActivate();
  h.render();
  await h.respond('get_game', gameInfo({ autohdr: true }));
  tree = h.render();
  assert.equal(find(tree, 'ToggleField', 'Use the RenoDX mod').props.disabled, false);
  assert.equal(find(tree, 'ToggleField', 'AutoHDR').props.disabled, false);
  find(tree, 'DropdownItem', 'Graphics API').props.onChange({ data: 'd3d11' });
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  const enable = h.calls.find(c => c.name === 'enable_game');
  assert.ok(enable, 'changing the API sets the game up again');
  assert.deepEqual(enable.args.slice(0, 5), [80, 'GoW.exe', 'd3d11', false, '']);

  // First-run wizard: a failed call goes back to the summary to try again; a finished setup shows how to use it,
  // then the main page.
  const w = harness();
  const fresh = state({ reshade: { ...state().reshade, installed: null } });
  const click = (t, label) => {
    const b = all(t).find(n => n.type === 'ButtonItem' && [].concat(n.props.children).includes(label));
    assert.ok(b, `button ${label}`); assert.ok(!b.props.disabled, `${label} enabled`); b.props.onClick();
  };
  tree = await open(w, fresh);
  click(tree, 'Start setup'); tree = w.render();
  click(tree, 'With add-ons'); tree = w.render();
  click(tree, 'Next'); tree = w.render();
  assert.ok(find(tree, 'ToggleField', 'Download AutoHDR'), 'AutoHDR step for the add-on build');
  click(tree, 'Next'); tree = w.render();
  click(tree, 'Download and set up'); w.render();
  const failed = w.calls.find(c => c.name === 'setup');
  assert.deepEqual(failed.args, [true, 'latest', true]);
  failed.settled = true; failed.reject(new Error('backend restarting')); await settle();
  w.render(); tree = w.render();
  click(tree, 'Download and set up');  // back on the summary, enabled: not stuck on "Starting…"
  w.render();
  await w.respond('setup', state());
  w.render(); tree = w.render();
  assert.ok(find(tree, 'Field', 'How to use it'), 'the how-to page after setup');
  click(tree, 'Done'); tree = w.render();
  assert.equal(labels(tree, 'Field')[0], 'Games');

  console.log('Frontend panel checks passed: main page, This game, game list and page, reopening, standard build, setup wizard.');
})().catch(e => { console.error(e); process.exit(1); });
