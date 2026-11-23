import unittest
from windows_host.cluster_config import ClusterConfig

class ClusterConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(ClusterConfig().validate().execution_mode, "performance")
    def test_memory_budget_keeps_os_headroom(self):
        with self.assertRaisesRegex(ValueError, "OS headroom"):
            ClusterConfig(ram_budget_percent=100).validate()
    def test_output_cannot_exceed_context(self):
        with self.assertRaisesRegex(ValueError, "context window"):
            ClusterConfig(context_size=512, max_output_tokens=1024).validate()
    def test_round_trip(self):
        config = ClusterConfig(execution_mode="performance_group", ram_budget_percent=55)
        self.assertEqual(ClusterConfig.from_dict(config.to_dict()), config)
    def test_unknown_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "schema"):
            ClusterConfig.from_dict({"schema_version": 99})

if __name__ == "__main__":
    unittest.main()
