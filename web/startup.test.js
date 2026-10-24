// Exercise the actual inline startup code with real stock authentication, no USB.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const OE915 = require('./oe915-core.js');
const html = readFileSync(`${__dirname}/index.html`, 'utf8');
const stock = new Uint8Array(readFileSync(`${__dirname}/CompxUpgradeBinFile.bin`));
const source = html.slice(html.indexOf('  async function fetchAttachedFirmware()'), html.indexOf('  initialize();'));

async function boot({saved, response = stock, blockedStorage = false, offline = false} = {}) {
  const nodes = new Map();
  const storage = new Map(saved ? [['stock', saved]] : []);
  const requests = [], errors = [];
  let firmware;
  const context = vm.createContext({
    OE915, Uint8Array, console,
    $: id => {
      if (!nodes.has(id)) nodes.set(id, {hidden: true, addEventListener() {}});
      return nodes.get(id);
    },
    STOCK_STORAGE: 'stock', state: {view: 'configure'},
    bindEvents() {}, initTester() {}, setView() {},
    start: value => { firmware = value; },
    showError: message => errors.push(message),
    toBase64: bytes => Buffer.from(bytes).toString('base64'),
    fromBase64: text => new Uint8Array(Buffer.from(text, 'base64')),
    localStorage: {
      getItem: key => { if (blockedStorage) throw Error('blocked'); return storage.get(key); },
      setItem: (key, value) => { if (blockedStorage) throw Error('blocked'); storage.set(key, value); },
      removeItem: key => storage.delete(key),
    },
    fetch: async url => {
      requests.push(url);
      if (offline) throw Error('offline');
      return {ok: true, arrayBuffer: async () => response};
    },
  });
  await vm.runInContext(`${source}\ninitialize()`, context);
  return {firmware, requests, errors, nodes, storage};
}

test('first visit downloads and authenticates bundled firmware without a click', async () => {
  const result = await boot();
  assert.equal(result.firmware.model().base_sha256, OE915.STOCK_SHA);
  assert.deepEqual(result.requests, ['CompxUpgradeBinFile.bin']);
  assert.ok(result.storage.has('stock'));
});

test('authenticated cached stock works offline', async () => {
  const result = await boot({saved: Buffer.from(stock).toString('base64'), offline: true});
  assert.ok(result.firmware);
  assert.equal(result.requests.length, 0);
});

test('invalid cache is discarded and replaced with authenticated bundled stock', async () => {
  const result = await boot({saved: 'invalid'});
  assert.ok(result.firmware);
  assert.equal(result.requests.length, 1);
});

test('blocked localStorage does not prevent first-visit auto-load', async () => {
  assert.ok((await boot({blockedStorage: true})).firmware);
});

for (const [name, options] of Object.entries({offline: {offline: true}, corrupt: {response: new Uint8Array(stock.length)}})) {
  test(`${name} firmware fails closed into the manual loader with an explanation`, async () => {
    const result = await boot(options);
    assert.equal(result.firmware, undefined);
    assert.equal(result.nodes.get('stock-loader').hidden, false);
    assert.equal(result.nodes.get('loading').hidden, true);
    assert.match(result.errors[0], /could not be downloaded or authenticated/);
  });
}
