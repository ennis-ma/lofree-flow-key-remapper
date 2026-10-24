// Offline tests for web/oe915-core.js. Run from the project root: node --test web/
// Parity checks call the Python reference tools; no USB device is opened.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const OE915 = require('./oe915-core.js');

const ROOT = path.join(__dirname, '..');
const STOCK = new Uint8Array(readFileSync(path.join(ROOT, 'CompxUpgradeBinFile.bin')));
const profile = (changes = [], settings = {}) => ({format: OE915.FORMAT, base_sha256: OE915.STOCK_SHA, changes, settings});
const CAPS_TO_CTRL = profile([{layer: 'win', index: 66, type: 1, value: 1}, {layer: 'mac', index: 66, type: 1, value: 1}]);
const sha = bytes => OE915.sha256Hex(bytes);

function python(code, input) {
  const result = spawnSync('python3', ['-B', '-c', code], {cwd: ROOT, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 64 << 20});
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

let firmware;
test.before(async () => { firmware = await OE915.loadStock(STOCK); });

test('factory model matches the Python reference', () => {
  const reference = python('import json, oe915_patch as k; print(json.dumps(k.model()))', null);
  const model = firmware.model();
  for (const key of ['format', 'base_sha256', 'rows', 'cols', 'layers', 'actions', 'settings', 'settings_note']) assert.deepEqual(model[key], reference[key], key);
});

test('builds are byte-identical to the Python builder', async () => {
  const profiles = [
    CAPS_TO_CTRL,
    profile(),
    profile([{layer: 'win', index: 66, type: 2, value: 57}]),
    profile([{layer: 'winfn', index: 1, type: 3, value: 233}, {layer: 'macfn', index: 35, type: 7, value: (41 << 8) | 3}, {layer: 'mac', index: 120, type: 6, value: 2}]),
    profile([{layer: 'win', index: 0, type: 0, value: 0}, {layer: 'win', index: 1, type: 1, value: 0x81}, {layer: 'winfn', index: 23, type: 5, value: 0}]),
  ];
  const reference = python('import sys, json, hashlib, oe915_patch as k\nprint(json.dumps([hashlib.sha256(k.build(p)).hexdigest() for p in json.load(sys.stdin)]))', profiles);
  for (const [i, item] of profiles.entries()) {
    const image = firmware.build(item);
    firmware.validateImage(image);
    assert.equal(await sha(image), reference[i], `profile ${i}`);
  }
});

test('Caps to Ctrl reproduces the hardware-tested image and review', async () => {
  const review = await firmware.describe(CAPS_TO_CTRL);
  assert.equal(review.sha256, '0e73b1e2db93055a809c0280bb76c07184cd35ec16c1682b2e1ee9d321fe06ac');
  const reference = python('import sys, json, oe915_patch as k\nprint(json.dumps(k.describe_changes(json.load(sys.stdin))))', CAPS_TO_CTRL);
  for (const key of ['sha256', 'size', 'changes', 'settings_changes', 'changed_payload_bytes', 'code_patches']) assert.deepEqual(review[key], reference[key], key);
});

test('stock report stream and update-entry command match the verified plan', async () => {
  const reports = firmware.reportsFor(firmware.build(profile()));
  assert.equal(reports.length, 4381);
  const stream = new Uint8Array(reports.length * 49);
  reports.forEach((report, i) => stream.set(report, i * 49));
  assert.equal(await sha(stream), OE915.REPORTS_SHA);
  const reset = firmware.resetCommand();
  assert.deepEqual([...reset], [8, 0x0d, ...new Array(14).fill(0), 0x40]);
  OE915.checkOutgoing('normal', reset);
});

test('profiles outside the safety boundary are rejected like the Python builder', () => {
  const cases = [
    [profile([{layer: 'win', index: 66, type: 1, value: 1}], {sleep: 1}), /settings must be an empty object/],
    [{...CAPS_TO_CTRL, base_sha256: '00'.repeat(32)}, /firmware base does not match/],
    [profile([{layer: 'win', index: 66, type: 1, value: 1}, {layer: 'win', index: 66, type: 1, value: 2}]), /duplicate change/],
    [profile([{layer: 'win', index: 132, type: 1, value: 1}]), /key index must be an integer/],
    [profile([{layer: 'win', index: 66, type: true, value: 1}]), /action type must be an integer/],
    [profile([{layer: 'win', index: 66, type: 5, value: 0}]), /original slot/],
    [profile([{layer: 'win', index: 66, type: 0x82, value: 4}]), /bit-7 types/],
    [profile([{layer: 'win', index: 66, type: 7, value: (4 << 8) | 0x10}]), /unsupported action/],
    [profile([{layer: 'win', index: 66, type: 3, value: 1}]), /unsupported action/],
    [profile([{layer: 'bt', index: 66, type: 1, value: 1}]), /unknown layer/],
  ];
  for (const [item, pattern] of cases) assert.throws(() => firmware.build(item), pattern);
});

test('image validation rejects code edits, missing call patch and flag changes', () => {
  const remap = firmware.build(CAPS_TO_CTRL);
  const repair = data => { // valid container checksums around an invalid edit
    const payload = data.subarray(0x2000);
    const crc = OE915.imageCrc(payload);
    data.set([crc >>> 24, crc >>> 16 & 255, crc >>> 8 & 255, crc & 255], 0x1d7 + 11);
    const head = OE915.checksum(data.subarray(0, 0x2000));
    data.set([head & 255, head >>> 8 & 255, head >>> 16 & 255, head >>> 24], 0);
    return data;
  };
  const code = remap.slice(); code[0x3000] ^= 1;
  assert.throws(() => firmware.validateImage(repair(code)), /outside allowed/);
  const unpatched = remap.slice(); unpatched.set(STOCK.subarray(0x1b06a, 0x1b06e), 0x1b06a);
  assert.throws(() => firmware.validateImage(repair(unpatched)), /retargeted to the ROM loader/);
  const flag = remap.slice(); const entry = 0x22cc0 + 1 * 4; flag[entry] ^= 0x80; flag[entry + 3] = (flag[entry + 3] - 0x80) & 255;
  assert.throws(() => firmware.validateImage(repair(flag)), /bit-7 flag changed/);
  const truncated = remap.slice(0, remap.length - 1);
  assert.throws(() => firmware.validateImage(truncated), /length differs/);
});

test('stock is found inside a vendor-updater-like wrapper and other files are refused', async () => {
  const wrapped = new Uint8Array(STOCK.length + 5000);
  wrapped.set(STOCK, 3001);
  wrapped.set([...'ComUsbUpgradeFile'].map(c => c.charCodeAt(0)), 100); // decoy marker
  assert.equal((await OE915.loadStock(wrapped)).isStock(STOCK), true);
  const tampered = STOCK.slice(); tampered[0x5000] ^= 1;
  await assert.rejects(OE915.loadStock(tampered), /not \(and does not contain\)/);
});

test('device identity requires IDs, product name and the exact vendor report layout', () => {
  const vendor = (reportId, bytes) => ({usagePage: 0xff02, usage: 2,
    inputReports: [{reportId, items: [{reportSize: 8, reportCount: bytes}]}], outputReports: [{reportId, items: [{reportSize: 8, reportCount: bytes}]}]});
  const normal = {vendorId: 0x05ac, productId: 0x024f, productName: 'Flow84@Lofree', collections: [vendor(8, 16), {usagePage: 0x0c, usage: 1}]};
  const boot = {vendorId: 0x3554, productId: 0xf800, productName: '', collections: [vendor(6, 48)]};
  assert.deepEqual(OE915.classifyDevice(normal), {mode: 'normal', ok: true, reason: ''});
  assert.equal(OE915.classifyDevice({...normal, productName: 'Compx Flow84@Lofree'}).ok, true);
  assert.deepEqual(OE915.classifyDevice(boot), {mode: 'boot', ok: true, reason: ''});
  assert.match(OE915.classifyDevice({...normal, productName: 'Magic Keyboard'}).reason, /not the Flow84/);
  assert.match(OE915.classifyDevice({...normal, collections: [vendor(8, 32)]}).reason, /layout differs/);
  assert.match(OE915.classifyDevice({...boot, collections: [vendor(6, 48), vendor(6, 48)]}).reason, /ambiguous/);
  assert.equal(OE915.classifyDevice({...boot, vendorId: 0x1234}).mode, null);
  assert.throws(() => OE915.checkOutgoing('normal', new Uint8Array(17)), /verified update entry/);
  assert.throws(() => OE915.checkOutgoing('boot', Uint8Array.of(6, 0x5a, ...new Array(47).fill(0))), /unsupported bootloader report/);
});

/* Simulated bootloader following the observed state sequence. */
function fakeBootloader(behaviour = {}) {
  const queue = [], sent = [];
  const state = (s, detail = 0) => { const r = new Uint8Array(49); r.set([6, 0x5b, 0xb5, s, detail]); return r; };
  let mismatchesLeft = behaviour.mismatches || 0, dataCount = 0;
  return {
    sent,
    async send(report) {
      OE915.checkOutgoing('boot', report);
      sent.push(report);
      if (report[1] === 0xb0) { queue.push(Uint8Array.of(0xb0, 0, 0), state(2, 0), state(2, 1)); return; }
      dataCount++;
      if (behaviour.earlySuccessAt === dataCount) { queue.push(state(136)); return; }
      if (mismatchesLeft > 0) { mismatchesLeft--; const bad = report.slice(); bad[20] ^= 1; queue.push(bad); return; }
      queue.push(report.slice());
      if (report[2] === 0xc1) queue.push(state(5), state(136, 1));
    },
    async receive(deadline) {
      if (queue.length) return queue.shift();
      throw new OE915.FlashError(Date.now() >= deadline ? 'timed out' : 'no response queued');
    },
  };
}

test('upload completes against a simulated bootloader with every echo checked', async () => {
  const reports = firmware.reportsFor(firmware.build(CAPS_TO_CTRL));
  const device = fakeBootloader({mismatches: 3}), log = [];
  await OE915.upload(device, reports, {emit: line => log.push(line)});
  assert.equal(device.sent.length, reports.length + 3); // three resends after mismatched echoes
  assert.ok(log.includes('Bootloader reported success.'));
});

test('upload fails closed on early success, repeated mismatches and error reports', async () => {
  const reports = firmware.reportsFor(firmware.build(CAPS_TO_CTRL));
  await assert.rejects(OE915.upload(fakeBootloader({earlySuccessAt: 10}), reports), /before entire image was sent/);
  await assert.rejects(OE915.upload(fakeBootloader({mismatches: 9}), reports), /echo mismatch at packet 1/);
  const error = {async send() {}, async receive() { const r = new Uint8Array(49); r.set([6, 0x5a]); return r; }};
  await assert.rejects(OE915.upload(error, reports), /bootloader error/);
});
