import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_dev_networks", ROOT / "infrastructure/scripts/check_dev_networks.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def compose_config() -> dict:
    return {
        "name": "mykhaya",
        "networks": {
            "edge": {"ipam": {"config": [{"subnet": "10.77.0.0/24"}]}},
            "app": {
                "internal": True,
                "ipam": {"config": [{"subnet": "10.77.1.0/24"}]},
            },
            "data": {"internal": True},
        },
    }


def live(*, edge="10.77.0.0/24", app="10.77.1.0/24") -> dict:
    return {
        "mykhaya_edge": {
            "Driver": "bridge",
            "Internal": False,
            "IPAM": {"Config": [{"Subnet": edge}]},
        },
        "mykhaya_app": {
            "Driver": "bridge",
            "Internal": True,
            "IPAM": {"Config": [{"Subnet": app}]},
        },
        "mykhaya_data": {
            "Driver": "bridge",
            "Internal": True,
            "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]},
        },
    }


class NetworkComparisonTests(unittest.TestCase):
    def test_matching_networks_have_no_drift(self):
        self.assertEqual(module.compare_networks(compose_config(), live()), [])

    def test_edge_subnet_drift_is_reported(self):
        errors = module.compare_networks(compose_config(), live(edge="172.20.0.0/16"))
        self.assertTrue(any("mykhaya_edge" in error for error in errors))

    def test_app_subnet_drift_is_reported(self):
        errors = module.compare_networks(compose_config(), live(app="172.21.0.0/16"))
        self.assertTrue(any("mykhaya_app" in error for error in errors))

    def test_missing_caddy_does_not_change_network_definition_result(self):
        self.assertEqual(module.compare_networks(compose_config(), live()), [])

    def test_data_network_dynamic_subnet_is_allowed(self):
        current = live()
        current["mykhaya_data"]["IPAM"]["Config"][0]["Subnet"] = "172.30.0.0/16"
        self.assertEqual(module.compare_networks(compose_config(), current), [])


if __name__ == "__main__":
    unittest.main()
