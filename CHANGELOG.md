# Changelog

## 2026-10-09 — One-line header with a clickable connection status

- The header's connection status is now a button: it reads **Connect keyboard** until a keyboard is granted, then "Flow84 connected" or "Bootloader (update mode)". Clicking it on any page opens the same WebHID chooser as the Flash page's **Connect…**. Chooser errors appear in the page's top error box, or in the device panel on the Flash page. It is disabled while a write runs.
- Import, Export and Reset draft are icon buttons with tooltips and accessible names. The subtitle is shortened. The draft-storage note now appears only when there is a problem (storage unavailable, saved draft unreadable).
- Browser smoke on Chromium 152 with a simulated device: the header stayed on one row at viewport widths 760–1280 px (63–67 px tall). Clicking the status opened the chooser and selected the picked Flow84 ("Flow84 connected").

## 2026-10-09 — Bootloader chooser opens automatically

- After update entry, the web app now opens Chrome's bootloader (`3554:f800`) chooser itself, using the Confirm click's user activation. The user picks the bootloader once, and the separate **Connect bootloader** click is no longer needed. That button remains as a fallback if the chooser is dismissed or the activation has expired.
- A fully prompt-free reconnect is not possible from a public page: the device has no USB serial number, so Chromium's grant lasts one connection, and silent grants need a managed `WebHidAllowDevicesForUrls` policy.
- Browser smoke on Chromium 152 with a simulated HID device: `navigator.userActivation.isActive` was true when the chooser opened; the bootloader was picked and the upload started on it. A dismissed chooser fell back to **Connect bootloader**. Not yet hardware-tested.

## 2026-10-09 — Standalone web app with WebHID flashing

- Replaced the local Python server (`oe915_remapper.py`) and its page with a standalone app in `web/`: open `web/index.html` (file:// or any HTTPS host) in a Chromium browser; no server or Python needed.
- Ported the builder, image validator, report planner, boot-response decoder and upload state machine to `web/oe915-core.js`; the app loads the user's `CompxUpgradeBinFile.bin` or vendor updater EXE, authenticates it by SHA-256 and bundles no firmware.
- Flashing and stock restore run over WebHID with the Linux flasher's outgoing-report guards; devices are identified by IDs, product name and exact vendor report layout. After update entry, the page asks for the bootloader grant when Chrome needs one. Restore works from bootloader mode.
- Added `web/oe915-core.test.js` (`node --test web/`): parity with the Python tools and simulated-bootloader upload tests. Browser smoke used a simulated device; the WebHID path is not yet hardware-tested.
- Fixed the Combos builder hint, which had collapsed into a one-character-wide column.

## 2026-10-09 — VIA-style remapper UI

- Rebuilt `oe915_ui.html` as a dark, VIA-style configurator: rendered Flow84 75% keyboard, numbered layer tabs with per-layer change counts, a categorized click-to-assign picker (Basic, Modifiers, F-keys, Navigation, Media, Numpad, International, Combos, Special) with search, and a key + left-modifier combo builder.
- Physical keys are placed on the factory slot whose Windows-layer function matches the Flow84 keycap legend; Fn-layer functions match the printed Fn legends. The full 6 × 22 factory table remains available as "All 132 factory slots". Fn-layer keys equal to their base layer are shown faded.
- Separate Configure / Flash / Safety views. Flash view adds a Build → Review → Flash stepper and per-change Show/Revert. Build, review acknowledgement, exact-port, stale-status and two-step confirmation guards are unchanged.
- Removed the always-empty settings editor; profiles with any `settings` entry are rejected, matching the builder.
- Browser smoke: Caps→Ctrl on both base layers still builds `0e73b1e2…06ac`; confirmation dialog opened and cancelled with `job: null`; no console errors.

## 2026-10-09 — Project preserved and last tested remap selected

- Collected maintained remapper/container/Linux-flasher tools and untouched stock artifacts in `~/Projects/lofree-firmware`; preserved original vendor updater under `originals/`.
- Archived retained reverse-engineering scripts/listings/maps/DLLs/web bundles with source and per-member SHA-256 provenance. Exploratory scripts are quarantined as research, not supported operations.
- Added usage/API, firmware/address reference, corrected upload-protocol reference, hardware/software verification record and live-remapping/VIA assessment.
- Preserved a reproducible `profiles/caps-to-ctrl.json`: Caps→Left Ctrl on both base OS layers, not a reciprocal swap. Final image/install evidence is recorded under `evidence/`.
- No live-remapping firmware or guessed settings were implemented during documentation.

## 2026-10-09 — Win/Mac mode-switch patch

- Found stock mode-switch call at `0x1b06a` loading keymap entries from EEPROM via `0x19710`, including writing ROM defaults for invalid entries.
- Retargeted that exact call to existing ROM keymap loader `0x196cc`. The four-byte instruction changes from `fe f7 51 fb` to `fe f7 2f fb`; only one instruction byte differs.
- Every changed keymap requires the exact patch; unchanged/no-op profiles remain byte-identical stock. Other code edits and remapped images without this patch are rejected.
- Replaced obsolete build review `code_unchanged` with explicit `code_patches`; updated UI confirmations and flasher messages.
- Added regression coverage for missing patch, patch with unchanged map, and no-op stock generation; 12 tests passed.
- Hardware observed Caps→Ctrl before and after user-reported Win/Mac transitions; stock rollback restored Caps in the same sequence. UI preview matched the tested image digest.
- Deleted obsolete data-only and earlier experimental builds; they are not current supported flashing images.

## 2026-10-09 — Local onboard remapper

- Added strict sparse remap profiles, four-layer factory grid, supported key/modifier/media/Fn/left-modifier-combo encodings, preserved slot bit-7 flags and internal-action restrictions.
- Built loopback HTTP/UI workflow with preview/download, browser drafts, profile import/export, exact port selection, review digest, confirmed flash/stock restore, live job logs and same-origin/session guards.
- Proved Linux stock flashing, data-only Caps→Ctrl remapping, and stock restoration with physical raw-HID key observations.
- Initially restricted images to data-only changes; that policy was later superseded by the narrowly allowed, hardware-tested mode-switch call patch above.

## 2026-10-09 — Settings investigation and corrected conclusions

- Traced RAM threshold `0x400398` reads in idle/sleep/backlight candidate paths. Exact writer, default source and timer cadence remain unknown; settings stay uneditable.
- Corrected an early claim that EEPROM settings always override ROM defaults: boot calls a loader and then performs unconditional ROM→RAM copies. No blanket precedence or impossibility conclusion is justified.
- Corrected overly strong recovery language: leaving boot/USB code untouched does not guarantee recoverability after arbitrary new code failure.
- Corrected intermediate HID `0x01` interpretation: not independent decoded mode-state evidence.

## 2026-10-09 — Official updater extraction and protocol work

- Extracted v2.52 firmware container/payload/configuration from the user's supplied .NET Windows updater.
- Implemented container info/verify/pack/unpack and offline update-report planning, then the authenticated Linux HID uploader.
- Established 49-byte report-ID-6 wire packets with 32-byte chunks; 66-byte native-DLL queue entries are not the transmitted HID packet length.
- Established download-template address offset `+7` and wire start `0x00002000`, not the earlier mistaken `+8` / `0x00200000` interpretation. Protocol addresses coincide with link/container addresses for this image; the chip's physical mapping remains unverified.

## Earlier incident

A speculative update-entry command left the keyboard in persistent update mode. The user obtained the vendor updater and reported successful recovery. This incident motivates authentication, exact-device checks, explicit writes and preservation of stock recovery artifacts. It does not establish guaranteed recovery from all firmware failures.
