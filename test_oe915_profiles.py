"""Consumer-visible image safety and profile boundary regressions.

Run from this directory: python3 -B -m unittest test_oe915_profiles
No USB device is opened and no firmware is flashed.
"""

import struct
import unittest

import oe915_fw as container
import oe915_patch as keymap

LAYERS = {"win": 0x22CC0, "winfn": 0x22ED0, "mac": 0x230E0, "macfn": 0x232F0}


def profile(changes=None, settings=None):
    return {"format": keymap.FORMAT, "base_sha256": keymap.STOCK_SHA,
            "changes": [] if changes is None else changes,
            "settings": {} if settings is None else settings}


def repair_container_checksums(data):
    struct.pack_into(">II", data, container.PREPARE + 7, len(data) - container.HEAD_REGION,
                     container.image_crc(data[container.HEAD_REGION:]))
    struct.pack_into("<I", data, 0, container.checksum(data[:container.HEAD_REGION]))
    return bytes(data)


class ProfileSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = keymap.load_stock()

    def test_caps_remap_is_ctrl_on_both_base_layers(self):
        image = keymap.build(profile([
            {"layer": layer, "index": 66, "type": 1, "value": 1}
            for layer in ("win", "mac")]))
        for address in (0x22DC8, 0x231E8):
            self.assertEqual(bytes.fromhex("01 01 00 53"), image[address:address + 4])
        for address in (0x22FD8, 0x233F8):
            self.assertEqual(self.stock[address:address + 4], image[address:address + 4])
        self.assertEqual(bytes.fromhex("fe f7 2f fb"), image[0x1B06A:0x1B06E])  # bl 0x196cc
        keymap.validate_image(image)

    def test_function_slot_keeps_its_fn_lock_flag(self):
        image = keymap.build(profile([{"layer": "win", "index": 1, "type": 2, "value": 4}]))
        self.assertEqual(0x82, image[LAYERS["win"] + 4])
        self.assertEqual(4, image[LAYERS["win"] + 5])
        self.assertEqual(0x55, sum(image[LAYERS["win"] + 4:LAYERS["win"] + 8]) & 255)

    def test_each_layer_accepts_first_and_last_slot(self):
        for layer, address in LAYERS.items():
            with self.subTest(layer=layer):
                image = keymap.build(profile([
                    {"layer": layer, "index": index, "type": 2, "value": usage}
                    for index, usage in ((0, 4), (131, 5))]))
                self.assertEqual(4, image[address + 1])
                self.assertEqual(5, image[address + 131 * 4 + 1])
                keymap.validate_image(image)

    def test_out_of_bounds_and_boolean_positions_are_rejected(self):
        for index in (-1, 132, True, False, 1.5, "66"):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    keymap.build(profile([{"layer": "win", "index": index, "type": 1, "value": 1}]))

    def test_duplicate_slot_assignments_are_rejected(self):
        with self.assertRaises(ValueError):
            keymap.build(profile([
                {"layer": "win", "index": 66, "type": 1, "value": 1},
                {"layer": "win", "index": 66, "type": 2, "value": 4}]))

    def test_wrong_firmware_identity_and_unknown_settings_are_rejected(self):
        wrong = profile()
        wrong["base_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            keymap.build(wrong)
        with self.assertRaises(ValueError):
            keymap.build(profile(settings={"unmapped_flash_field": 10}))

    def test_code_patch_is_rejected_even_with_valid_container_checksums(self):
        changed = bytearray(self.stock)
        changed[0x1B06C] ^= 1
        with self.assertRaises(ValueError):
            keymap.validate_image(repair_container_checksums(changed))

    def test_remapped_keymap_requires_the_mode_switch_call_patch(self):
        image = bytearray(keymap.build(profile([{"layer": "win", "index": 66, "type": 1, "value": 1}])))
        image[0x1B06A:0x1B06E] = self.stock[0x1B06A:0x1B06E]
        with self.assertRaises(ValueError):
            keymap.validate_image(repair_container_checksums(image))

    def test_call_patch_without_keymap_change_is_rejected(self):
        changed = bytearray(self.stock)
        changed[0x1B06A:0x1B06E] = bytes.fromhex("fe f7 2f fb")
        with self.assertRaises(ValueError):
            keymap.validate_image(repair_container_checksums(changed))

    def test_no_op_change_builds_unpatched_stock(self):
        self.assertEqual(self.stock, keymap.build(profile([{"layer": "win", "index": 66, "type": 2, "value": 0x39}])))

    def test_bad_key_checksum_is_rejected_even_with_valid_image_crc(self):
        changed = bytearray(self.stock)
        changed[0x22DCB] ^= 1
        with self.assertRaises(ValueError):
            keymap.validate_image(repair_container_checksums(changed))

    def test_fn_flag_change_is_rejected_even_with_valid_checksums(self):
        changed = bytearray(self.stock)
        address = LAYERS["win"] + 4
        changed[address] &= 0x7F
        changed[address + 3] = (0x55 - sum(changed[address:address + 3])) & 255
        with self.assertRaises(ValueError):
            keymap.validate_image(repair_container_checksums(changed))


if __name__ == "__main__":
    unittest.main()
