#!/usr/bin/env python3
"""Compare live dev Compose networks with the merged declaration."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

NETWORKS = ("edge", "app", "data")


def _subnets(network: dict[str, Any]) -> set[str]:
    return {
        item["Subnet"]
        for item in network.get("IPAM", {}).get("Config", [])
        if item.get("Subnet")
    }


def compare_networks(compose: dict[str, Any], live: dict[str, dict[str, Any] | None]) -> list[str]:
    """Return immutable network-definition differences."""
    project = compose.get("name", "mykhaya")
    declared = compose.get("networks", {})
    errors: list[str] = []
    for logical_name in NETWORKS:
        expected = declared.get(logical_name, {})
        physical_name = expected.get("name", f"{project}_{logical_name}")
        actual = live.get(physical_name)
        if actual is None:
            errors.append(f"{physical_name} is missing")
            continue
        expected_driver = expected.get("driver", "bridge")
        if actual.get("Driver") != expected_driver:
            errors.append(f"{physical_name} driver differs")
        expected_internal = bool(expected.get("internal", False))
        if bool(actual.get("Internal")) != expected_internal:
            errors.append(f"{physical_name} internal flag differs")
        expected_subnets = {
            item["subnet"]
            for item in expected.get("ipam", {}).get("config", [])
            if item.get("subnet")
        }
        if expected_subnets and _subnets(actual) != expected_subnets:
            errors.append(
                f"{physical_name} subnets are {sorted(_subnets(actual))!r}; "
                f"expected {sorted(expected_subnets)!r}"
            )
    return errors


def inspect_live_networks(compose: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    project = compose.get("name", "mykhaya")
    declared = compose.get("networks", {})
    names = {
        expected.get("name", f"{project}_{logical_name}")
        for logical_name in NETWORKS
        for expected in [declared.get(logical_name, {})]
    }
    result: dict[str, dict[str, Any] | None] = {}
    for name in names:
        inspected = subprocess.run(
            ["docker", "network", "inspect", name], capture_output=True, text=True, check=False
        )
        if inspected.returncode != 0:
            result[name] = None
            continue
        try:
            result[name] = json.loads(inspected.stdout)[0]
        except (IndexError, json.JSONDecodeError):
            result[name] = None
    return result


def main() -> int:
    try:
        compose = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Cannot parse merged Compose configuration: {exc}", file=sys.stderr)
        return 2
    differences = compare_networks(compose, inspect_live_networks(compose))
    if differences:
        print("Development network drift detected:", file=sys.stderr)
        for difference in differences:
            print(f"- {difference}", file=sys.stderr)
        return 1
    print("Development network definitions match the merged Compose configuration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
