/* OE915 (Lofree Flow84) v2.52 firmware core for the standalone web remapper.
 *
 * JavaScript port of oe915_fw.py (container + HID report plan), oe915_patch.py
 * (factory model, profile validation, constrained keymap builds, image
 * validation) and the transport-independent parts of oe915_linux.py (boot
 * response decoding, upload state machine, outgoing-report guards).
 * web/oe915-core.test.js checks byte-for-byte parity with the Python tools.
 *
 * No device access happens here. The page supplies a transport (WebHID) and
 * the user's own copy of the vendor firmware; nothing is fetched or bundled.
 * Loads as a classic browser script (window.OE915) or a CommonJS module.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.OE915 = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const FORMAT = 'oe915-remap-v1';
  const STOCK_SHA = '7c061d9ce66c0b45e7d9f02e5d467af78cd537a88529b90fccb5dbf6dbccc7de';
  const REPORTS_SHA = 'e0773c09ef14ad671ec57e332a6fae445b7df7510c0db315cc55995948481d7c';
  const STOCK_SIZE = 148336;
  const HEAD_REGION = 0x2000;
  const BASE = HEAD_REGION;
  const PREPARE = 0x01d7;
  const DOWNLOAD = 0x0217;
  const RESET_COMMAND = 0x0199;
  const LAYERS = {win: 0x22cc0, winfn: 0x22ed0, mac: 0x230e0, macfn: 0x232f0};
  const LAYER_IDS = Object.keys(LAYERS);
  const LAYER_LABELS = {win: 'Windows', winfn: 'Windows + Fn', mac: 'Mac', macfn: 'Mac + Fn'};
  const ROWS = 6, COLS = 22, ENTRY_COUNT = ROWS * COLS;
  const MODE_SWITCH_CALL = 0x1b06a;
  const EEPROM_KEYMAP_LOADER = 0x19710;
  const ROM_KEYMAP_LOADER = 0x196cc;
  const SUPPORTED_TYPES = [0, 1, 2, 3, 6, 7];
  const NORMAL_IDS = [0x05ac, 0x024f];
  const BOOT_IDS = [0x3554, 0xf800];
  const NORMAL_PRODUCT_NAMES = ['Flow84@Lofree', 'Compx Flow84@Lofree'];
  const VENDOR_USAGE_PAGE = 0xff02;

  const MOD_LABELS = {1: 'Left Ctrl', 2: 'Left Shift', 4: 'Left Alt', 8: 'Left GUI / Command',
    16: 'Right Ctrl', 32: 'Right Shift', 64: 'Right Alt', 128: 'Right GUI / Command'};
  const KEY_LABELS = new Map(Object.entries({
    4: 'A', 5: 'B', 6: 'C', 7: 'D', 8: 'E', 9: 'F', 10: 'G', 11: 'H', 12: 'I', 13: 'J', 14: 'K', 15: 'L', 16: 'M',
    17: 'N', 18: 'O', 19: 'P', 20: 'Q', 21: 'R', 22: 'S', 23: 'T', 24: 'U', 25: 'V', 26: 'W', 27: 'X', 28: 'Y', 29: 'Z',
    30: '1', 31: '2', 32: '3', 33: '4', 34: '5', 35: '6', 36: '7', 37: '8', 38: '9', 39: '0',
    40: 'Enter', 41: 'Escape', 42: 'Backspace', 43: 'Tab', 44: 'Space', 45: 'Minus (-)', 46: 'Equal (=)',
    47: 'Left bracket ([)', 48: 'Right bracket (])', 49: 'Backslash', 50: 'Non-US # / ~', 51: 'Semicolon',
    52: 'Quote', 53: 'Grave (`)', 54: 'Comma', 55: 'Period (.)', 56: 'Slash', 57: 'Caps Lock',
    58: 'F1', 59: 'F2', 60: 'F3', 61: 'F4', 62: 'F5', 63: 'F6', 64: 'F7', 65: 'F8', 66: 'F9', 67: 'F10', 68: 'F11', 69: 'F12',
    70: 'Print Screen', 71: 'Scroll Lock', 72: 'Pause', 73: 'Insert', 74: 'Home', 75: 'Page Up', 76: 'Delete',
    77: 'End', 78: 'Page Down', 79: 'Right', 80: 'Left', 81: 'Down', 82: 'Up', 83: 'Num Lock',
    84: 'Kp Divide', 85: 'Kp Multiply', 86: 'Kp Minus', 87: 'Kp Plus', 88: 'Kp Enter',
    89: 'Kp 1', 90: 'Kp 2', 91: 'Kp 3', 92: 'Kp 4', 93: 'Kp 5', 94: 'Kp 6', 95: 'Kp 7', 96: 'Kp 8', 97: 'Kp 9', 98: 'Kp 0',
    99: 'Kp Dot', 100: 'Non-US backslash', 101: 'Application / Menu', 133: 'Kp Comma',
    135: 'International 1 (Ro)', 136: 'International 2 (Katakana/Hiragana)', 137: 'International 3 (Yen)',
    138: 'International 4 (Henkan)', 139: 'International 5 (Muhenkan)', 144: 'Language 1 (Hangul)', 145: 'Language 2 (Hanja)',
  }).map(([value, label]) => [Number(value), label]));
  const MEDIA_LABELS = new Map(Object.entries({
    111: 'Display brightness up', 112: 'Display brightness down', 181: 'Next track', 182: 'Previous track',
    205: 'Play / Pause', 226: 'Mute', 233: 'Volume up', 234: 'Volume down', 402: 'Calculator', 545: 'Search',
  }).map(([value, label]) => [Number(value), label]));
  const LIMITATIONS = [
    'This is the factory 6 × 22 full-size-compatible table, including unused and other-keyboard slots; physical Flow84 wiring has not been fully recovered.',
    'Every edit requires a full firmware reflash, not live VIA-style configuration. The current keyboard mapping is not read back.',
    'Remapped builds change one call so a Win/Mac switch reloads the flashed keymap instead of settings EEPROM. Restoring stock returns the original EEPROM-loading behavior; EEPROM keymap entries are left as stock last wrote them.',
    'Each destination preserves its factory bit-7 Fn-lock flag; profiles cannot change the flag or invent internal function encodings.',
    'Unverified internal factory functions can only be retained unchanged in their original slot; they cannot be assigned to other keys or normalized to a new type.',
    'Interrupted flashing leaves persistent update mode; stock restore needs the bootloader to stay reachable over USB. Recovery is not guaranteed after hardware failure.',
    'The browser cannot see which physical USB port or bus (USB vs Bluetooth) a device uses. Devices are identified by IDs, product name and the exact vendor report layout; flash only with the cable connected and the mode switch on ON.',
  ];
  const SETTINGS_NOTE = 'Bluetooth sleep/auto-off and backlight timeouts are not editable here: their exact firmware value sources, units, and runtime initialization remain unverified. No guessed settings or EEPROM writes are offered.';

  class FlashError extends Error {}

  /* ---------------- byte helpers ---------------- */
  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; table[n] = c >>> 0; }
    return table;
  })();
  /** zlib.crc32(payload) ^ 0xFFFFFFFF, as stored in the prepare template. */
  function imageCrc(payload) {
    let crc = 0xffffffff;
    for (let i = 0; i < payload.length; i++) crc = CRC_TABLE[(crc ^ payload[i]) & 0xff] ^ (crc >>> 8);
    return crc >>> 0;
  }
  const u32le = (data, offset) => (data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16 | data[offset + 3] << 24) >>> 0;
  const u32be = (data, offset) => (data[offset] << 24 | data[offset + 1] << 16 | data[offset + 2] << 8 | data[offset + 3]) >>> 0;
  function putU32le(data, offset, value) { for (let i = 0; i < 4; i++) data[offset + i] = (value >>> (8 * i)) & 0xff; }
  function putU32be(data, offset, value) { for (let i = 0; i < 4; i++) data[offset + i] = (value >>> (8 * (3 - i))) & 0xff; }
  function equalBytes(a, b) { if (a.length !== b.length) return false; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }
  const hex = (value, width) => value.toString(16).padStart(width, '0');
  const toHex = bytes => Array.from(bytes, byte => hex(byte, 2)).join('');
  const spacedHex = bytes => Array.from(bytes, byte => hex(byte, 2)).join(' ');
  function zstr(bytes) { let end = bytes.indexOf(0); if (end < 0) end = bytes.length; return String.fromCharCode(...bytes.subarray(0, end)); }
  async function sha256Hex(bytes) {
    const subtle = globalThis.crypto && globalThis.crypto.subtle;
    if (!subtle) throw new Error('SHA-256 (Web Crypto) is unavailable in this browser context.');
    return toHex(new Uint8Array(await subtle.digest('SHA-256', bytes)));
  }

  /** Additive header checksum: 0x55555555 - sum(header[8:headLength]). */
  function checksum(head) {
    const length = u32le(head, 4);
    if (length >= HEAD_REGION) return 0;
    let sum = 0;
    for (let i = 8; i < length; i++) sum += head[i];
    return (0x55555555 - sum) >>> 0;
  }
  function thumbBl(address, target) {
    const offset = ((target - (address + 4)) >> 1) & 0x3fffff;
    const high = 0xf000 | offset >> 11, low = 0xf800 | offset & 0x7ff;
    return Uint8Array.of(high & 0xff, high >> 8, low & 0xff, low >> 8);
  }
  const STOCK_CALL = thumbBl(MODE_SWITCH_CALL, EEPROM_KEYMAP_LOADER);
  const PATCHED_CALL = thumbBl(MODE_SWITCH_CALL, ROM_KEYMAP_LOADER);
  const CODE_PATCH = {address: `0x${hex(MODE_SWITCH_CALL, 0)}`,
    from: `bl 0x${hex(EEPROM_KEYMAP_LOADER, 0)} (Win/Mac switch loads keymap from settings EEPROM)`,
    to: `bl 0x${hex(ROM_KEYMAP_LOADER, 0)} (Win/Mac switch loads flashed keymap, as at boot)`};

  function integer(value, name, minimum, maximum) {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum || value > maximum)
      throw new Error(`${name} must be an integer from ${minimum} to ${maximum}`);
    return value;
  }
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const offsetOf = (layer, index) => LAYERS[layer] + index * 4;
  const decode = (data, offset) => [data[offset], data[offset + 1] | data[offset + 2] << 8];
  function entry(type, value) {
    integer(type, 'entry type', 0, 255); integer(value, 'entry value', 0, 65535);
    const lo = value & 255, hi = value >> 8;
    return Uint8Array.of(type, lo, hi, (0x55 - type - lo - hi) & 255);
  }
  function label(type, value) {
    if (!SUPPORTED_TYPES.includes(type & 0x7f)) return `Factory function ${hex(type, 2)}:${hex(value, 4)} (original slot only; meaning unverified)`;
    type &= 0x7f;
    const mods = () => Object.entries(MOD_LABELS).filter(([bit]) => value & Number(bit)).map(([, name]) => name).join(' + ');
    if (type === 0) return 'Disabled / unused';
    if (type === 1) return mods();
    if (type === 2) return KEY_LABELS.get(value) || `Keyboard usage 0x${hex(value, 4)}`;
    if (type === 3) return MEDIA_LABELS.get(value) || `Consumer usage 0x${hex(value, 4)}`;
    if (type === 6 && value === 2) return 'Fn';
    if (type === 7) {
      const key = value >> 8;
      return `${Object.entries(MOD_LABELS).filter(([bit]) => value & Number(bit)).map(([, name]) => name).join(' + ')} + ${KEY_LABELS.get(key) || `usage 0x${hex(key, 2)}`}`;
    }
    return `Factory function ${hex(type, 2)}:${hex(value, 4)} (meaning unverified)`;
  }

  /* ---------------- container / report plan ---------------- */
  function parseHeader(data) {
    if (data.length < HEAD_REGION) throw new Error('file shorter than the 0x2000 header region');
    return {headCRC: u32le(data, 0), headLength: u32le(data, 4), fwLength: u32le(data, 8), nextFileAddress: u32le(data, 12),
      fileId: zstr(data.subarray(0x17, 0x17 + 64)), icName: zstr(data.subarray(0x57, 0x57 + 64))};
  }
  /** All update-mode HID reports (report ID included): one prepare, then 32-byte data chunks. */
  function upgradeReports(data) {
    const header = parseHeader(data), payload = data.subarray(HEAD_REGION);
    const prepareLength = u32be(data, PREPARE + 7), prepareCrc = u32be(data, PREPARE + 11);
    if (header.fileId !== 'ComUsbUpgradeFile' || header.icName !== 'CX53710' || header.nextFileAddress !== 0
        || header.headCRC !== checksum(data.subarray(0, HEAD_REGION)) || header.fwLength !== payload.length || !payload.length
        || prepareLength !== payload.length || prepareCrc !== imageCrc(payload))
      throw new Error('invalid or unsupported OE915 firmware container');
    for (const [offset, opcode] of [[PREPARE, 0xb0], [DOWNLOAD, 0xb1]]) {
      if (!equalBytes(data.subarray(offset, offset + 4), Uint8Array.of(49, 0, 6, opcode))) throw new Error('unsupported HID command template');
    }
    const base = u32be(data, DOWNLOAD + 7);
    if (base !== 0x2000) throw new Error('unexpected OE915 flash start address');
    const reports = [data.slice(PREPARE + 2, PREPARE + 2 + 49)];
    for (let offset = 0; offset < payload.length; offset += 32) {
      const n = Math.min(32, payload.length - offset), packet = new Uint8Array(49);
      packet.set([6, 0xb1, offset + n === payload.length ? 0xc1 : 0xc0, n]);
      putU32be(packet, 5, base + offset);
      packet.fill(0xff, 17, 49);
      packet.set(payload.subarray(offset, offset + n), 17);
      reports.push(packet);
    }
    return reports;
  }
  /** Normal-mode update-entry report from the container template, checksum recomputed. */
  function resetCommand(data) {
    const report = data.slice(RESET_COMMAND, RESET_COMMAND + 17);
    let sum = 0; for (let i = 0; i < 16; i++) sum += report[i];
    report[16] = (0x55 - sum) & 255;
    return report;
  }

  /* ---------------- authenticated firmware ---------------- */
  /** Candidate containers: the exact .bin, or containers embedded in the vendor updater EXE. */
  function containerCandidates(bytes) {
    if (bytes.length === STOCK_SIZE) return [bytes];
    const marker = [...'ComUsbUpgradeFile'].map(char => char.charCodeAt(0)), found = [];
    for (let i = 0x17; i + marker.length <= bytes.length; i++) {
      if (bytes[i] !== marker[0]) continue;
      let match = true; for (let k = 1; k < marker.length; k++) if (bytes[i + k] !== marker[k]) { match = false; break; }
      const start = i - 0x17;
      if (match && start + STOCK_SIZE <= bytes.length) found.push(bytes.subarray(start, start + STOCK_SIZE));
    }
    return found;
  }
  async function loadStock(input) {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    for (const candidate of containerCandidates(bytes)) {
      if (await sha256Hex(candidate) !== STOCK_SHA) continue;
      const stock = candidate.slice();
      const reports = upgradeReports(stock), stream = new Uint8Array(reports.length * 49);
      reports.forEach((report, index) => stream.set(report, index * 49));
      if (await sha256Hex(stream) !== REPORTS_SHA) throw new Error('stock report stream differs from the verified official packet builder');
      return createFirmware(stock, reports);
    }
    throw new Error('This file is not (and does not contain) the authenticated OE915 v2.52 stock firmware. Use CompxUpgradeBinFile.bin or Lofree’s OE915 V2.52 updater .exe.');
  }

  function createFirmware(stock, stockReports) {
    const factory = new Set();
    for (const layer of LAYER_IDS) for (let index = 0; index < ENTRY_COUNT; index++) factory.add(decode(stock, offsetOf(layer, index)).join(':'));
    const inFactory = (type, value) => factory.has(`${type}:${value}`);
    if (!equalBytes(stock.subarray(MODE_SWITCH_CALL, MODE_SWITCH_CALL + 4), STOCK_CALL)) throw new Error('stock Win/Mac keymap-load call is not the expected instruction');

    function action(type, value) {
      integer(type, 'action type', 0, 255); integer(value, 'action value', 0, 65535);
      if (type & 0x80 && !inFactory(type, value)) throw new Error('bit-7 types are accepted only for exact known factory actions');
      type &= 0x7f;
      let valid;
      if (type === 0) valid = value === 0;
      else if (type === 1) valid = value >= 1 && value <= 255;
      else if (type === 2) valid = KEY_LABELS.has(value);
      else if (type === 3) valid = [...factory].some(item => { const [t, v] = item.split(':').map(Number); return (t & 0x7f) === 3 && v === value; });
      else if (type === 6) valid = value === 2;
      else if (type === 7) valid = KEY_LABELS.has(value >> 8) && (value & 255) >= 1 && (value & 255) <= 15;
      else valid = false;
      if (!valid) throw new Error(`unsupported action ${hex(type, 2)}:${hex(value, 4)}`);
      return [type, value];
    }
    function slotAction(layer, index, type, value) {
      integer(type, 'action type', 0, 255); integer(value, 'action value', 0, 65535);
      const [stockType, stockValue] = decode(stock, offsetOf(layer, index));
      if (!SUPPORTED_TYPES.includes(type & 0x7f)) {
        if (type === stockType && value === stockValue) return [type, value];
        throw new Error('unverified internal factory actions may only be retained unchanged at their original slot');
      }
      [type, value] = action(type, value);
      return [type | (stock[offsetOf(layer, index)] & 0x80), value];
    }

    function model() {
      const known = new Map();
      for (const item of factory) {
        const [t, v] = item.split(':').map(Number), type = SUPPORTED_TYPES.includes(t & 0x7f) ? t & 0x7f : t;
        known.set(`${type}:${v}`, [type, v]);
      }
      for (const value of KEY_LABELS.keys()) known.set(`2:${value}`, [2, value]);
      const groups = {0: 'Disabled', 1: 'Modifiers', 2: 'Keyboard', 3: 'Media', 6: 'Layers', 7: 'Combinations'};
      const actions = [...known.values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([type, value]) => ({
        id: `${hex(type, 2)}:${hex(value, 4)}`, label: label(type, value), type, value,
        group: groups[type] || 'Factory functions (original slot only)', editable: SUPPORTED_TYPES.includes(type)}));
      const layers = LAYER_IDS.map(id => ({id, label: LAYER_LABELS[id], keys: Array.from({length: ENTRY_COUNT}, (_, index) => {
        const [type, value] = decode(stock, offsetOf(id, index));
        return {index, row: Math.floor(index / COLS), col: index % COLS, label: label(type, value), type, value};
      })}));
      return {format: FORMAT, base_sha256: STOCK_SHA, rows: ROWS, cols: COLS, layers, actions, settings: [],
        settings_note: SETTINGS_NOTE, limitations: [...LIMITATIONS]};
    }

    function normalizeProfile(profile) {
      if (!isObject(profile)) throw new Error('profile must be a JSON object');
      if (Object.keys(profile).some(key => !['format', 'base_sha256', 'changes', 'settings'].includes(key))) throw new Error('unknown profile fields');
      if (profile.format !== FORMAT || profile.base_sha256 !== STOCK_SHA) throw new Error('profile format or authenticated firmware base does not match');
      const changes = profile.changes === undefined ? [] : profile.changes, settings = profile.settings === undefined ? {} : profile.settings;
      if (!Array.isArray(changes)) throw new Error('changes must be a list');
      if (!isObject(settings) || Object.keys(settings).length) throw new Error('settings must be an empty object; no safe settings fields are evidenced');
      if (changes.length > LAYER_IDS.length * ENTRY_COUNT) throw new Error('too many keymap changes');
      const seen = new Set(), canonical = [];
      for (const change of changes) {
        const keys = isObject(change) ? Object.keys(change).sort().join(',') : '';
        if (keys !== 'index,layer,type,value') throw new Error('each change requires exactly layer, index, type, and value');
        const layer = change.layer;
        if (typeof layer !== 'string' || !LAYER_IDS.includes(layer)) throw new Error('unknown layer');
        const index = integer(change.index, 'key index', 0, ENTRY_COUNT - 1);
        if (seen.has(`${layer}:${index}`)) throw new Error(`duplicate change for ${layer} index ${index}`);
        seen.add(`${layer}:${index}`);
        const [type, value] = slotAction(layer, index, change.type, change.value), [stockType, stockValue] = decode(stock, offsetOf(layer, index));
        if (type !== stockType || value !== stockValue) canonical.push({layer, index, type: type & 0x7f, value});
      }
      canonical.sort((a, b) => LAYER_IDS.indexOf(a.layer) - LAYER_IDS.indexOf(b.layer) || a.index - b.index);
      return {format: FORMAT, base_sha256: STOCK_SHA, changes: canonical, settings: {}};
    }

    function build(profile) {
      const normalized = normalizeProfile(profile), data = stock.slice();
      for (const change of normalized.changes) {
        const offset = offsetOf(change.layer, change.index);
        data.set(entry(change.type | (stock[offset] & 0x80), change.value), offset);
      }
      if (equalBytes(data, stock)) return data;
      data.set(PATCHED_CALL, MODE_SWITCH_CALL);
      putU32be(data, PREPARE + 11, imageCrc(data.subarray(BASE)));
      putU32le(data, 0, checksum(data.subarray(0, BASE)));
      return data;
    }

    function validateImage(data) {
      if (!(data instanceof Uint8Array)) throw new Error('firmware image must be bytes');
      if (data.length !== stock.length) throw new Error('firmware length differs from authenticated stock');
      const allowed = new Uint8Array(stock.length);
      allowed.fill(1, 0, 4); allowed.fill(1, PREPARE + 11, PREPARE + 15);
      for (const layer of LAYER_IDS) {
        const start = LAYERS[layer];
        allowed.fill(1, start, start + ENTRY_COUNT * 4);
        for (let index = 0; index < ENTRY_COUNT; index++) {
          const offset = offsetOf(layer, index), raw = data.subarray(offset, offset + 4);
          if (((raw[0] + raw[1] + raw[2] + raw[3]) & 255) !== 0x55) throw new Error(`bad entry checksum in ${layer} index ${index}`);
          if ((raw[0] & 0x80) !== (stock[offset] & 0x80)) throw new Error(`factory bit-7 flag changed in ${layer} index ${index}`);
          const [type, value] = decode(data, offset);
          const candidate = SUPPORTED_TYPES.includes(type & 0x7f) ? type & 0x7f : type;
          slotAction(layer, index, candidate, value);
        }
      }
      const keymapChanged = LAYER_IDS.some(layer => !equalBytes(data.subarray(LAYERS[layer], LAYERS[layer] + ENTRY_COUNT * 4), stock.subarray(LAYERS[layer], LAYERS[layer] + ENTRY_COUNT * 4)));
      if (!equalBytes(data.subarray(MODE_SWITCH_CALL, MODE_SWITCH_CALL + 4), keymapChanged ? PATCHED_CALL : STOCK_CALL))
        throw new Error(`Win/Mac keymap-load call at 0x${hex(MODE_SWITCH_CALL, 0)} must be ${keymapChanged ? 'retargeted to the ROM loader for a remapped keymap' : 'stock when the keymap is unchanged'}`);
      allowed.fill(1, MODE_SWITCH_CALL, MODE_SWITCH_CALL + 4);
      for (let offset = 0; offset < stock.length; offset++) {
        if (stock[offset] !== data[offset] && !allowed[offset]) throw new Error(`firmware differs outside allowed data/checksums/call at 0x${hex(offset, 0)}`);
      }
      const header = parseHeader(data), payload = data.subarray(BASE);
      if (header.headCRC !== checksum(data.subarray(0, HEAD_REGION))) throw new Error('container header checksum mismatch');
      if (header.fwLength !== payload.length || u32be(data, PREPARE + 7) !== payload.length) throw new Error('container payload/prepare length mismatch');
      if (u32be(data, PREPARE + 11) !== imageCrc(payload)) throw new Error('container prepare CRC mismatch');
    }

    /** Build review, matching oe915_patch.describe_changes. */
    async function describe(profile) {
      const normalized = normalizeProfile(profile), data = build(normalized);
      validateImage(data);
      const changes = normalized.changes.map(change => {
        const [oldType, oldValue] = decode(stock, offsetOf(change.layer, change.index));
        return {layer: change.layer, index: change.index, row: Math.floor(change.index / COLS), col: change.index % COLS,
          from: label(oldType, oldValue), to: label(change.type, change.value)};
      });
      let changedPayloadBytes = 0;
      for (let i = BASE; i < stock.length; i++) if (stock[i] !== data[i]) changedPayloadBytes++;
      return {sha256: await sha256Hex(data), size: data.length, changes, settings_changes: [], changed_payload_bytes: changedPayloadBytes,
        code_patches: equalBytes(data, stock) ? [] : [{...CODE_PATCH}], image: data, profile: normalized};
    }

    /** Reports for an image already validated against this stock. */
    function reportsFor(data) {
      validateImage(data);
      return equalBytes(data, stock) ? stockReports : upgradeReports(data);
    }

    return {stock: stock.slice(), model, normalizeProfile, build, validateImage, describe, reportsFor,
      resetCommand: () => resetCommand(stock), isStock: data => equalBytes(data, stock)};
  }

  /* ---------------- device identity and transport guards ---------------- */
  function reportBits(report) { return (report.items || []).reduce((sum, item) => sum + item.reportSize * item.reportCount, 0); }
  /**
   * Identify a WebHID device as the Flow84 normal interface or the OE915
   * bootloader. Replaces the Linux flasher's raw-descriptor equality, which the
   * browser does not expose: requires exact IDs, the vendor 0xFF02/0x02
   * collection with exactly the expected input and output report, and (normal
   * mode) the Flow84 product name.
   */
  function classifyDevice(device) {
    const ids = [device.vendorId, device.productId];
    const mode = equalBytes(ids, NORMAL_IDS) ? 'normal' : equalBytes(ids, BOOT_IDS) ? 'boot' : null;
    if (!mode) return {mode: null, ok: false, reason: `unexpected USB IDs ${hex(ids[0], 4)}:${hex(ids[1], 4)}`};
    const [reportId, bytes] = mode === 'normal' ? [8, 16] : [6, 48];
    const vendor = (device.collections || []).filter(collection => collection.usagePage === VENDOR_USAGE_PAGE);
    if (vendor.length !== 1 || vendor[0].usage !== 2) return {mode, ok: false, reason: 'vendor update collection missing or ambiguous'};
    for (const kind of ['inputReports', 'outputReports']) {
      const reports = vendor[0][kind] || [];
      if (reports.length !== 1 || reports[0].reportId !== reportId || reportBits(reports[0]) !== bytes * 8)
        return {mode, ok: false, reason: `vendor ${kind === 'inputReports' ? 'input' : 'output'} report layout differs from the stock firmware`};
    }
    if (mode === 'normal' && !NORMAL_PRODUCT_NAMES.includes(device.productName))
      return {mode, ok: false, reason: `product name ${JSON.stringify(device.productName)} is not the Flow84`};
    return {mode, ok: true, reason: ''};
  }
  /** Same outgoing-report restrictions as oe915_linux.HidTransport.send. */
  function checkOutgoing(mode, report) {
    if (mode === 'normal') {
      let sum = 0; for (const byte of report) sum += byte;
      if (report.length !== 17 || report[0] !== 8 || report[1] !== 0x0d || (sum & 255) !== 0x55)
        throw new FlashError('refusing any normal-mode command other than verified update entry');
    } else if (mode === 'boot') {
      if (report.length !== 49 || report[0] !== 6 || ![0xb0, 0xb1].includes(report[1])) throw new FlashError('refusing unsupported bootloader report');
    } else throw new FlashError('refusing report to an unverified device');
  }

  /* ---------------- upload state machine ---------------- */
  function decodeBootResponse(report) {
    if (report.length === 3 && report[0] === 0xb0) return {kind: 'other'};
    if (report.length !== 49 || report[0] !== 6) throw new FlashError(`unexpected bootloader report: ${spacedHex(report)}`);
    const opcode = report[1];
    if (opcode === 0xb1) return {kind: 'echo', report};
    if (opcode === 0xb0) return {kind: 'prepare'};
    if (opcode === 0x5a) throw new FlashError(`bootloader error: ${spacedHex(report)}`);
    if (opcode === 0x5b && report[2] === 0xb5 && [1, 2, 5, 136].includes(report[3])) return {kind: 'state', state: report[3], detail: report[4]};
    throw new FlashError(`unknown bootloader response: ${spacedHex(report)}`);
  }
  /**
   * Hardware-tested upload sequence (port of oe915_linux.upload): prepare/erase,
   * exact data echoes with bounded resends, state 136 success.
   * transport: {send(report) -> Promise, receive(deadlineMs) -> Promise<Uint8Array incl. report ID>}
   */
  async function upload(transport, reports, {emit = () => {}, progress = () => {}, timeoutMs = 10000, now = Date.now} = {}) {
    const receive = async deadline => {
      const event = decodeBootResponse(await transport.receive(deadline));
      if (event.kind === 'state') emit(`Bootloader state=${event.state} detail=${event.detail}`);
      return event;
    };
    await transport.send(reports[0]);
    emit('Prepare/erase report sent; waiting for erase completion.');
    let deadline = now() + timeoutMs;
    for (;;) {
      const event = await receive(deadline);
      if (event.kind !== 'state') continue;
      if ((event.state === 1 || event.state === 2) && event.detail === 1) break;
      if (event.state !== 1 && event.state !== 2) throw new FlashError('unexpected success/check state before data upload');
    }
    const count = reports.length - 1;
    let nextProgress = 10;
    for (let index = 1; index <= count; index++) {
      const packet = reports[index];
      await transport.send(packet);
      deadline = now() + timeoutMs;
      let mismatches = 0;
      for (;;) {
        const event = await receive(deadline);
        if (event.kind === 'echo') {
          if (equalBytes(event.report, packet)) break;
          if (++mismatches > 8) throw new FlashError(`data echo mismatch at packet ${index}`);
          await transport.send(packet);
          deadline = now() + timeoutMs;
        } else if (event.kind === 'state' && event.state === 136) {
          if (index !== count) throw new FlashError('bootloader reported success before entire image was sent');
          progress(count, count);
          emit('Bootloader reported success for the final packet.');
          return;
        } else if (event.kind === 'state' && event.state === 5 && index !== count) {
          throw new FlashError('bootloader checked image before entire upload');
        }
      }
      progress(index, count);
      const percent = Math.floor(index * 100 / count);
      if (percent >= nextProgress) { emit(`Upload ${percent}% (${index}/${count} data reports acknowledged)`); nextProgress += 10; }
    }
    deadline = now() + timeoutMs;
    for (;;) {
      const event = await receive(deadline);
      if (event.kind === 'state' && event.state === 136) { emit('Bootloader reported success.'); return; }
    }
  }

  return {FORMAT, STOCK_SHA, REPORTS_SHA, NORMAL_IDS, BOOT_IDS, VENDOR_USAGE_PAGE, CODE_PATCH, FlashError,
    loadStock, upgradeReports, checksum, imageCrc, sha256Hex, classifyDevice, checkOutgoing, decodeBootResponse, upload, label, toHex};
});
