"""Destructive regression tests for the backend-config probe's volume safety.

Only throwaway volumes are used (every name starts with f03vh). An "owner"
project creates volumes holding a marker and its containers are then removed:
the case in which Docker's "volume in use" protection no longer applies. The
real probe code (create, verify isolation, run, clean up) then runs in DEV and
PROD modes. No owner volume may be deleted or emptied, and the probe must
remove everything it created.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_backend_config_safety", ROOT / "infrastructure/scripts/validate_backend_config.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules["validate_backend_config_safety"] = module
SPEC.loader.exec_module(module)


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


@unittest.skipUnless(docker_available(), "Docker daemon is required")
class ProbeVolumeSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        tag = uuid.uuid4().hex[:8]
        self.owner = f"f03vh-owner-{tag}"
        self.names = {
            "fixed": f"f03vh_fixed_{tag}",  # like mykhaya_{dev,prod}_home_migration_data
            "explicit_default": f"{self.owner}_explicit_default",  # explicit == default pattern
            "plain": f"{self.owner}_plain",  # ordinary project-scoped volume
        }
        self.work = Path(tempfile.mkdtemp(prefix="f03vh-"))
        self.addCleanup(self.cleanup)

    def write_compose(self, extra_volume: str = "", command: str = "true") -> Path:
        keys = list(self.names) + ([extra_volume] if extra_volume else [])
        mounts = "".join(f'      - "{k}:/v/{k}"\n' for k in keys)
        services = "".join(
            f"  {s}:\n    image: alpine:3.20\n    network_mode: none\n"
            f"    command: [\"sh\", \"-c\", \"{command}\"]\n    volumes:\n{mounts}"
            for s in module.SERVICES
        )
        path = self.work / f"compose-{uuid.uuid4().hex[:6]}.yml"
        external = (f"  {extra_volume}: {{ external: true, name: {self.external} }}\n"
                    if extra_volume else "")
        path.write_text(
            f"services:\n{services}networks:\n  edge: {{}}\n  app: {{}}\n  data: {{}}\n"
            "volumes:\n"
            f"  fixed: {{ name: {self.names['fixed']} }}\n"
            f"  explicit_default: {{ name: {self.names['explicit_default']} }}\n"
            f"  plain: {{}}\n{external}",
            encoding="utf-8",
        )
        return path

    def cleanup(self) -> None:
        for name in [*self.names.values(), getattr(self, "external", "")]:
            if name.startswith("f03vh"):
                run("docker", "volume", "rm", "-f", name, check=False)
        shutil.rmtree(self.work, ignore_errors=True)

    def create_owner_volumes(self, compose: Path) -> None:
        run("docker", "compose", "-f", str(compose), "-p", self.owner, "run", "--rm", "--no-deps",
            "--entrypoint", "sh", "api", "-c",
            " && ".join(f"echo keep > /v/{k}/marker" for k in self.names))
        # The owner's containers are gone: only the probe's own safety remains.
        self.assertEqual(run("docker", "ps", "-aq", "--filter",
                             f"label=com.docker.compose.project={self.owner}").stdout.strip(), "")

    def probe_context(self, compose: Path, environment: dict[str, str]):
        resolved = json.loads(run("docker", "compose", "-f", str(compose), "-p", self.owner,
                                  "config", "--format", "json").stdout)
        with mock.patch.dict(os.environ, environment):
            os.environ.pop("MYKHAYA_DEV_CONFIG_ROOT", None)
            if "MYKHAYA_PRODUCTION" not in environment:
                os.environ.pop("MYKHAYA_PRODUCTION", None)
            context = module.create_probe_context(resolved)
        return module.ProbeContext(
            context.project_name,
            ("docker", "compose", "-f", str(compose), "-p", context.project_name, "-f",
             str(context.override_path)),
            context.override_path,
        )

    def assert_owner_volumes_intact(self) -> None:
        for key, name in self.names.items():
            marker = run("docker", "run", "--rm", "--network", "none", "-v", f"{name}:/v:ro",
                         "alpine:3.20", "cat", "/v/marker", check=False).stdout.strip()
            self.assertEqual(marker, "keep", f"{key} volume was deleted or emptied")

    def assert_probe_cleaned(self, project: str) -> None:
        self.assertEqual(module.probe_owned_existing_volumes(project), [])
        self.assertEqual(run("docker", "volume", "ls", "-q", "--filter",
                             f"name={project}").stdout.split(), [])

    def full_probe(self, environment: dict[str, str], command: str = "true") -> str:
        compose = self.write_compose(command=command)
        self.create_owner_volumes(compose)
        context = self.probe_context(compose, environment)
        try:
            module.verify_probe_isolation(context)
            result = run(*context.compose_args, "run", "--rm", "--no-deps", "api", check=False)
            # Every volume the probe touched is its own, labelled for its project.
            owned = module.probe_owned_existing_volumes(context.project_name)
            self.assertEqual(sorted(owned),
                             sorted(f"{context.project_name}_{k}" for k in self.names))
            return_code = result.returncode
        finally:
            module.cleanup_probe(context)
        self.assert_owner_volumes_intact()
        self.assert_probe_cleaned(context.project_name)
        return str(return_code)

    def test_dev_probe_never_deletes_application_volumes(self):
        self.full_probe({})

    def test_production_probe_never_deletes_application_volumes(self):
        self.full_probe({"MYKHAYA_PRODUCTION": "1"})

    def test_cleanup_after_failed_validation_removes_only_probe_resources(self):
        self.assertEqual(self.full_probe({}, command="exit 3"), "3")

    def test_external_volumes_fail_closed_and_stay_untouched(self):
        self.external = f"f03vh_external_{uuid.uuid4().hex[:8]}"
        run("docker", "volume", "create", self.external)
        run("docker", "run", "--rm", "--network", "none", "-v", f"{self.external}:/v",
            "alpine:3.20", "sh", "-c", "echo keep > /v/marker")
        compose = self.write_compose(extra_volume="shared")
        resolved = json.loads(run("docker", "compose", "-f", str(compose), "-p", self.owner,
                                  "config", "--format", "json").stdout)
        with self.assertRaises(module.ProbeIsolationError):
            module.create_probe_context(resolved)
        marker = run("docker", "run", "--rm", "--network", "none", "-v", f"{self.external}:/v:ro",
                     "alpine:3.20", "cat", "/v/marker").stdout.strip()
        self.assertEqual(marker, "keep")

    def test_pre_existing_probe_volume_name_is_refused_and_preserved(self):
        compose = self.write_compose()
        self.create_owner_volumes(compose)
        context = self.probe_context(compose, {})
        squatter = f"{context.project_name}_plain"
        run("docker", "volume", "create", squatter)  # not labelled for the probe
        try:
            with self.assertRaises(module.ProbeIsolationError) as raised:
                module.verify_probe_isolation(context)
            self.assertIn("volume plain already exists", str(raised.exception))
            module.cleanup_probe(context)
            self.assertEqual(run("docker", "volume", "inspect", squatter,
                                 check=False).returncode, 0, "unlabelled volume was removed")
        finally:
            run("docker", "volume", "rm", "-f", squatter, check=False)
        self.assert_owner_volumes_intact()


if __name__ == "__main__":
    unittest.main()
