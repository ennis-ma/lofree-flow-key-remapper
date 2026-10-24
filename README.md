# Lofree Flow84 / OE915 firmware project

Browser-based remapper and WebHID flasher, firmware-container tools, a Linux CLI flasher, tested stock restoration, and reverse-engineering record for **OE915 v2.52 / CX53710**. Snapshot and hardware work: 2026-10-09.

## Current capabilities

- Build onboard remaps for Windows, Windows+Fn, Mac, and Mac+Fn in a standalone web app, then flash them from Chrome over WebHID; or flash with the Linux CLI.
- Test switch actuation, latency, modifiers and remap verification (e.g. Caps Lock → Ctrl) with the interactive Flow84 Key Tester in the web app.
- Preview/download firmware and import/export mapping profiles in the browser; no server needed.
- Preserve each factory slot's bit-7 flag; reject unsupported internal actions and unrelated firmware changes.
- Remapped builds include one fixed call patch so Win/Mac switching loads the flashed keymap rather than older settings-memory entries.
- Restore the byte-identical vendor stock image, including from bootloader (update) mode. No universal recovery guarantee.

**This is not VIA and not live remapping. Every mapping edit currently requires a full firmware reflash.** Bluetooth sleep/auto-off settings are deliberately unavailable: their value source and timer units remain unresolved. The factory 6×22 grid is not a fully recovered physical 84-key layout.

## Online application & GitHub Pages

The application is deployed on GitHub Pages:
**[https://ennis-ma.github.io/lofree-firmware/](https://ennis-ma.github.io/lofree-firmware/)**

The attached authenticated OE915 v2.52 firmware (`CompxUpgradeBinFile.bin`) is bundled directly with the web application so you can load it in one click without downloading or searching for external files.

You can also run it locally: open [`web/index.html`](web/index.html) in desktop Chrome, Edge, Opera or Brave: double-click it (`file://` works) or host the repository root on any local HTTP server.

1. **Load firmware**: Click **⚡ Load attached firmware** (or drag & drop `CompxUpgradeBinFile.bin`).
2. **Configure**: Choose a layer → click a key on the rendered Flow84 → choose an assignment.
3. **Review & flash**: Review the exact digest and changes, plug in the USB cable with the switch on **ON** (not BT), connect the Flow84, and confirm firmware write over WebHID.
4. **Key tester**: Switch to the **Tester** tab anytime to test switches, check latency, verify remaps, and test modifier locks.

Downloading and previewing never send keyboard commands. Keep the cable connected and the tab open while writing. On Linux the browser needs hidraw access to the keyboard (existing udev `uaccess` rules).

## Last hardware-tested remap

`profiles/caps-to-ctrl.json` maps **Caps Lock to Left Ctrl on both Windows and Mac base layers**, with the Win/Mac mode-switch patch. It is **not a reciprocal Ctrl↔Caps swap**; the original Ctrl key and Fn-layer Caps slots are unchanged.

Final requested install: this exact image was flashed successfully on USB port `3-3`; the bootloader acknowledged all data, reported success, and normal USB returned. The keyboard is left **remapped**, not stock. See [install record](evidence/install-record.json) and [flash log](evidence/last-flash.log). Physical key behavior was proven on the identical image in the earlier test, not re-observed during this reinstall.

Offline build and validation:

```sh
python3 -B oe915_patch.py build --profile profiles/caps-to-ctrl.json -o images/caps-to-ctrl-v2.52.bin
python3 -B oe915_patch.py validate images/caps-to-ctrl-v2.52.bin
sha256sum images/caps-to-ctrl-v2.52.bin
```

Expected SHA-256: `0e73b1e2db93055a809c0280bb76c07184cd35ec16c1682b2e1ee9d321fe06ac`.

Read-only USB preflight:

```sh
python3 -B oe915_linux.py inspect
```

The hardware tested here was on physical port `3-3`; **do not assume this is your current port**. Use the exact port printed by `inspect`, not an unstable `/dev/hidrawN` name.

The following commands **write the keyboard's firmware**; run only when you intend that operation and can keep USB/power connected:

```sh
python3 -B oe915_linux.py flash --port 3-3 --image images/caps-to-ctrl-v2.52.bin
python3 -B oe915_linux.py flash-stock --port 3-3
```

The second command undoes the firmware patch, not arbitrary EEPROM state. It is an alternative operation, not an automatic next step after the first.

## Safety and recovery boundary

- A prior exploratory update-entry command left this keyboard in persistent update mode; the user recovered it using Lofree's Windows updater. Do not repeat speculative commands.
- Keep `CompxUpgradeBinFile.bin` and `originals/OE915更新V2.52.exe` intact. The stock container's SHA is checked before building/flashing.
- A recognized bootloader can be restored using `flash-stock` on its exact physical port, or in the web app by connecting the bootloader and choosing **Restore authenticated stock**. Normal-mode update entry requires a working normal USB vendor interface.
- The web app cannot see the USB port or bus; it identifies the keyboard by IDs, product name and the exact vendor report layout. Flash only over the cable with the mode switch on ON, with one Flow84 connected.
- Leaving boot and USB code unchanged reduces risk; it **does not guarantee** recovery if new application code crashes or corrupts state. No independently verified hardware-only bootloader-entry procedure is documented here.
- The tools use existing hidraw permissions; they do not install rules, use sudo automatically, or change system configuration. `evidence/70-lofree.rules.snapshot` records the pre-existing workstation rules, not an installation instruction. VID/PID `05ac:024f` alone is unsafe identification because genuine Apple keyboards use it too.
- Flash validation allows keymap data, necessary checksums, and exactly the approved mode-switch call. The general-purpose container packer is not a flashing safety validator.

## Offline verification

```sh
python3 -B -m unittest test_oe915_profiles
node --test web/
python3 -B oe915_fw.py verify CompxUpgradeBinFile.bin
python3 -B oe915_fw.py plan CompxUpgradeBinFile.bin
```

Tests do not open USB nodes. `node --test web/` checks the browser core against the Python tools and a simulated bootloader. `info`, `verify`, `plan`, `dump`, `model`, and firmware building are offline. `inspect` reads sysfs/permissions without opening hidraw. Only `flash`, `flash-stock`, and confirmed web-app writes perform firmware updates.

## Project files and provenance

The maintained `.py` tools, stock container, payload, and vendor configuration are included in the repository. The standalone `web/` app bundles the authenticated firmware image for convenient browser flashing and switch testing. Detailed research notes, execution logs, and historical extraction snapshots are kept offline in private working directories.
