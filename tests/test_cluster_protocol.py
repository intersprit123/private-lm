import tempfile
import unittest
from pathlib import Path
from windows_host.cluster_protocol import ClusterRegistry

class ClusterRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = ClusterRegistry(Path(self.temp.name) / "cluster.json")
    def tearDown(self):
        self.temp.cleanup()
    def pair_one(self):
        code, _ = self.registry.issue_pairing_code()
        return self.registry.pair("192.168.1.20", code, {
            "name": "Test phone", "platform": "Android",
            "capabilities": {"ram_total_mb": 8192, "gpus": []}})
    def test_pairing_token_is_one_time_and_not_persisted(self):
        code, _ = self.registry.issue_pairing_code()
        paired = self.registry.pair("192.168.1.20", code, {"name": "Phone"})
        raw = (Path(self.temp.name) / "cluster.json").read_text()
        self.assertNotIn(paired["credential"], raw)
        with self.assertRaises(PermissionError):
            self.registry.pair("192.168.1.20", code, {"name": "Second device"})
    def test_pair_token_heartbeat_and_config_ack(self):
        paired = self.pair_one()
        hb = self.registry.heartbeat(paired["credential"], {"status": "ready"})
        self.assertEqual(hb["config"]["revision"], 1)
        config = self.registry.update_config({"execution_mode": "performance_group"})
        self.registry.acknowledge(paired["credential"], config["revision"], True, "Applied")
        self.assertTrue(self.registry.snapshot()[0]["config_ack_ok"])
    def test_worker_health_and_memory_accounting(self):
        paired = self.pair_one()
        hb = self.registry.heartbeat(paired["credential"], {"status": "ready", "capabilities": {"ram_available_mb": 6000, "worker_memory_available_mb": 4200, "worker_memory_held_mb": 512, "worker_state": "ready", "native_rpc_version": "rpc7", "worker_throttled": False}})
        self.assertEqual(hb["control_protocol_version"], 1)
        node = self.registry.snapshot()[0]
        self.assertTrue(node["worker_ready"])
        self.assertTrue(node["compute_eligible"])
        self.assertEqual(node["memory"]["safe_worker_budget_mb"], 4200)
        self.assertEqual(node["memory"]["worker_held_mb"], 512)

    def test_worker_is_not_compute_eligible_when_throttled_or_wrong_rpc(self):
        paired = self.pair_one()
        self.registry.heartbeat(paired["credential"], {"status": "ready", "capabilities": {"worker_state": "ready", "native_rpc_version": "rpc6", "worker_throttled": True, "ram_available_mb": 999999999}})
        node = self.registry.snapshot()[0]
        self.assertFalse(node["compute_eligible"])
        self.assertEqual(node["memory"]["reported_free_mb"], 1048576)

    def test_revocation_invalidates_credential(self):
        paired = self.pair_one()
        self.assertTrue(self.registry.revoke(paired["node_id"]))
        with self.assertRaises(PermissionError):
            self.registry.heartbeat(paired["credential"], {})
    def test_bad_pairing_attempts_are_limited(self):
        for _ in range(8):
            with self.assertRaises(PermissionError):
                self.registry.pair("192.168.1.90", "bad", {})
        with self.assertRaisesRegex(PermissionError, "Too many"):
            self.registry.pair("192.168.1.90", "bad", {})

if __name__ == "__main__":
    unittest.main()
