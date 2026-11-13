import json
import tempfile
import unittest
from pathlib import Path

from lmrchip.errors import CommandError
from lmrchip.protocols import ProtocolStore, empty_protocol


class ProtocolStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = ProtocolStore(Path(self.tempdir.name))

    def tearDown(self):
        self.tempdir.cleanup()

    def protocol(self):
        protocol = empty_protocol("Binding assay")
        protocol["samples"] = [{"id": "s1", "name": "Streptavidin", "concentration": "1 mg/mL", "notes": ""}]
        protocol["positions"][1] = {"sample_id": "s1", "color": "blue"}
        protocol["steps"][0] = {"sample_id": "s1", "flow_rate": 7, "duration_seconds": 60}
        return protocol

    def test_new_has_twelve_positions_and_sixteen_steps(self):
        protocol = self.store.new()
        self.assertEqual(len(protocol["positions"]), 12)
        self.assertEqual(len(protocol["steps"]), 16)

    def test_save_load_and_list_round_trip(self):
        saved = self.store.save(self.protocol())
        loaded = self.store.load(saved["id"])
        self.assertEqual(loaded, saved)
        self.assertEqual(self.store.list(), [{"id": saved["id"], "name": "Binding assay"}])
        self.assertTrue((Path(self.tempdir.name) / f"protocol_{saved['id']}.json").is_file())

    def test_validation_rejects_unknown_references_and_wrong_lengths(self):
        protocol = self.protocol()
        protocol["steps"][0]["sample_id"] = "missing"
        with self.assertRaises(CommandError) as raised:
            self.store.validate(protocol)
        self.assertEqual(raised.exception.code, "INVALID_PROTOCOL")

        protocol = self.protocol()
        protocol["positions"] = protocol["positions"][:-1]
        with self.assertRaises(CommandError):
            self.store.validate(protocol)

    def test_validation_rejects_invalid_step_values_and_unassigned_samples(self):
        protocol = self.protocol()
        protocol["steps"][0]["flow_rate"] = 0
        with self.assertRaises(CommandError):
            self.store.validate(protocol)

        protocol = self.protocol()
        protocol["positions"][1]["sample_id"] = None
        with self.assertRaises(CommandError):
            self.store.validate(protocol)

    def test_stored_json_is_validated_when_loaded(self):
        protocol = self.protocol()
        target = Path(self.tempdir.name) / f"protocol_{protocol['id']}.json"
        target.write_text(json.dumps({**protocol, "positions": []}), encoding="utf-8")
        with self.assertRaises(CommandError) as raised:
            self.store.load(protocol["id"])
        self.assertEqual(raised.exception.code, "INVALID_PROTOCOL")


if __name__ == "__main__":
    unittest.main()
