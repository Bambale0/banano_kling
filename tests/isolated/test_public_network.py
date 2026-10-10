"""Classification only: no DNS, HTTP, application or database imports."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("public_network_under_test", Path(__file__).parents[2] / "bot/public_network.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicNetworkTests(unittest.TestCase):
    def test_reject_non_public_unicast(self):
        for value in ("100.64.0.1", "100.100.100.200", "127.0.0.1", "10.0.0.1",
                      "169.254.169.254", "224.0.0.1", "0.0.0.0", "::1", "::",
                      "ff02::1", "fe80::1", "::ffff:100.64.0.1", "::ffff:127.0.0.1",
                      "::ffff:224.0.0.1", "example.com", "garbage"):
            with self.subTest(value=value):
                self.assertFalse(module.is_public_unicast(value))

    def test_accept_public_unicast(self):
        for value in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"):
            with self.subTest(value=value):
                self.assertTrue(module.is_public_unicast(value))


if __name__ == "__main__":
    unittest.main()
