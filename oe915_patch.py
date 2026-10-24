#!/usr/bin/env python3
"""Build and inspect keymap-only OE915 (Lofree Flow84) v2.52 firmware images.

The four factory layers are 6 x 22 tables of four-byte entries. These are
full-size-compatible firmware tables, not a recovered physical 84-key layout.
Only table entries, container checksums, and one fixed call may change; the
original firmware/updater files are never modified. Each destination retains
its factory bit-7 Fn-lock flag.

Stock firmware loads the keymap from ROM at boot (0x1AA66: bl 0x196CC) but
from settings EEPROM on a Win/Mac switch (0x1B06A: bl 0x19710), writing ROM
entries into any invalid EEPROM slot. Every remapped build retargets that one
call to the boot ROM loader, so a mode switch keeps the flashed layout and
never stores it in EEPROM. Stock restore is the unmodified original image.
Flashing is performed separately by oe915_linux.py.

CLI: dump; model; build --profile PROFILE.json -o OUTPUT.bin;
build --set win,3,0=lctrl --set mac,3,0=lctrl -o OUTPUT.bin; validate IMAGE.bin.
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import oe915_fw

HERE = Path(__file__).resolve().parent
STOCK_BIN = HERE / "CompxUpgradeBinFile.bin"
FORMAT = "oe915-remap-v1"
STOCK_SHA = "7c061d9ce66c0b45e7d9f02e5d467af78cd537a88529b90fccb5dbf6dbccc7de"
BASE = oe915_fw.HEAD_REGION
LAYERS = {"win": 0x22CC0, "winfn": 0x22ED0, "mac": 0x230E0, "macfn": 0x232F0}
LAYER_LABELS = {"win": "Windows", "winfn": "Windows + Fn", "mac": "Mac", "macfn": "Mac + Fn"}
ROWS, COLS = 6, 22
ENTRY_COUNT = ROWS * COLS
SETTINGS_SPEC = {}
MODE_SWITCH_CALL = 0x1B06A
EEPROM_KEYMAP_LOADER = 0x19710
ROM_KEYMAP_LOADER = 0x196CC

MODS = {"lctrl": 0x01, "lshift": 0x02, "lalt": 0x04, "lgui": 0x08,
        "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rgui": 0x80}
MOD_LABELS = {1: "Left Ctrl", 2: "Left Shift", 4: "Left Alt", 8: "Left GUI / Command",
              16: "Right Ctrl", 32: "Right Shift", 64: "Right Alt", 128: "Right GUI / Command"}
KEYS = {c: 0x04 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
KEYS.update({str((i + 1) % 10): 0x1E + i for i in range(10)})
KEYS.update({f"f{i}": 0x3A + i - 1 for i in range(1, 13)})
KEYS.update({
    "enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "equal": 0x2E, "lbracket": 0x2F, "rbracket": 0x30,
    "backslash": 0x31, "nonus_hash": 0x32, "semicolon": 0x33, "quote": 0x34,
    "grave": 0x35, "comma": 0x36, "dot": 0x37, "slash": 0x38, "caps": 0x39,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49,
    "home": 0x4A, "pageup": 0x4B, "delete": 0x4C, "end": 0x4D,
    "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "numlock": 0x53, "kp_divide": 0x54, "kp_multiply": 0x55, "kp_minus": 0x56,
    "kp_plus": 0x57, "kp_enter": 0x58, "kp_1": 0x59, "kp_2": 0x5A,
    "kp_3": 0x5B, "kp_4": 0x5C, "kp_5": 0x5D, "kp_6": 0x5E,
    "kp_7": 0x5F, "kp_8": 0x60, "kp_9": 0x61, "kp_0": 0x62, "kp_dot": 0x63,
    "nonus_backslash": 0x64, "menu": 0x65, "kp_comma": 0x85,
    "international1": 0x87, "international2": 0x88, "international3": 0x89,
    "international4": 0x8A, "international5": 0x8B, "lang1": 0x90, "lang2": 0x91,
})
KEY_LABELS = {v: (k.upper() if len(k) == 1 or k.startswith("f") and k[1:].isdigit()
                  else k.replace("_", " ").title()) for k, v in KEYS.items()}
KEY_LABELS.update({0x29: "Escape", 0x2D: "Minus (-)", 0x2E: "Equal (=)",
                   0x2F: "Left bracket ([)", 0x30: "Right bracket (])", 0x31: "Backslash",
                   0x32: "Non-US # / ~", 0x34: "Quote", 0x35: "Grave (`)",
                   0x37: "Period (.)", 0x39: "Caps Lock", 0x46: "Print Screen",
                   0x47: "Scroll Lock", 0x4B: "Page Up", 0x4E: "Page Down",
                   0x53: "Num Lock", 0x64: "Non-US backslash", 0x65: "Application / Menu",
                   0x87: "International 1 (Ro)", 0x88: "International 2 (Katakana/Hiragana)",
                   0x89: "International 3 (Yen)", 0x8A: "International 4 (Henkan)",
                   0x8B: "International 5 (Muhenkan)", 0x90: "Language 1 (Hangul)",
                   0x91: "Language 2 (Hanja)"})
MEDIA_LABELS = {0x6F: "Display brightness up", 0x70: "Display brightness down",
                0xB5: "Next track", 0xB6: "Previous track", 0xCD: "Play / Pause",
                0xE2: "Mute", 0xE9: "Volume up", 0xEA: "Volume down",
                0x192: "Calculator", 0x221: "Search"}
LIMITATIONS = [
    "This is the factory 6 × 22 full-size-compatible table, including unused and other-keyboard slots; physical Flow84 wiring has not been fully recovered.",
    "Every edit requires a full firmware reflash, not live VIA-style configuration. The current keyboard mapping is not read back.",
    "Remapped builds change one call so a Win/Mac switch reloads the flashed keymap instead of settings EEPROM. Restoring stock returns the original EEPROM-loading behavior; EEPROM keymap entries are left as stock last wrote them.",
    "Each destination preserves its factory bit-7 Fn-lock flag; profiles cannot change the flag or invent internal function encodings.",
    "Unverified internal factory functions can only be retained unchanged in their original slot; they cannot be assigned to other keys or normalized to a new type.",
    "Interrupted flashing leaves persistent update mode; verified stock restore needs a reachable bootloader on the same USB port. Recovery is not guaranteed after hardware failure.",
]


def load_stock() -> bytes:
    """Authenticate the entire original container, without modifying it."""
    data = STOCK_BIN.read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        raise ValueError("stock v2.52 container SHA-256 mismatch")
    return data


def _thumb_bl(address, target):
    offset = ((target - (address + 4)) >> 1) & 0x3FFFFF
    return struct.pack("<HH", 0xF000 | offset >> 11, 0xF800 | offset & 0x7FF)


STOCK_CALL = _thumb_bl(MODE_SWITCH_CALL, EEPROM_KEYMAP_LOADER)
PATCHED_CALL = _thumb_bl(MODE_SWITCH_CALL, ROM_KEYMAP_LOADER)
CODE_PATCH = {"address": f"{MODE_SWITCH_CALL:#x}",
              "from": f"bl {EEPROM_KEYMAP_LOADER:#x} (Win/Mac switch loads keymap from settings EEPROM)",
              "to": f"bl {ROM_KEYMAP_LOADER:#x} (Win/Mac switch loads flashed keymap, as at boot)"}


def _offset(layer, index):
    # The flash link base and container header size are both 0x2000.
    return LAYERS[layer] + index * 4


def _decode(data, offset):
    return data[offset], data[offset + 1] | data[offset + 2] << 8


def _factory_actions(stock):
    return {_decode(stock, _offset(layer, index))
            for layer in LAYERS for index in range(ENTRY_COUNT)}


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _action(action_type, value, factory):
    """Validate supported actions and canonicalize known ordinary flag aliases."""
    _integer(action_type, "action type", 0, 255)
    _integer(value, "action value", 0, 65535)
    if action_type & 0x80 and (action_type, value) not in factory:
        raise ValueError("bit-7 types are accepted only for exact known factory actions")
    action_type &= 0x7F
    if action_type == 0:
        valid = value == 0
    elif action_type == 1:
        valid = 1 <= value <= 255
    elif action_type == 2:
        valid = value in KEY_LABELS
    elif action_type == 3:
        valid = any(t & 0x7F == 3 and v == value for t, v in factory)
    elif action_type == 6:
        valid = value == 2
    elif action_type == 7:
        valid = value >> 8 in KEY_LABELS and 1 <= (value & 255) <= 15
    else:
        valid = False
    if not valid:
        raise ValueError(f"unsupported action {action_type:02x}:{value:04x}")
    return action_type, value


def _slot_action(stock, layer, index, action_type, value, factory):
    _integer(action_type, "action type", 0, 255)
    _integer(value, "action value", 0, 65535)
    if action_type & 0x7F not in (0, 1, 2, 3, 6, 7):
        if (action_type, value) == _decode(stock, _offset(layer, index)):
            return action_type, value
        raise ValueError("unverified internal factory actions may only be retained unchanged at their original slot")
    action_type, value = _action(action_type, value, factory)
    flag = stock[_offset(layer, index)] & 0x80
    return action_type | flag, value


def entry(action_type: int, value: int) -> bytes:
    _integer(action_type, "entry type", 0, 255)
    _integer(value, "entry value", 0, 65535)
    lo, hi = value & 255, value >> 8
    return bytes((action_type, lo, hi, (0x55 - action_type - lo - hi) & 255))


def _label(action_type, value):
    if action_type & 0x7F not in (0, 1, 2, 3, 6, 7):
        return f"Factory function {action_type:02x}:{value:04x} (original slot only; meaning unverified)"
    action_type &= 0x7F
    if action_type == 0:
        return "Disabled / unused"
    if action_type == 1:
        return " + ".join(label for bit, label in MOD_LABELS.items() if value & bit)
    if action_type == 2:
        return KEY_LABELS.get(value, f"Keyboard usage 0x{value:04x}")
    if action_type == 3:
        return MEDIA_LABELS.get(value, f"Consumer usage 0x{value:04x}")
    if action_type == 6 and value == 2:
        return "Fn"
    if action_type == 7:
        modifiers = " + ".join(label for bit, label in MOD_LABELS.items() if value & bit)
        return f"{modifiers} + {KEY_LABELS.get(value >> 8, f'usage 0x{value >> 8:02x}')}"
    return f"Factory function {action_type:02x}:{value:04x} (meaning unverified)"


def model() -> dict:
    stock = load_stock()
    factory = _factory_actions(stock)
    known = {(t & 0x7F if t & 0x7F in (0, 1, 2, 3, 6, 7) else t, v) for t, v in factory}
    known.update((2, v) for v in KEY_LABELS)
    layers = []
    for layer in LAYERS:
        keys = []
        for index in range(ENTRY_COUNT):
            action_type, value = _decode(stock, _offset(layer, index))
            keys.append({"index": index, "row": index // COLS, "col": index % COLS,
                         "label": _label(action_type, value), "type": action_type, "value": value})
        layers.append({"id": layer, "label": LAYER_LABELS[layer], "keys": keys})
    groups = {0: "Disabled", 1: "Modifiers", 2: "Keyboard", 3: "Media",
              6: "Layers", 7: "Combinations"}
    actions = [{"id": f"{t:02x}:{v:04x}", "label": _label(t, v), "type": t, "value": v,
                "group": groups.get(t, "Factory functions (original slot only)"),
                "editable": t in (0, 1, 2, 3, 6, 7)} for t, v in sorted(known)]
    return {"format": FORMAT, "base_sha256": STOCK_SHA, "rows": ROWS, "cols": COLS,
            "layers": layers, "actions": actions, "settings": [],
            "settings_note": "Bluetooth sleep/auto-off and backlight timeouts are not editable here: their exact firmware value sources, units, and runtime initialization remain unverified. No guessed settings or EEPROM writes are offered.",
            "limitations": list(LIMITATIONS)}


def normalize_profile(profile) -> dict:
    """Validate all overrides before any image bytes are changed."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be a JSON object")
    if set(profile) - {"format", "base_sha256", "changes", "settings"}:
        raise ValueError("unknown profile fields")
    if profile.get("format") != FORMAT or profile.get("base_sha256") != STOCK_SHA:
        raise ValueError("profile format or authenticated firmware base does not match")
    changes, settings = profile.get("changes", []), profile.get("settings", {})
    if not isinstance(changes, list):
        raise ValueError("changes must be a list")
    if not isinstance(settings, dict) or settings:
        raise ValueError("settings must be an empty object; no safe settings fields are evidenced")
    if len(changes) > len(LAYERS) * ENTRY_COUNT:
        raise ValueError("too many keymap changes")
    stock = load_stock()
    factory = _factory_actions(stock)
    seen, canonical = set(), []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"layer", "index", "type", "value"}:
            raise ValueError("each change requires exactly layer, index, type, and value")
        layer = change["layer"]
        if not isinstance(layer, str) or layer not in LAYERS:
            raise ValueError("unknown layer")
        index = _integer(change["index"], "key index", 0, ENTRY_COUNT - 1)
        if (layer, index) in seen:
            raise ValueError(f"duplicate change for {layer} index {index}")
        seen.add((layer, index))
        encoded_type, value = _slot_action(stock, layer, index, change["type"], change["value"], factory)
        if (encoded_type, value) != _decode(stock, _offset(layer, index)):
            canonical.append({"layer": layer, "index": index, "type": encoded_type & 0x7F, "value": value})
    order = {layer: i for i, layer in enumerate(LAYERS)}
    canonical.sort(key=lambda c: (order[c["layer"]], c["index"]))
    return {"format": FORMAT, "base_sha256": STOCK_SHA, "changes": canonical, "settings": {}}


def build(profile) -> bytes:
    normalized = normalize_profile(profile)
    stock = load_stock()
    if stock[MODE_SWITCH_CALL:MODE_SWITCH_CALL + 4] != STOCK_CALL:
        raise ValueError("stock Win/Mac keymap-load call is not the expected instruction")
    data = bytearray(stock)
    for change in normalized["changes"]:
        offset = _offset(change["layer"], change["index"])
        action_type = change["type"] | (stock[offset] & 0x80)
        data[offset:offset + 4] = entry(action_type, change["value"])
    if data == stock:
        return stock
    data[MODE_SWITCH_CALL:MODE_SWITCH_CALL + 4] = PATCHED_CALL
    payload = data[BASE:]
    struct.pack_into(">I", data, oe915_fw.PREPARE + 11, oe915_fw.image_crc(payload))
    struct.pack_into("<I", data, 0, oe915_fw.checksum(data[:BASE]))
    return bytes(data)


def validate_image(data) -> None:
    """Reject unexpected code, changed identity/flags, bad sums, and unknown actions.

    A changed keymap requires exactly the mode-switch call patch; an unchanged
    keymap requires the stock call, so no other instruction byte may differ.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("firmware image must be bytes")
    stock = load_stock()
    if len(data) != len(stock):
        raise ValueError("firmware length differs from authenticated stock")
    allowed = bytearray(len(stock))
    allowed[:4] = b"\x01" * 4
    allowed[oe915_fw.PREPARE + 11:oe915_fw.PREPARE + 15] = b"\x01" * 4
    factory = _factory_actions(stock)
    for layer in LAYERS:
        start = LAYERS[layer]
        allowed[start:start + ENTRY_COUNT * 4] = b"\x01" * (ENTRY_COUNT * 4)
        for index in range(ENTRY_COUNT):
            offset = _offset(layer, index)
            raw = data[offset:offset + 4]
            if sum(raw) & 255 != 0x55:
                raise ValueError(f"bad entry checksum in {layer} index {index}")
            if raw[0] & 0x80 != stock[offset] & 0x80:
                raise ValueError(f"factory bit-7 flag changed in {layer} index {index}")
            action_type, value = _decode(data, offset)
            # Supported actions use canonical types; unverified factory bytes stay literal.
            candidate_type = action_type & 0x7F
            if candidate_type not in (0, 1, 2, 3, 6, 7):
                candidate_type = action_type
            _slot_action(stock, layer, index, candidate_type, value, factory)
    keymap_changed = any(data[start:start + ENTRY_COUNT * 4] != stock[start:start + ENTRY_COUNT * 4]
                         for start in LAYERS.values())
    call = bytes(data[MODE_SWITCH_CALL:MODE_SWITCH_CALL + 4])
    if call != (PATCHED_CALL if keymap_changed else STOCK_CALL):
        raise ValueError(f"Win/Mac keymap-load call at {MODE_SWITCH_CALL:#x} must be "
                         + ("retargeted to the ROM loader for a remapped keymap" if keymap_changed
                            else "stock when the keymap is unchanged"))
    allowed[MODE_SWITCH_CALL:MODE_SWITCH_CALL + 4] = b"\x01" * 4
    for offset, (original, candidate) in enumerate(zip(stock, data)):
        if original != candidate and not allowed[offset]:
            raise ValueError(f"firmware differs outside allowed data/checksums/call at 0x{offset:x}")
    head, header = oe915_fw.parse(data)
    payload = data[BASE:]
    prepare_length, prepare_crc = oe915_fw.prepare_fields(head)
    if header["headCRC"] != oe915_fw.checksum(head):
        raise ValueError("container header checksum mismatch")
    if header["fwLength"] != len(payload) or prepare_length != len(payload):
        raise ValueError("container payload/prepare length mismatch")
    if prepare_crc != oe915_fw.image_crc(payload):
        raise ValueError("container prepare CRC mismatch")


def describe_changes(profile) -> dict:
    normalized = normalize_profile(profile)
    stock = load_stock()
    data = build(normalized)
    changes = []
    for change in normalized["changes"]:
        layer, index = change["layer"], change["index"]
        old_type, old_value = _decode(stock, _offset(layer, index))
        changes.append({"layer": layer, "index": index, "row": index // COLS, "col": index % COLS,
                        "from": _label(old_type, old_value), "to": _label(change["type"], change["value"])})
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "changes": changes,
            "settings_changes": [], "changed_payload_bytes": sum(a != b for a, b in zip(stock[BASE:], data[BASE:])),
            "code_patches": [] if data == stock else [CODE_PATCH]}


def _parse_key(spec):
    spec = spec.lower()
    if spec in MODS:
        return 1, MODS[spec]
    if spec in KEYS:
        return 2, KEYS[spec]
    if spec == "fn":
        return 6, 2
    if spec == "disable":
        return 0, 0
    try:
        action_type, value = spec.split(":")
        return int(action_type, 16), int(value, 16)
    except ValueError as error:
        raise ValueError(f"unknown key {spec!r}; use a key name, fn, disable, or TYPE:VALUE hex") from error


def _cli_profile(args):
    profile = (json.loads(Path(args.profile).read_text()) if args.profile else
               {"format": FORMAT, "base_sha256": STOCK_SHA, "changes": [], "settings": {}})
    # Validate imported shape before extending it, and preserve duplicate detection.
    normalize_profile(profile)
    profile = dict(profile)
    changes = list(profile.get("changes", []))
    for spec in args.set or []:
        try:
            where, key = spec.split("=", 1)
            layer, row, col = where.split(",")
            row, col = int(row), int(col)
            _integer(row, "row", 0, ROWS - 1)
            _integer(col, "column", 0, COLS - 1)
            action_type, value = _parse_key(key)
        except ValueError as error:
            raise ValueError(f"invalid --set {spec!r}: {error}") from error
        changes.append({"layer": layer, "index": row * COLS + col, "type": action_type, "value": value})
    profile["changes"] = changes
    return normalize_profile(profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dump", help="display all original factory table slots")
    sub.add_parser("model", help="emit the factory model as JSON")
    builder = sub.add_parser("build", help="build a keymap container offline; never an updater EXE")
    builder.add_argument("--profile", help="JSON remapping profile")
    builder.add_argument("--set", action="append", metavar="LAYER,ROW,COL=KEY")
    builder.add_argument("-o", "--out", required=True, help="exact output .bin path")
    validator = sub.add_parser("validate", help="validate a keymap image without hardware access")
    validator.add_argument("image")
    args = parser.parse_args()
    try:
        if args.command == "dump":
            for layer in model()["layers"]:
                print(f"--- {layer['id']} ({LAYERS[layer['id']]:#x})")
                for row in range(ROWS):
                    print(f"r{row}: " + " | ".join(f"c{k['col']} {k['label']}" for k in layer["keys"] if k["row"] == row))
            print("Factory table, not a physical 84-key wiring map.")
        elif args.command == "model":
            print(json.dumps(model(), indent=2))
        elif args.command == "validate":
            validate_image(Path(args.image).read_bytes())
            print("Valid authenticated-stock-derived keymap image; identity unchanged and code limited to the Win/Mac keymap-load call.")
        else:
            profile = _cli_profile(args)
            data = build(profile)
            validate_image(data)
            output = Path(args.out)
            if output.suffix.lower() != ".bin" or output.is_symlink():
                raise ValueError("output must be a .bin path, not a symlink or updater EXE")
            for original in (STOCK_BIN, HERE.parent / "OE915更新V2.52.exe"):
                if output.resolve() == original.resolve() or (
                        output.exists() and original.exists() and output.samefile(original)):
                    raise ValueError("refusing to overwrite original firmware or updater")
            output.write_bytes(data)
            print(json.dumps(describe_changes(profile), indent=2))
            print(f"Wrote {output}; no device opened or command sent.")
        return 0
    except (OSError, ValueError) as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
