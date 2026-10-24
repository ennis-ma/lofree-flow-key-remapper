#!/usr/bin/env python3
"""OE915 v2.52 Linux HID flasher for authenticated keymap images and stock.

`inspect` reads sysfs and validates stock without opening hidraw.
`flash-stock --port BUS-PORT` restores the verified original image.
`flash --port BUS-PORT --profile PROFILE.json` builds a remapped keymap;
`flash --port BUS-PORT --image IMAGE.bin` accepts only a validated keymap
container. Build/download images offline with oe915_patch.py first.
Remapped images contain exactly one code change: the Win/Mac switch reloads
the flashed keymap (as boot does) instead of the settings-EEPROM copy.
No other instruction patch or arbitrary firmware image is accepted.

Normal and boot interfaces are bound to the same physical USB port, with
exact HID identity and report descriptors checked before any device write.
Existing udev uaccess permissions are used; no system configuration changes.
Update mode is persistent. Interrupted flashing can require stock recovery
through a reachable bootloader; recovery from hardware failure is not assured.

The report generator and upload state machine retain the hardware-tested wire
protocol: prepare/erase, exact data echoes, state 5 check, state 136 success.
Hardware round trip with the Win/Mac call patch: a Caps-to-Ctrl image on both
base layers emitted Left Ctrl in Windows, after switching to Mac, and after
switching back. After flash-stock, the same sequence emitted Caps Lock each
time, so the patched image left no keymap in settings storage. That evidence
does not verify every possible mapping, Fn-lock action, or persistent setting.
The original firmware and updater are never modified.
"""

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import sys
import time

sys.dont_write_bytecode = True
import oe915_fw
import oe915_patch

REPORTS_SHA = "e0773c09ef14ad671ec57e332a6fae445b7df7510c0db315cc55995948481d7c"
NORMAL_IDS = (0x05AC, 0x024F)
BOOT_IDS = (0x3554, 0xF800)
BOOT_DESCRIPTOR = bytes.fromhex(
    "0602ff0902a1018506150026ff00750895300902810009029100c0"
    "050c0901a10185b01500263c0219002a3c02751095018100c0")
HIDIOCGRAWINFO = 0x80084803


class FlashError(Exception):
    pass


@dataclass(frozen=True)
class Interface:
    node: Path
    port: str
    ids: tuple
    descriptor: bytes
    name: str
    manufacturer: str


def stock_image():
    try:
        data = oe915_patch.load_stock()
    except ValueError as error:
        raise FlashError(f"{error}; refusing any device write") from error
    reports = list(oe915_fw.upgrade_reports(data))
    if hashlib.sha256(b"".join(reports)).hexdigest() != REPORTS_SHA:
        raise FlashError("report stream differs from verified official packet builder")
    # USB interface 1 descriptor as supplied in this exact stock image.
    normal_descriptor = data[0x22819:0x22883]
    return data, reports, normal_descriptor




def interfaces():
    for path in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            device = (path / "device").resolve()
            values = dict(line.split("=", 1) for line in
                          (device / "uevent").read_text().splitlines() if "=" in line)
            _, vendor, product = values.get("HID_ID", "0:0:0").split(":")
            ids = (int(vendor, 16), int(product, 16))
            if ids not in (NORMAL_IDS, BOOT_IDS):
                continue
            usb = next(p for p in device.parents if (p / "idVendor").is_file())
            manufacturer = (usb / "manufacturer").read_text().strip() if (usb / "manufacturer").exists() else ""
            yield Interface(Path("/dev") / path.name, usb.name, ids,
                            (device / "report_descriptor").read_bytes(),
                            values.get("HID_NAME", ""), manufacturer)
        except (OSError, StopIteration):
            # A USB re-enumeration can remove sysfs entries mid-snapshot.
            continue


def find_interface(port, ids, descriptor):
    matches = [i for i in interfaces() if i.port == port and i.ids == ids
               and i.descriptor == descriptor]
    if len(matches) > 1:
        raise FlashError("ambiguous HID interface on selected port")
    if not matches:
        return None
    match = matches[0]
    if ids == NORMAL_IDS and (match.name != "Compx Flow84@Lofree" or match.manufacturer != "Compx"):
        raise FlashError("normal USB device is not the expected Compx Flow84")
    return match


def wait_interface(port, ids, descriptor, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        match = find_interface(port, ids, descriptor)
        if match:
            return match
        time.sleep(0.05)
    raise FlashError(f"expected {ids[0]:04x}:{ids[1]:04x} interface did not appear on {port}")


class HidTransport:
    def __init__(self, interface):
        self.interface = interface
        self.fd = os.open(interface.node, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = bytearray(8)
            fcntl.ioctl(self.fd, HIDIOCGRAWINFO, info, True)
            bus, vendor, product = struct.unpack("<IHH", info)
            if bus != 3 or (vendor, product) != interface.ids:
                raise FlashError("opened HID identity changed; refusing write")
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def send(self, report):
        if self.interface.ids == NORMAL_IDS:
            if len(report) != 17 or report[:2] != bytes([8, 0x0D]) or sum(report) & 255 != 0x55:
                raise FlashError("refusing any normal-mode command other than verified update entry")
        elif len(report) != 49 or report[0] != 6 or report[1] not in (0xB0, 0xB1):
            raise FlashError("refusing unsupported bootloader report")
        written = os.write(self.fd, report)
        if written != len(report):
            raise FlashError(f"short HID write: {written}/{len(report)}")

    def receive(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
            raise FlashError("timed out waiting for bootloader response")
        data = os.read(self.fd, 4096)
        if not data:
            raise FlashError("bootloader disconnected")
        return data


def decode_boot_response(report):
    if len(report) == 3 and report[0] == 0xB0:
        return ("other",)
    if len(report) != 49 or report[0] != 6:
        raise FlashError(f"unexpected bootloader report: {report.hex(' ')}")
    opcode = report[1]
    if opcode == 0xB1:
        return ("echo", report)
    if opcode == 0xB0:
        return ("prepare",)
    if opcode == 0x5A:
        raise FlashError(f"bootloader error: {report.hex(' ')}")
    if opcode == 0x5B and report[2] == 0xB5 and report[3] in (1, 2, 5, 136):
        return ("state", report[3], report[4])
    raise FlashError(f"unknown bootloader response: {report.hex(' ')}")


def upload(transport, reports, emit=print):
    def receive(deadline):
        event = decode_boot_response(transport.receive(deadline))
        if event[0] == "state":
            emit(f"Bootloader state={event[1]} detail={event[2]}")
        return event

    transport.send(reports[0])
    emit("Prepare/erase report sent; waiting for erase completion.")
    deadline = time.monotonic() + 10
    while True:
        event = receive(deadline)
        if event[0] == "state":
            if event[1] in (1, 2) and event[2] == 1:
                break
            if event[1] not in (1, 2):
                raise FlashError("unexpected success/check state before data upload")

    count = len(reports) - 1
    next_progress = 10
    for index, packet in enumerate(reports[1:], 1):
        transport.send(packet)
        deadline = time.monotonic() + 10
        mismatches = 0
        while True:
            event = receive(deadline)
            if event[0] == "echo":
                if event[1] == packet:
                    break
                mismatches += 1
                if mismatches > 8:
                    raise FlashError(f"data echo mismatch at packet {index}")
                transport.send(packet)
                deadline = time.monotonic() + 10
            elif event[0] == "state" and event[1] == 136:
                if index != count:
                    raise FlashError("bootloader reported success before entire image was sent")
                emit("Bootloader reported success for the final packet.")
                return
            elif event[0] == "state" and event[1] == 5 and index != count:
                raise FlashError("bootloader checked image before entire upload")
        progress = index * 100 // count
        if progress >= next_progress:
            emit(f"Upload {progress}% ({index}/{count} data reports acknowledged)")
            next_progress += 10

    deadline = time.monotonic() + 10
    while True:
        event = receive(deadline)
        if event[0] == "state" and event[1] == 136:
            emit("Bootloader reported success.")
            return


def inspect(emit=print):
    _, reports, expected = stock_image()
    emit(f"Unchanged stock image verified; {len(reports)} reports, report stream SHA-256 {REPORTS_SHA}")
    for interface in interfaces():
        mode = "normal" if interface.ids == NORMAL_IDS else "boot"
        valid = interface.descriptor == (expected if mode == "normal" else BOOT_DESCRIPTOR)
        emit(f"{interface.node} port={interface.port} mode={mode} descriptor_match={valid} "
             f"read_write_access={os.access(interface.node, os.R_OK | os.W_OK)} name={interface.name!r}")
    emit("Read-only: no HID node opened, no device command sent.")


def flash_image(port, data=None, emit=print):
    if data is not None:
        if not isinstance(data, (bytes, bytearray)):
            raise FlashError("firmware image must be bytes")
        data = bytes(data)
        try:
            oe915_patch.validate_image(data)
        except ValueError as error:
            raise FlashError(f"invalid keymap image: {error}") from error
    stock, stock_reports, expected = stock_image()
    if data is None:
        data = stock
    is_stock = data == stock
    reports = stock_reports if is_stock else list(oe915_fw.upgrade_reports(data))
    emit("Selected image: unchanged stock v2.52" if is_stock else
         "Selected image: authenticated keymap; one call patched so Win/Mac switches keep it.")
    emit(f"Image SHA-256 {hashlib.sha256(data).hexdigest()}")
    boot = find_interface(port, BOOT_IDS, BOOT_DESCRIPTOR)
    if boot is None:
        normal = find_interface(port, NORMAL_IDS, expected)
        if normal is None:
            raise FlashError("verified Flow84 vendor interface not found on selected port")
        reset = bytearray(data[0x199:0x199 + 17])
        reset[-1] = (0x55 - sum(reset[:-1])) & 255
        transport = HidTransport(normal)
        try:
            emit(f"Sending known update-entry command to {normal.node} on port {port}.")
            transport.send(reset)
        finally:
            transport.close()
        boot = wait_interface(port, BOOT_IDS, BOOT_DESCRIPTOR, 15)
    emit(f"Exact bootloader descriptor verified: {boot.node} on port {port}.")
    # uaccess ACLs may settle shortly after USB enumeration.
    end = time.monotonic() + 3
    while not os.access(boot.node, os.R_OK | os.W_OK) and time.monotonic() < end:
        time.sleep(0.05)
    transport = HidTransport(boot)
    try:
        upload(transport, reports, emit=emit)
    finally:
        transport.close()
    normal = wait_interface(port, NORMAL_IDS, expected, 20)
    emit(f"RETURNED: {normal.name}; {normal.node}, port {port}; normal descriptor matches stock.")
    emit("Stock firmware installed; no remapping or experimental code." if is_stock else
         "Remapped keymap installed; Win/Mac switches reload the flashed keymap.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="read-only firmware and USB preflight")
    restore = sub.add_parser("flash-stock", help="restore authenticated stock, including from boot mode")
    restore.add_argument("--port", required=True, help="exact physical USB port from inspect, e.g. 3-3")
    flash = sub.add_parser("flash", help="upload a validated keymap profile or image")
    flash.add_argument("--port", required=True, help="exact physical USB port from inspect, e.g. 3-3")
    source = flash.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile", help="JSON remapping profile")
    source.add_argument("--image", help="validated stock-derived keymap .bin container")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            inspect()
        elif args.command == "flash-stock":
            flash_image(args.port)
        else:
            data = (oe915_patch.build(json.loads(Path(args.profile).read_text()))
                    if args.profile else Path(args.image).read_bytes())
            flash_image(args.port, data=data)
    except (FlashError, OSError, ValueError) as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        if args.command in ("flash-stock", "flash"):
            print("The keyboard may be in persistent update mode. Keep the original Windows updater "
                  "available. A verified boot-mode interface can be recovered by flash-stock on the same port.",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
