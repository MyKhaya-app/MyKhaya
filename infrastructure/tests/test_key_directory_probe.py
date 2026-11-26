"""F-03: protected key-directory validation through the service-identity probe.

The field keyrings and the Apple signing key are readable only by the
containers' service identity (10001:10001), never by the deployment account,
so the validator inspects them from a locked-down probe container. Unit tests
use synthetic probe results; the integration tests run the real probe against
synthetic fixtures created with real ownership inside the Docker host. No key
is real and nothing here ever reads key contents.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "service_env_contract_probe", ROOT / "infrastructure/scripts/service_env_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules["service_env_contract_probe"] = contract
SPEC.loader.exec_module(contract)

POSIX = os.name == "posix"
FIELD = "MYKHAYA_FIELD_KEYS_HOST_DIR"
APPLE = "MYKHAYA_APPLE_KEY_HOST_DIR"
SVC = contract.SERVICE_UID
DEPLOY_UID = 1000
LEAK_MARKER = "SYNTHETIC-DOCKER-STDERR-DETAIL"


def entry(name: str, kind: str = "file", mode: int = 0o440, uid: int = 0, gid: int = SVC,
          readable: bool = True, inode: int = 7) -> contract.KeyEntry:
    return contract.KeyEntry(name, kind, mode, uid, gid, inode, readable)


def listing(root: contract.KeyEntry | None, entries, *, ids=(SVC, SVC), error=None):
    return contract.KeyDirListing(ids[0], ids[1], (ids[1],), root,
                                  None if entries is None else tuple(entries), error)


# The intended DEV layout (see the migration runbook).
def dev_field_keys() -> contract.KeyDirListing:
    return listing(entry(".", "directory", 0o750, 0, SVC),
                   [entry("blind-index-keys.json"), entry("field-encryption-keys.json")])


def dev_apple() -> contract.KeyDirListing:
    return listing(entry(".", "directory", 0o700, SVC, SVC),
                   [entry("AuthKey_SYNTHETIC.p8", mode=0o600, uid=SVC, gid=SVC)])


class KeyDirectoryCase(unittest.TestCase):
    """Runs check_key_directory against a real (empty) host directory whose
    contents the synthetic probe describes."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="mykhaya-keyprobe-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.dir = self.base / "keys"
        self.dir.mkdir()
        patcher = mock.patch.object(contract, "_deployment_uid", return_value=DEPLOY_UID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, result, *, path: Path | None = None, referenced=()) -> list[str]:
        path = path or self.dir
        calls = []

        def probe(source):
            calls.append(source)
            if isinstance(result, Exception):
                raise result
            if result.root is None:
                return result
            root = result.root
            inode = path.lstat().st_ino
            return contract.KeyDirListing(
                result.uid, result.gid, result.groups,
                contract.KeyEntry(root.name, root.kind, root.mode, root.uid, root.gid, inode,
                                  root.readable),
                result.entries, result.error)

        report = contract.Report()
        contract.check_key_directory(FIELD, path, probe, report, set(referenced))
        self.calls = calls
        return report.errors

    def assertOnly(self, errors: list[str], fragment: str) -> None:
        self.assertTrue(errors, "expected a rejection")
        self.assertTrue(all(fragment in e for e in errors), errors)


class DevLayoutTests(KeyDirectoryCase):
    def test_existing_dev_field_key_layout_is_accepted(self):
        self.assertEqual(self.check(dev_field_keys(), referenced={"field-encryption-keys.json"}),
                         [])

    def test_existing_dev_apple_layout_is_accepted(self):
        self.assertEqual(self.check(dev_apple()), [])

    def test_root_group_and_root_owned_files_are_accepted_when_readable(self):
        self.assertEqual(self.check(listing(entry(".", "directory", 0o750, 0, 0),
                                            [entry("k.json", mode=0o640, uid=SVC, gid=0)])), [])

    def test_host_listing_is_never_needed(self):
        # The deployment account cannot list the real directories; only lstat
        # of the directory itself happens on the host.
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError(13, "denied")):
            self.assertEqual(self.check(dev_field_keys()), [])
        self.assertEqual(self.calls, [str(self.dir)])

    @unittest.skipUnless(POSIX and hasattr(os, "geteuid") and os.geteuid() != 0,
                         "needs an unprivileged POSIX account")
    def test_restricted_directory_validates_as_an_unprivileged_account(self):
        os.chmod(self.dir, 0)  # like 0750 root:10001 seen by the deployment account
        self.addCleanup(os.chmod, self.dir, 0o700)
        with self.assertRaises(PermissionError):
            list(self.dir.iterdir())
        self.assertEqual(self.check(dev_field_keys()), [])


class OwnershipTests(KeyDirectoryCase):
    def test_deployment_account_ownership_is_rejected(self):
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", uid=DEPLOY_UID)]))
        self.assertOnly(errors, "is owned by the deployment account (UID 1000)")
        errors = self.check(listing(entry(".", "directory", 0o750, DEPLOY_UID, SVC),
                                    [entry("k.json")]))
        self.assertOnly(errors, f"{FIELD}: is owned by the deployment account")

    def test_deployment_account_is_rejected_even_if_it_were_the_service_uid(self):
        with mock.patch.object(contract, "_deployment_uid", return_value=SVC):
            errors = self.check(dev_apple())
        self.assertTrue(any("deployment account" in e for e in errors), errors)

    def test_arbitrary_owner_and_group_are_rejected(self):
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", uid=1234)]))
        self.assertOnly(errors, "is owned by untrusted UID 1234")
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", gid=DEPLOY_UID)]))
        self.assertOnly(errors, "has untrusted group GID 1000")
        errors = self.check(listing(entry(".", "directory", 0o750, 0, 999), [entry("k.json")]))
        self.assertOnly(errors, "has untrusted group GID 999")


class ModeTests(KeyDirectoryCase):
    def assertFileModeRejected(self, mode: int, fragment: str) -> None:
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", mode=mode)]))
        self.assertTrue(any(fragment in e for e in errors), (oct(mode), errors))

    def test_insecure_file_modes_are_rejected(self):
        self.assertFileModeRejected(0o444, "readable by other users")
        self.assertFileModeRejected(0o441, "readable by other users")
        self.assertFileModeRejected(0o460, "writable by its group")
        self.assertFileModeRejected(0o442, "writable by other users")
        self.assertFileModeRejected(0o4440, "setuid/setgid")

    def test_insecure_directory_modes_are_rejected(self):
        for mode, fragment in ((0o755, "readable by other users"), (0o751, "readable by other"),
                               (0o770, "writable by its group"), (0o757, "writable by other")):
            errors = self.check(listing(entry(".", "directory", mode, 0, SVC),
                                        [entry("k.json")]))
            self.assertTrue(any(f"{FIELD}: is {fragment}" in e for e in errors), (oct(mode), errors))

    def test_secure_modes_are_accepted(self):
        for mode in (0o400, 0o440, 0o600, 0o640):
            errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                        [entry("k.json", mode=mode, uid=SVC)]))
            self.assertEqual(errors, [], oct(mode))

    def test_mode_alone_is_not_enough_the_service_must_have_access(self):
        # 0400 root:10001 has no insecure bits but the service cannot read it.
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", mode=0o400, readable=False)]))
        self.assertOnly(errors, "is not readable by the service account (10001:10001)")


class SymlinkAndTypeTests(KeyDirectoryCase):
    def test_symlinked_entries_are_rejected(self):
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("k.json", kind="symlink", mode=0o777, uid=DEPLOY_UID,
                                           readable=False)]))
        self.assertEqual(errors, [f"{FIELD}/k.json: must not be a symbolic link"])

    def test_unexpected_file_types_are_rejected(self):
        for kind in ("directory", "other"):
            errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                        [entry("nested", kind=kind, mode=0o750)]))
            self.assertOnly(errors, "unexpected file type")

    def test_symlinked_key_directory_is_rejected_on_the_host(self):
        link = self.base / "link"
        try:
            link.symlink_to(self.dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links cannot be created here")
        errors = self.check(dev_field_keys(), path=link)
        self.assertEqual(errors, [f"compose.env: {FIELD}: must not be a symbolic link"])
        self.assertEqual(self.calls, [])  # the probe never mounts a link


class MissingAndUnreadableTests(KeyDirectoryCase):
    def test_missing_directory_is_rejected(self):
        errors = self.check(dev_field_keys(), path=self.base / "absent")
        self.assertEqual(errors, [f"compose.env: {FIELD} does not exist on this host"])

    def test_regular_file_instead_of_directory_is_rejected(self):
        not_dir = self.base / "file"
        not_dir.write_text("synthetic", encoding="utf-8")
        self.assertEqual(self.check(dev_field_keys(), path=not_dir),
                         [f"compose.env: {FIELD}: is not a directory"])

    def test_empty_directory_is_rejected(self):
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC), []))
        self.assertOnly(errors, "is empty; the services would find no keys")

    def test_directory_the_service_cannot_list_is_rejected(self):
        errors = self.check(listing(entry(".", "directory", 0o700, 0, 0, readable=False), None,
                                    error="denied"))
        self.assertOnly(errors, "is not listable by the service account")

    def test_referenced_key_file_must_be_present(self):
        errors = self.check(dev_field_keys(), referenced={"field-encryption-keys.json",
                                                          "missing-keys.json"})
        self.assertOnly(errors, "missing-keys.json is named by a *_FILE setting")

    def test_vanished_mount_is_reported(self):
        errors = self.check(listing(None, None, error="missing"))
        self.assertOnly(errors, "the mounted directory was missing")

    @unittest.skipUnless(POSIX and hasattr(os, "geteuid") and os.geteuid() != 0,
                         "needs an unprivileged POSIX account")
    def test_parent_denying_the_deployment_account_is_reported_without_traceback(self):
        os.chmod(self.base, 0)
        self.addCleanup(os.chmod, self.base, 0o700)
        errors = self.check(dev_field_keys())
        self.assertTrue(any("does not exist" in e or "denies the deployment account" in e
                            for e in errors), errors)


class ProbeIntegrityTests(KeyDirectoryCase):
    def test_no_probe_fails_closed(self):
        report = contract.Report()
        contract.check_key_directory(FIELD, self.dir, None, report, set())
        self.assertEqual(report.errors, [(f"compose.env: {FIELD}: cannot be verified: no API "
                                          "image was given for the key-directory probe "
                                          "(--probe-image)")])

    def test_probe_failure_fails_closed(self):
        errors = self.check(contract.ProbeFailure("the Docker daemon is not reachable"))
        self.assertEqual(errors, [(f"compose.env: {FIELD}: cannot be verified: the Docker "
                                   "daemon is not reachable")])

    def test_probe_must_run_as_the_service_identity(self):
        result = dev_field_keys()
        errors = self.check(contract.KeyDirListing(0, 0, (0,), result.root, result.entries))
        self.assertOnly(errors, "the probe did not run as 10001:10001")

    def test_probe_must_have_mounted_the_same_directory(self):
        report = contract.Report()
        contract.check_key_directory(FIELD, self.dir, lambda _: dev_field_keys(), report, set())
        self.assertEqual(len(report.errors), 1)
        self.assertIn("the probe saw a different directory", report.errors[0])

    def test_entry_names_are_sanitised(self):
        errors = self.check(listing(entry(".", "directory", 0o750, 0, SVC),
                                    [entry("bad\nname" + "x" * 100, mode=0o444)]))
        self.assertTrue(errors)
        for error in errors:
            self.assertNotIn("\n", error)
            self.assertLess(len(error), 220)


def completed(cmd, code=0, out="", err=""):
    return subprocess.CompletedProcess(cmd, code, out, err)


class FakeDocker:
    def __init__(self, *, user='"10001:10001"', inspect_code=0, inspect_err="",
                 probe_out=None, probe_code=0, probe_err="", raises=None, timeout=False):
        self.calls: list[list[str]] = []
        self.user, self.inspect_code, self.inspect_err = user, inspect_code, inspect_err
        self.probe_code, self.probe_err = probe_code, probe_err
        self.probe_out = probe_out if probe_out is not None else json.dumps(
            {"uid": SVC, "gid": SVC, "groups": [SVC],
             "root": {"name": ".", "kind": "directory", "mode": 0o750, "uid": 0, "gid": SVC,
                      "inode": 7, "readable": True},
             "entries": [{"name": "k.json", "kind": "file", "mode": 0o440, "uid": 0,
                          "gid": SVC, "inode": 8, "readable": True}]})
        self.raises, self.timeout = raises, timeout

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        self.kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        if cmd[:3] == ["docker", "image", "inspect"]:
            return completed(cmd, self.inspect_code, self.user + "\n", self.inspect_err)
        if cmd[:2] == ["docker", "run"]:
            if self.timeout:
                raise subprocess.TimeoutExpired(cmd, contract.PROBE_TIMEOUT_SECONDS)
            return completed(cmd, self.probe_code, self.probe_out, self.probe_err)
        return completed(cmd)


class DockerProbeUnitTests(unittest.TestCase):
    IMAGE = "mykhaya-api:latest"

    def run_probe(self, fake: FakeDocker, source: str = "/etc/mykhaya/field-keys"):
        return contract.docker_key_dir_probe(self.IMAGE, run=fake)(source)

    def assertFails(self, fake: FakeDocker, fragment: str, source="/etc/mykhaya/field-keys"):
        with self.assertRaises(contract.ProbeFailure) as caught:
            self.run_probe(fake, source)
        message = str(caught.exception)
        self.assertIn(fragment, message)
        self.assertNotIn(LEAK_MARKER, message)
        return message

    def test_command_is_locked_down_and_mounts_only_the_key_directory(self):
        fake = FakeDocker()
        result = self.run_probe(fake)
        self.assertEqual(result.entries[0].name, "k.json")
        inspect, run = fake.calls
        self.assertEqual(inspect[:3], ["docker", "image", "inspect"])
        options = run[: run.index(self.IMAGE)]
        for flag in (["--rm"], ["--pull", "never"], ["--network", "none"], ["--read-only"],
                     ["--cap-drop", "ALL"], ["--security-opt", "no-new-privileges"],
                     ["--user", "10001:10001"], ["--entrypoint", "python"]):
            self.assertTrue(any(options[i:i + len(flag)] == flag for i in range(len(options))),
                            flag)
        mounts = [options[i + 1] for i, o in enumerate(options) if o == "--mount"]
        self.assertEqual(mounts, ["type=bind,source=/etc/mykhaya/field-keys,target=/probe,readonly"])
        for forbidden in ("-v", "--volume", "-e", "--env", "--env-file", "--privileged",
                          "--cap-add", "--network=host", "--pid", "--ipc", "--volumes-from"):
            self.assertNotIn(forbidden, options)
        self.assertEqual(run[run.index(self.IMAGE) + 1:-1], ["-I", "-S", "-B", "-c"])
        self.assertIn("timeout", fake.kwargs)

    def test_probe_script_never_opens_files_or_follows_links(self):
        script = contract.PROBE_SCRIPT
        self.assertNotRegex(script, r"\bopen\(|read_text|read_bytes|\.read\(|os\.stat\(")
        self.assertNotIn("realpath", script)
        self.assertIn("os.lstat(path)", script)

    def test_image_is_verified_once_against_the_service_identity(self):
        fake = FakeDocker()
        probe = contract.docker_key_dir_probe(self.IMAGE, run=fake)
        probe("/a")
        probe("/b")
        self.assertEqual(sum(c[:3] == ["docker", "image", "inspect"] for c in fake.calls), 1)
        for user in ('"0:0"', '""', '"10001"', '"mykhaya"', "not json"):
            self.assertFails(FakeDocker(user=user), "does not run as the expected service "
                                                    "identity 10001:10001")

    def test_missing_image_fails_closed_without_pulling(self):
        message = self.assertFails(
            FakeDocker(inspect_code=1, inspect_err=f"Error: No such image: x {LEAK_MARKER}"),
            "not available locally")
        self.assertIn("never pulls", message)

    def test_docker_errors_are_sanitised(self):
        self.assertFails(FakeDocker(raises=FileNotFoundError("docker")), "Docker is unavailable")
        self.assertFails(FakeDocker(inspect_code=1, inspect_err="Cannot connect to the Docker "
                                    f"daemon {LEAK_MARKER}"), "Docker daemon is not reachable")
        self.assertFails(FakeDocker(probe_code=125, probe_err="invalid mount config: bind source "
                                    f"path does not exist: {LEAK_MARKER}"),
                         "not visible to the Docker daemon")
        self.assertFails(FakeDocker(probe_code=1, probe_err=f"Traceback {LEAK_MARKER}"),
                         "the probe container failed")

    def test_timeout_removes_the_container(self):
        fake = FakeDocker(timeout=True)
        self.assertFails(fake, "timed out")
        removal = fake.calls[-1]
        self.assertEqual(removal[:3], ["docker", "rm", "-f"])
        self.assertRegex(removal[3], r"^mykhaya-keydir-probe-\d+-[0-9a-f]{8}$")
        self.assertIn(removal[3], fake.calls[1])

    def test_unexpected_output_fails_closed(self):
        good = json.loads(FakeDocker().probe_out)
        bad_outputs = ["", "not json", "[]", json.dumps({**good, "uid": "10001"}),
                       json.dumps({**good, "error": "other"}),
                       json.dumps({k: v for k, v in good.items() if k != "root"}),
                       json.dumps({**good, "entries": [{**good["entries"][0], "name": "../x"}]}),
                       json.dumps({**good, "entries": [{**good["entries"][0], "kind": "pipe"}]}),
                       json.dumps({**good, "entries": [{**good["entries"][0], "mode": -1}]}),
                       json.dumps({**good, "entries": [{**good["entries"][0], "readable": 1}]}),
                       json.dumps({**good, "root": {**good["root"], "name": "x"}})]
        for output in bad_outputs:
            self.assertFails(FakeDocker(probe_out=output), "unexpected output")

    def test_unsafe_image_and_path_arguments_are_refused(self):
        for image in ("--privileged", "", "image name", "a" * 300):
            with self.assertRaises(contract.ProbeFailure):
                contract.docker_key_dir_probe(image, run=FakeDocker())
        for source in ("relative/dir", "/etc/a,readonly=false", '/etc/"x', "/etc/a\nb"):
            fake = FakeDocker()
            self.assertFails(fake, "cannot be passed safely", source)
            self.assertEqual(fake.calls, [])

    @unittest.skipUnless(POSIX and hasattr(os, "getuid"), "the probe script targets Linux")
    def test_probe_script_output_parses(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "k.json").write_text("synthetic", encoding="utf-8")
            os.symlink("/nonexistent", Path(directory, "link"))
            script = contract.PROBE_SCRIPT.replace('"/probe', '"' + directory)
            out = subprocess.run([sys.executable, "-I", "-S", "-c", script], capture_output=True,
                                 text=True, check=True).stdout
        parsed = contract.parse_probe_output(out)
        self.assertEqual({e.name: e.kind for e in parsed.entries},
                         {"k.json": "file", "link": "symlink"})
        self.assertNotIn("synthetic", out)


class ValidatorWiringTests(unittest.TestCase):
    def synthetic_root(self) -> Path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import synthetic_dev_config as synthetic

        base = Path(tempfile.mkdtemp(prefix="mykhaya-keyprobe-cli-"))
        self.addCleanup(shutil.rmtree, base, True)
        return synthetic.write_synthetic_root(base)

    def test_seven_file_validation_without_a_probe_fails_closed(self):
        report = contract.validate_root(self.synthetic_root(), repo_root=ROOT, check_perms=True)
        for key in (FIELD, APPLE):
            self.assertIn(f"compose.env: {key}: cannot be verified: no API image was given for "
                          "the key-directory probe (--probe-image)", report.errors)

    @unittest.skipUnless(POSIX, "the command line checks permissions only on POSIX")
    def test_command_line_reports_probe_failure_without_traceback(self):
        import contextlib
        import io

        root = self.synthetic_root()
        failing = FakeDocker(inspect_code=1, inspect_err=f"No such image {LEAK_MARKER}")
        stderr = io.StringIO()
        real = contract.docker_key_dir_probe
        with mock.patch.object(contract, "docker_key_dir_probe",
                               lambda image: real(image, run=failing)), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = contract.main(["--root", str(root), "--repo-root", str(ROOT),
                                  "--probe-image", "mykhaya-api:latest"])
        self.assertEqual(code, 1)
        output = stderr.getvalue()
        self.assertIn("the API image is not available locally", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn(LEAK_MARKER, output)

    def test_deploy_script_passes_the_api_image_and_never_skips(self):
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        block = script[script.index("validate_service_env() {"): script.index("check_resolved_"
                                                                             "service_env() {")]
        self.assertIn('--probe-image "$probe_image"', block)
        self.assertNotIn("--skip-permissions", block)
        self.assertIn('print(api.get("image") or model["name"] + "-api")', block)

    @unittest.skipUnless(POSIX, "POSIX permission semantics")
    def test_environment_files_keep_their_own_ownership_policy(self):
        # The generated files stay owned by the deployment account; the stricter
        # key-material policy applies only inside the key directories.
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory, "api.env")
            env_file.write_text("MYKHAYA_ENVIRONMENT=development\n", encoding="utf-8")
            os.chmod(env_file, 0o600)
            report = contract.Report()
            contract.check_permissions(env_file, secret=True, is_dir=False, report=report)
            self.assertEqual(report.errors, [])


# --- Real probe containers ------------------------------------------------------

IMAGE = os.environ.get("MYKHAYA_PROBE_TEST_IMAGE", "mykhaya-api:latest")
FIXTURE = re.compile(r"mykhaya-keyprobe-it-[0-9a-f]{12}")
OUTSIDE_MARKER = "SYNTHETIC-OUTSIDE-MARKER"

# Runs as root in a throwaway container to create synthetic fixtures with real
# ownership inside the Docker host's filesystem. Nothing here is a key.
FIXTURE_SCRIPT = """
set -eu
w=/work
mkdir -p $w/field-keys $w/apple $w/bad-owner $w/unreadable $w/closed $w/links $w/outside \
  $w/world $w/empty $w/nested/sub
for f in field-encryption-keys.json blind-index-keys.json; do
  printf 'synthetic keyring placeholder\\n' > $w/field-keys/$f
done
chown -R 0:10001 $w/field-keys && chmod 0750 $w/field-keys && chmod 0440 $w/field-keys/*
printf 'synthetic signing key placeholder\\n' > $w/apple/AuthKey_SYNTHETIC.p8
chown -R 10001:10001 $w/apple && chmod 0700 $w/apple && chmod 0600 $w/apple/AuthKey_SYNTHETIC.p8
printf 'synthetic\\n' > $w/bad-owner/k.json
chown 0:10001 $w/bad-owner && chmod 0750 $w/bad-owner
chown 1000:10001 $w/bad-owner/k.json && chmod 0440 $w/bad-owner/k.json
printf 'synthetic\\n' > $w/unreadable/k.json
chown 0:10001 $w/unreadable && chmod 0750 $w/unreadable
chown 0:0 $w/unreadable/k.json && chmod 0400 $w/unreadable/k.json
printf 'synthetic\\n' > $w/closed/k.json
chown -R 0:0 $w/closed && chmod 0700 $w/closed
printf '%s\\n' "$MARKER" > $w/outside/secret.txt && chmod 0444 $w/outside/secret.txt
ln -s /work/outside/secret.txt $w/links/absolute
ln -s ../outside/secret.txt $w/links/relative
ln -s / $w/links/root
chown -h 0:10001 $w/links $w/links/* && chmod 0750 $w/links
printf 'synthetic\\n' > $w/world/k.json
chown -R 0:10001 $w/world && chmod 0755 $w/world && chmod 0444 $w/world/k.json
chown 0:10001 $w/empty && chmod 0750 $w/empty
chown -R 0:10001 $w/nested && chmod 0750 $w/nested $w/nested/sub
"""

# Run with the probe's exact command line to prove the restrictions hold.
SECURITY_SCRIPT = """
import json, os
def attempt(fn):
    try:
        fn()
        return "ok"
    except OSError as exc:
        return exc.errno
status = dict(line.split(":\\t", 1) for line in open("/proc/self/status").read().splitlines()
              if ":\\t" in line)
mounts = [line.split() for line in open("/proc/self/mountinfo")]
print(json.dumps({
    "ids": [os.getuid(), os.getgid(), sorted(os.getgroups())],
    "cap_eff": status["CapEff"].strip(), "cap_prm": status["CapPrm"].strip(),
    "cap_bnd": status["CapBnd"].strip(), "no_new_privs": status["NoNewPrivs"].strip(),
    "net": sorted(os.listdir("/sys/class/net")),
    "write_rootfs": attempt(lambda: open("/probe-write-test", "w").close()),
    "write_tmp": attempt(lambda: open("/tmp/probe-write-test", "w").close()),
    "write_mount": attempt(lambda: open("/probe/probe-write-test", "w").close()),
    "follow_absolute": attempt(lambda: open("/probe/absolute").read()),
    "follow_relative": attempt(lambda: open("/probe/relative").read()),
    "host_paths_visible": [p for p in ("/work", "/outside", "/work/outside/secret.txt",
                                       "/var/run/docker.sock") if os.path.exists(p)],
    "probe_mount": [m[5] for m in mounts if m[4] == "/probe"],
    "other_bind_mounts": [m[4] for m in mounts if m[4].startswith(("/etc/mykhaya", "/home",
                                                                  "/root", "/work"))],
    "env": sorted(os.environ),
}))
"""


def docker_image_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "image", "inspect", "--format",
                                 "{{json .Config.User}}", IMAGE], capture_output=True,
                                text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == '"10001:10001"'


@unittest.skipUnless(docker_image_ready(), f"needs Docker and the locally built {IMAGE}")
class RealProbeTests(unittest.TestCase):
    """Fixtures live in the Docker host's /tmp so the bind mounts see real
    ownership even when the tests run on a Docker Desktop client."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.name = f"mykhaya-keyprobe-it-{secrets.token_hex(6)}"
        assert FIXTURE.fullmatch(cls.name)
        cls.base = f"/tmp/{cls.name}"
        result = subprocess.run(
            ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0",
             "--mount", "type=bind,source=/tmp,target=/hosttmp",
             "--entrypoint", "sh", IMAGE, "-c", f"mkdir -m 0755 /hosttmp/{cls.name}"],
            capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise unittest.SkipTest("the Docker host's /tmp cannot be used for fixtures")
        result = subprocess.run(
            ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0",
             "-e", f"MARKER={OUTSIDE_MARKER}",
             "--mount", f"type=bind,source={cls.base},target=/work",
             "--entrypoint", "sh", IMAGE, "-c", FIXTURE_SCRIPT],
            capture_output=True, text=True, check=False)
        if result.returncode != 0:
            cls.tearDownClass()
            raise RuntimeError("synthetic fixture setup failed")
        cls.probe = staticmethod(contract.docker_key_dir_probe(IMAGE))

    @classmethod
    def tearDownClass(cls) -> None:
        assert FIXTURE.fullmatch(cls.name)
        subprocess.run(
            ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--user", "0:0",
             "--mount", "type=bind,source=/tmp,target=/hosttmp",
             "--entrypoint", "rm", IMAGE, "-rf", "--", f"/hosttmp/{cls.name}"],
            capture_output=True, text=True, check=False)

    def errors_for(self, sub: str) -> list[str]:
        result = self.probe(f"{self.base}/{sub}")
        report = contract.Report()
        self.assertEqual((result.uid, result.gid), (SVC, SVC))
        with mock.patch.object(contract, "_deployment_uid", return_value=DEPLOY_UID):
            contract.check_key_material(result.root, sub, report, directory=True,
                                        deployment_uid=DEPLOY_UID)
            for item in result.entries or ():
                contract.check_key_material(item, f"{sub}/{item.name}", report,
                                            directory=False, deployment_uid=DEPLOY_UID)
            if result.entries == ():
                report.error(f"{sub}: is empty")
        return report.errors

    def test_dev_layouts_are_accepted(self):
        self.assertEqual(self.errors_for("field-keys"), [])
        self.assertEqual(self.errors_for("apple"), [])
        names = {e.name: (e.uid, e.gid, e.mode) for e in self.probe(f"{self.base}/apple").entries}
        self.assertEqual(names, {"AuthKey_SYNTHETIC.p8": (SVC, SVC, 0o600)})

    def test_wrong_owner_insecure_modes_and_access_are_rejected(self):
        self.assertTrue(any("deployment account" in e for e in self.errors_for("bad-owner")))
        unreadable = self.errors_for("unreadable")
        self.assertTrue(any("not readable by the service account" in e for e in unreadable))
        world = self.errors_for("world")
        self.assertTrue(any("readable by other users" in e for e in world), world)
        self.assertTrue(any("unexpected file type" in e for e in self.errors_for("nested")))
        self.assertEqual(self.errors_for("empty"), ["empty: is empty"])

    def test_directory_closed_to_the_service_is_reported_not_raised(self):
        result = self.probe(f"{self.base}/closed")
        self.assertEqual(result.error, "denied")
        self.assertIsNone(result.entries)
        self.assertFalse(result.root.readable)

    def test_symlinks_are_reported_and_never_followed(self):
        result = self.probe(f"{self.base}/links")
        kinds = {e.name: (e.kind, e.readable) for e in result.entries}
        self.assertEqual(kinds, {"absolute": ("symlink", False), "relative": ("symlink", False),
                                 "root": ("symlink", False)})
        self.assertTrue(all("symbolic link" in e for e in self.errors_for("links")[0:3]))

    def test_missing_directory_fails_closed(self):
        with self.assertRaises(contract.ProbeFailure) as caught:
            self.probe(f"{self.base}/does-not-exist")
        self.assertNotIn(self.name, str(caught.exception))

    def test_runtime_restrictions_hold(self):
        name = f"mykhaya-keydir-probe-test-{secrets.token_hex(4)}"
        command = contract.probe_command(IMAGE, f"{self.base}/links", name, SECURITY_SCRIPT)
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        facts = json.loads(result.stdout)
        self.assertEqual(facts["ids"], [SVC, SVC, [SVC]])
        for capability in ("cap_eff", "cap_prm", "cap_bnd"):
            self.assertEqual(int(facts[capability], 16), 0, capability)
        self.assertEqual(facts["no_new_privs"], "1")
        self.assertEqual(facts["net"], ["lo"])
        self.assertEqual(facts["write_rootfs"], 30)  # EROFS
        self.assertEqual(facts["write_tmp"], 30)
        self.assertEqual(facts["write_mount"], 30)
        self.assertEqual(facts["follow_absolute"], 2)  # ENOENT: the target is not mounted
        self.assertEqual(facts["follow_relative"], 2)
        self.assertEqual(facts["host_paths_visible"], [])
        self.assertEqual(len(facts["probe_mount"]), 1)
        self.assertIn("ro", facts["probe_mount"][0].split(","))
        self.assertEqual(facts["other_bind_mounts"], [])
        image_env = json.loads(subprocess.run(
            ["docker", "image", "inspect", "--format", "{{json .Config.Env}}", IMAGE],
            capture_output=True, text=True, check=True).stdout)
        allowed = {item.split("=", 1)[0] for item in image_env} | {"HOSTNAME", "HOME", "LC_CTYPE"}
        self.assertEqual(sorted(set(facts["env"]) - allowed), [])
        self.assertNotIn(OUTSIDE_MARKER, result.stdout)


if __name__ == "__main__":
    unittest.main()
