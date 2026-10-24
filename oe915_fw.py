#!/usr/bin/env python3
"""LOFREE / CXTech "ComUsbUpgradeFile" firmware container (.bin) tool.

Container layout (all little-endian, header region is a fixed 0x2000 bytes):

  0x0000 u32  headCRC        0x55555555 - sum(header[0x08:headLength])
  0x0004 u32  headLength     bytes covered by headCRC (720 in the OE915 image)
  0x0008 u32  fwLength       payload byte count
  0x000C u32  nextFileAddress 0 for the last file, else offset of the next
                              0x2000-byte header inside the same file
  0x0010 u32  version
  0x0014 u8   deviceType
  0x0015 u8   cid
  0x0016 u8   mid
  0x0017  64  fileId          "ComUsbUpgradeFile"
  0x0057  64  icName          "CX53710"
  0x0097  64  bootInputEndPoint
  0x00D7  64  bootOutputEndPoint
  0x0117  64  normalInputEndPoint
  0x0157  64  normalOutputEndPoint
  0x0197  64  resetToUpdateModeCmd
  0x01D7  64  prepareDownLoadCmd   [0]=length of the command template,
                                   [7:11] = big-endian payload length,
                                   [11:15] = big-endian ~CRC32(payload)
                                   (zlib.crc32 ^ 0xFFFFFFFF)
  0x0217  64  dataDownLoadCmd      [7:11] = big-endian flash start address
  0x0257  64  sensorName
  0x0297  64  productName
  0x2000      payload (fwLength bytes) - ARM code linked at 0x2000,
              written to flash starting at the dataDownLoadCmd address

The struct marshalled by the updater is 727 bytes; headLength (720) excludes
the last 7 productName bytes from the checksum.

Command templates start with [report length including ID, feature flag],
followed by the HID report. OE915 uses report ID 6 with 48 data bytes:
  [1] opcode, [2] C0/C1 (more/last), [3] chunk length,
  [5:9] big-endian address, [17:49] 32-byte payload chunk.
The Windows DLL's 66-byte queue entries include internal metadata; they
are not HID wire packets. Its WriteFile call passes entry + 2 and length 49.

`plan` validates and constructs all update reports offline. It never opens
a device, sends an update-mode command, or writes flash. Packet equivalence
does not establish bootloader recovery or permission to flash a modified image.
"""

import argparse
import hashlib
import struct
import sys
import zlib

HEAD_REGION = 0x2000
PREPARE = 0x01D7
DOWNLOAD = 0x0217
FIELDS = [
    ("<I", "headCRC"),
    ("<I", "headLength"),
    ("<I", "fwLength"),
    ("<I", "nextFileAddress"),
    ("<I", "version"),
    ("<B", "deviceType"),
    ("<B", "cid"),
    ("<B", "mid"),
]
STR_FIELDS = [
    (0x0017, "fileId"),
    (0x0057, "icName"),
    (0x0097, "bootInputEndPoint"),
    (0x00D7, "bootOutputEndPoint"),
    (0x0117, "normalInputEndPoint"),
    (0x0157, "normalOutputEndPoint"),
    (0x0197, "resetToUpdateModeCmd"),
    (0x01D7, "prepareDownLoadCmd"),
    (0x0217, "dataDownLoadCmd"),
    (0x0257, "sensorName"),
    (0x0297, "productName"),
]


def checksum(head: bytes) -> int:
    length = struct.unpack_from("<I", head, 4)[0]
    if length >= HEAD_REGION:
        return 0
    return (0x55555555 - sum(head[8:length])) & 0xFFFFFFFF


def zstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1")


def image_crc(payload: bytes) -> int:
    return zlib.crc32(payload) ^ 0xFFFFFFFF


def prepare_fields(head: bytes):
    return struct.unpack_from(">II", head, PREPARE + 7)



def parse(data: bytes):
    head = data[:HEAD_REGION]
    if len(head) < HEAD_REGION:
        raise SystemExit("file shorter than the 0x2000 header region")
    out = {}
    off = 0
    for fmt, name in FIELDS:
        size = struct.calcsize(fmt)
        out[name] = struct.unpack_from(fmt, head, off)[0]
        off += size
    for off, name in STR_FIELDS:
        out[name] = zstr(head[off : off + 64])
    return head, out


def cmd_info(a):
    data = open(a.file, "rb").read()
    head, h = parse(data)
    payload = data[HEAD_REGION : HEAD_REGION + h["fwLength"]]
    print(f"file            {a.file}  {len(data)} bytes")
    print(f"sha256          {hashlib.sha256(data).hexdigest()}")
    print(f"headCRC         {h['headCRC']:#010x}  computed {checksum(head):#010x}  "
          f"{'OK' if h['headCRC'] == checksum(head) else 'MISMATCH'}")
    print(f"headLength      {h['headLength']}  fwLength {h['fwLength']}  "
          f"payload present {len(payload)}")
    print(f"nextFileAddress {h['nextFileAddress']:#x}  version {h['version']}  "
          f"deviceType {h['deviceType']:#04x} cid {h['cid']} mid {h['mid']}")
    for off, name in STR_FIELDS:
        v = h[name]
        if name.endswith("Cmd"):
            raw = head[off : off + 64]
            n = raw[0] or 0x40
            print(f"{name:20}{v!r}\n{'':20}bytes {raw[:n].hex(' ')}")
        else:
            print(f"{name:20}{v!r}")
    flash = struct.unpack_from(">I", head, DOWNLOAD + 7)[0]
    print(f"flash load addr {flash:#010x}  (chunk 0x20 bytes per HID packet)")
    plen, pcrc = prepare_fields(head)
    print(f"prepare len     {plen}  {'OK' if plen == len(payload) else 'MISMATCH'}  "
          f"crc {pcrc:#010x} computed {image_crc(payload):#010x}  "
          f"{'OK' if pcrc == image_crc(payload) else 'MISMATCH'}")
    return 0


def cmd_verify(a):
    data = open(a.file, "rb").read()
    head, h = parse(data)
    ok = h["headCRC"] == checksum(head)
    payload = data[HEAD_REGION : HEAD_REGION + h["fwLength"]]
    plen, pcrc = prepare_fields(head)
    prep_ok = plen == len(payload) and pcrc == image_crc(payload)
    print(f"headCRC {'OK' if ok else 'MISMATCH'}  "
          f"payload {'OK' if len(payload) == h['fwLength'] else 'TRUNCATED'}  "
          f"prepare len/crc {'OK' if prep_ok else 'MISMATCH'}")
    return 0 if ok and prep_ok and len(payload) == h["fwLength"] else 1


def cmd_unpack(a):
    data = open(a.file, "rb").read()
    _, h = parse(data)
    n = 0
    off = 0
    while True:
        head, h = parse(data[off:])
        payload = data[off + HEAD_REGION : off + HEAD_REGION + h["fwLength"]]
        out = f"{a.out}.{n}" if n else a.out
        open(out, "wb").write(payload)
        print(f"{out}  {len(payload)} bytes  ic={h['icName']} "
              f"product={h['productName']!r} crc={'OK' if h['headCRC'] == checksum(head) else 'MISMATCH'}")
        n += 1
        if not h["nextFileAddress"]:
            break
        off += h["nextFileAddress"]
    return 0


def cmd_pack(a):
    head = bytearray(open(a.header_file, "rb").read()[:HEAD_REGION])
    payload = open(a.payload, "rb").read()
    head[0x0008:0x000C] = struct.pack("<I", len(payload))
    head[0x000C:0x0010] = struct.pack("<I", 0)
    head[PREPARE + 7 : PREPARE + 15] = struct.pack(">II", len(payload), image_crc(payload))
    head[0x0000:0x0004] = struct.pack("<I", checksum(bytes(head)))
    blob = bytes(head).ljust(HEAD_REGION, b"\0") + payload
    open(a.out, "wb").write(blob)
    print(f"{a.out}  {len(blob)} bytes  headCRC {checksum(head):#010x}")
    return 0


def upgrade_reports(data: bytes):
    """Yield update-mode reports only; no hardware access or reboot command."""
    head, h = parse(data)
    payload = data[HEAD_REGION:]
    plen, pcrc = prepare_fields(head)
    if (h["fileId"] != "ComUsbUpgradeFile" or h["icName"] != "CX53710"
            or h["nextFileAddress"] != 0
            or h["headCRC"] != checksum(head)
            or h["fwLength"] != len(payload) or not payload
            or plen != len(payload) or pcrc != image_crc(payload)):
        raise SystemExit("invalid or unsupported OE915 firmware container")
    for off, opcode in ((PREPARE, 0xB0), (DOWNLOAD, 0xB1)):
        if head[off:off + 4] != bytes([49, 0, 6, opcode]):
            raise SystemExit("unsupported HID command template")
    base = struct.unpack_from(">I", head, DOWNLOAD + 7)[0]
    if base != 0x2000:
        raise SystemExit("unexpected OE915 flash start address")
    yield bytes(head[PREPARE + 2:PREPARE + 2 + 49])
    for off in range(0, len(payload), 32):
        n = min(32, len(payload) - off)
        packet = bytearray(49)
        packet[:4] = bytes([6, 0xB1, 0xC1 if off + n == len(payload) else 0xC0, n])
        struct.pack_into(">I", packet, 5, base + off)
        packet[17:49] = b"\xff" * 32
        packet[17:17 + n] = payload[off:off + n]
        yield bytes(packet)


def cmd_plan(a):
    data = open(a.file, "rb").read()
    digest = hashlib.sha256()
    count = 0
    first = last = None
    for packet in upgrade_reports(data):
        digest.update(packet)
        if count == 1:
            first = packet
        last = packet
        count += 1
    first_addr = struct.unpack_from(">I", first, 5)[0]
    last_addr = struct.unpack_from(">I", last, 5)[0]
    print("OFFLINE ONLY: no device opened, no reports transmitted")
    print(f"report ID       6, 48 data bytes (49 including ID)")
    print(f"reports         1 prepare + {count - 1} data")
    print(f"flash interval  [{first_addr:#x}, {last_addr + last[3]:#x})")
    print(f"final chunk     {last[3]} bytes at {last_addr:#x}")
    print(f"report SHA-256  {digest.hexdigest()}")
    print(f"first report    {first.hex(' ')}")
    print(f"last report     {last.hex(' ')}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("info", cmd_info), ("verify", cmd_verify), ("plan", cmd_plan)):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.set_defaults(fn=fn)
    s = sub.add_parser("unpack")
    s.add_argument("file")
    s.add_argument("-o", dest="out", required=True)
    s.set_defaults(fn=cmd_unpack)
    s = sub.add_parser("pack")
    s.add_argument("payload")
    s.add_argument("--header-file", required=True, help="existing .bin used as the header template")
    s.add_argument("-o", dest="out", required=True)
    s.set_defaults(fn=cmd_pack)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
