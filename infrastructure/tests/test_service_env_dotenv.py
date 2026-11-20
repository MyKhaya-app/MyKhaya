"""Dotenv parsing, serialisation and splitting of multiline values (F-03).

The legacy DEV .env holds MYKHAYA_APNS_PRIVATE_KEY as a quoted multiline PEM
value, which Docker Compose supports. These tests pin the parser to Compose's
real behaviour (checked against the Compose CLI when available), prove values
survive splitting byte for byte, and prove malformed input is refused without
partial output or disclosure. Every key here is synthetic; the PEM-shaped
block deliberately is not labelled as a private key.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic_dev_config as synthetic  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "service_env_contract_dotenv", ROOT / "infrastructure/scripts/service_env_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules["service_env_contract_dotenv"] = contract
SPEC.loader.exec_module(contract)

# PEM-shaped synthetic key: real line structure, synthetic content.
SYNTHETIC_PEM = "\n".join([
    "-----BEGIN SYNTHETIC KEY-----",
    "MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQgSYNTHETICSYNTHETIC",
    "SYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETIC1+",
    "SYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHETIC2/",
    "SYNTHETIC3=",
    "-----END SYNTHETIC KEY-----",
])
SECRET_FRAGMENTS = ("MIGTAgEA", "SYNTHETICSYNTHETIC", "SYNTHETIC3=")

# Values every serialisation must round-trip exactly.
TRICKY_VALUES = {
    "PLAIN": "plain-value",
    "EMPTY": "",
    "JSON_LIST": '["10.77.0.250/32","10.77.1.250/32"]',
    "SPACES_INSIDE": "MyKhaya <hello@dev.mykhaya.app>",
    "LEADING_TRAILING": "  padded  ",
    "HASH_NO_SPACE": "a#b",
    "HASH_WITH_SPACE": "a #b",
    "DOLLARS": "p$ss$$word$",
    "BACKSLASHES": r"C:\path\n\t\\",
    "ESCAPED_NEWLINES_ONE_LINE": r"-----BEGIN X-----\nAAAA\n-----END X-----\n",
    "QUOTES": "it's \"quoted\"",
    "LEADING_QUOTE": "\"starts with a quote",
    "MULTILINE_PEM": SYNTHETIC_PEM,
    "TRAILING_NEWLINE": SYNTHETIC_PEM + "\n",
    "CRLF_INSIDE": "line1\r\nline2",
    "TAB": "a\tb",
    "UNICODE": "café ✓",
}


def compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    ).returncode == 0


def compose_env_file_values(env_file: Path) -> dict[str, str]:
    """What Compose itself loads from `env_file` (no secrets printed)."""
    compose = env_file.parent / "probe-compose.yml"
    compose.write_text(
        "name: dotenvprobe\nservices:\n  s:\n    image: alpine:3.20\n"
        f"    env_file: [{env_file.name}]\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
        capture_output=True, encoding="utf-8", cwd=env_file.parent, check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("MYKHAYA_")},
    )
    if result.returncode != 0:
        raise AssertionError("Compose rejected the file (details withheld)")
    environment = json.loads(result.stdout)["services"]["s"].get("environment") or {}
    # `compose config` prints each literal "$" as "$$".
    return {k: (v or "").replace("$$", "$") for k, v in environment.items()}


class ParsingTests(unittest.TestCase):
    def parse(self, text: str):
        return contract.parse_env_text(text, "test.env")

    def test_double_quoted_multiline_private_key(self):
        text = f'A=1\nMYKHAYA_APNS_PRIVATE_KEY="{SYNTHETIC_PEM}"\nB=2\n'
        values, problems = self.parse(text)
        self.assertEqual(problems, [])
        self.assertEqual(values["MYKHAYA_APNS_PRIVATE_KEY"], SYNTHETIC_PEM)
        self.assertEqual(values["A"], "1")
        self.assertEqual(values["B"], "2")  # parsing resumes after the closing quote

    def test_single_quoted_multiline_private_key(self):
        values, problems = self.parse(f"K='{SYNTHETIC_PEM}'\n")
        self.assertEqual(problems, [])
        self.assertEqual(values["K"], SYNTHETIC_PEM)

    def test_compose_escape_semantics(self):
        text = (
            'DQ="a\\nb\\tc\\rd\\\\e\\"f\\$g$$h\\xi"\n'
            "SQ='a\\nb\\\\c\\'d$e'\n"
            "UNQ=a\\nb$$c   # comment\n"
            "HASH=a#b\n"
            "export EXPORTED=yes\n"
        )
        values, problems = self.parse(text)
        self.assertEqual(problems, [])
        self.assertEqual(values["DQ"], 'a\nb\tc\rd\\e"f$g$h\\xi')
        self.assertEqual(values["SQ"], "a\\nb\\\\c'd$e")
        self.assertEqual(values["UNQ"], "a\\nb$c")
        self.assertEqual(values["HASH"], "a#b")
        self.assertEqual(values["EXPORTED"], "yes")

    def test_existing_one_line_credentials_and_ordinary_lines_are_unchanged(self):
        text = (
            "# comment\n\n"
            "MYKHAYA_FCM_PRIVATE_KEY=-----BEGIN X-----\\nAAAA\\n-----END X-----\\n\n"
            "MYKHAYA_SMTP_PASSWORD=plain-secret-value\n"
            'MYKHAYA_CORS_ORIGINS=["https://dev.mykhaya.app"]\n'
            "MYKHAYA_EMAIL_FROM=MyKhaya <hello@dev.mykhaya.app>\n"
            "QUOTED=\"one line\"\r\n"
        )
        values, problems = self.parse(text)
        self.assertEqual(problems, [])
        self.assertEqual(values["MYKHAYA_FCM_PRIVATE_KEY"],
                         "-----BEGIN X-----\\nAAAA\\n-----END X-----\\n")  # literal \n kept
        self.assertEqual(values["MYKHAYA_SMTP_PASSWORD"], "plain-secret-value")
        self.assertEqual(values["MYKHAYA_CORS_ORIGINS"], '["https://dev.mykhaya.app"]')
        self.assertEqual(values["MYKHAYA_EMAIL_FROM"], "MyKhaya <hello@dev.mykhaya.app>")
        self.assertEqual(values["QUOTED"], "one line")

    def assertRefusedWithoutDisclosure(self, text: str, fragment: str) -> list[str]:
        _, problems = self.parse(text)
        self.assertTrue(any(fragment in p for p in problems), problems)
        for problem in problems:
            for secret in SECRET_FRAGMENTS:
                self.assertNotIn(secret, problem)
        return problems

    def test_unterminated_quotes_are_refused(self):
        self.assertRefusedWithoutDisclosure(
            f'A=1\nMYKHAYA_APNS_PRIVATE_KEY="{SYNTHETIC_PEM}\nB=2\n',
            "line 2: MYKHAYA_APNS_PRIVATE_KEY has an unterminated double-quoted value")
        self.assertRefusedWithoutDisclosure(
            f"K='{SYNTHETIC_PEM}\n", "K has an unterminated single-quoted value")

    def test_unquoted_multiline_key_is_refused_and_never_read_as_names(self):
        # Compose silently keeps only the first line here; the parser refuses
        # the whole block. "SYNTHETIC3=" ends in base64 padding and must not
        # become a variable name, because names appear in reports.
        values, problems = self.parse(f"MYKHAYA_APNS_PRIVATE_KEY={SYNTHETIC_PEM}\nB=2\n")
        self.assertEqual(problems, [(
            "test.env lines 1-6: MYKHAYA_APNS_PRIVATE_KEY is an unquoted multiline value "
            "(Compose keeps only its first line); enclose the whole value in double quotes")])
        self.assertEqual(values, {"B": "2"})

    def test_other_stray_lines_are_reported_individually_not_attached(self):
        values, problems = self.parse("A=1\nsome stray text\nlowercase_name=x\nB=2\n")
        self.assertEqual(values, {"A": "1", "B": "2"})
        self.assertEqual([p.split(":")[0] for p in problems],
                         ["test.env line 2", "test.env line 3"])
        self.assertTrue(all("not a KEY=VALUE assignment" in p for p in problems))

    def test_text_after_closing_quote_and_interpolation_are_refused(self):
        self.assertRefusedWithoutDisclosure('K="SYNTHETIC3=" trailing\n', "K has text after its closing quote")
        self.assertRefusedWithoutDisclosure('K="MIGTAgEA$HOME"\n', "K contains '$' that Compose would interpolate")
        self.assertRefusedWithoutDisclosure("K=MIGTAgEA${X}\n", "K contains '$' that Compose would interpolate")

    def test_line_numbers_continue_after_multiline_values(self):
        _, problems = self.parse(f'K="{SYNTHETIC_PEM}"\nnot an assignment\n')
        self.assertEqual(problems, [("test.env line 7: not a KEY=VALUE assignment "
                                     "(and not inside a quoted value)")])


class SerialisationTests(unittest.TestCase):
    def test_every_value_round_trips_through_the_parser(self):
        text = "".join(f"{k}={contract.format_env_value(v)}\n" for k, v in TRICKY_VALUES.items())
        values, problems = contract.parse_env_text(text, "roundtrip.env")
        self.assertEqual(problems, [])
        self.assertEqual(values, TRICKY_VALUES)

    def test_multiline_values_are_written_quoted_and_single_lines_stay_unquoted(self):
        self.assertTrue(contract.format_env_value(SYNTHETIC_PEM).startswith('"'))
        self.assertEqual(contract.format_env_value("plain-value"), "plain-value")
        self.assertEqual(contract.format_env_value("a$b"), "a$$b")


@unittest.skipUnless(compose_available(), "Docker Compose CLI is required")
class ComposeAgreementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="mykhaya-dotenv-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_parser_matches_compose_for_legacy_style_input(self):
        legacy = self.work / "legacy.env"
        legacy.write_bytes((
            f'MYKHAYA_APNS_PRIVATE_KEY="{SYNTHETIC_PEM}"\n'
            f"SQ_KEY='{SYNTHETIC_PEM}'\n"
            "MYKHAYA_FCM_PRIVATE_KEY=-----BEGIN X-----\\nAAAA\\n-----END X-----\\n\n"
            'DQ_ESC="a\\nb\\tc\\\\d\\"e\\$f$$g\\xh"\n'
            "SQ_ESC='a\\nb\\\\c\\'d$e'\n"
            "UNQ=a\\nb$$c   # comment\n"
            'JSON=["https://dev.mykhaya.app"]\n'
            "CRLF=crlf\r\n"
        ).encode())
        ours, problems = contract.parse_env_file(legacy)
        self.assertEqual(problems, [])
        self.assertEqual(ours, compose_env_file_values(legacy))

    def test_serialised_values_resolve_identically_in_compose(self):
        generated = self.work / "generated.env"
        generated.write_text(
            "".join(f"{k}={contract.format_env_value(v)}\n" for k, v in TRICKY_VALUES.items()),
            encoding="utf-8", newline="\n")
        self.assertEqual(compose_env_file_values(generated), TRICKY_VALUES)


class SplitMultilineTests(unittest.TestCase):
    """The legacy .env -> service files path with a multiline APNs key."""

    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="mykhaya-split-ml-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.out = self.work / "dev"
        self.out.mkdir()
        cfg_base = self.work / "src"
        root = synthetic.write_synthetic_root(cfg_base)
        legacy: dict[str, str] = {}
        for name in ("compose.env", "common.env", "api.env", "worker.env", "scheduler.env"):
            legacy.update(contract.parse_env_file(root / name)[0])
        legacy.pop("MYKHAYA_DATABASE_URL")
        legacy.update({
            "MYKHAYA_POSTGRES_ADMIN_PASSWORD": synthetic.ADMIN_PASSWORD,
            "MYKHAYA_MIGRATION_DB_PASSWORD": synthetic.MIGRATION_PASSWORD,
            "MYKHAYA_DB_PASSWORD": synthetic.RUNTIME_PASSWORD,
            "MYKHAYA_APNS_DELIVERY_CONFIGURED": "true",
            "MYKHAYA_APNS_TEAM_ID": "SYNTHTEAM1",
            "MYKHAYA_APNS_KEY_ID": "SYNTHKEY01",
        })
        lines = "".join(f"{k}={contract.format_env_value(v)}\n" for k, v in legacy.items())
        # The multiline key in the legacy layout: a double-quoted PEM block.
        self.legacy = self.work / "legacy.env"
        self.legacy.write_text(lines + f'MYKHAYA_APNS_PRIVATE_KEY="{SYNTHETIC_PEM}"\n',
                               encoding="utf-8", newline="\n")

    def split(self, legacy: Path):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                code = contract.main(["--split-legacy-env", str(legacy), "--out", str(self.out)])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                buffer.write(str(exc))
        return code, buffer.getvalue()

    def test_key_reaches_only_the_worker_exactly(self):
        code, output = self.split(self.legacy)
        self.assertEqual(code, 0, output)
        files = {p.name: contract.parse_env_file(p)[0] for p in self.out.glob("*.env")}
        self.assertEqual(files["worker.env"]["MYKHAYA_APNS_PRIVATE_KEY"], SYNTHETIC_PEM)
        for name in ("api.env", "scheduler.env", "migrate.env", "common.env", "compose.env",
                     "postgres.env"):
            self.assertNotIn("MYKHAYA_APNS_PRIVATE_KEY", files[name], name)
        for secret in SECRET_FRAGMENTS:
            self.assertNotIn(secret, output)
        report = contract.validate_root(self.out, repo_root=ROOT, check_perms=False)
        self.assertEqual([e for e in report.errors if "permission" not in e], [])

    @unittest.skipUnless(compose_available(), "Docker Compose CLI is required")
    def test_key_survives_compose_resolution_of_the_service_env_overlay(self):
        code, output = self.split(self.legacy)
        self.assertEqual(code, 0, output)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("MYKHAYA_", "COMPOSE_"))}
        env.update(MYKHAYA_DEV_CONFIG_ROOT=str(self.out), MYKHAYA_DB_PASSWORD="",
                   MYKHAYA_MIGRATION_DB_PASSWORD="", MYKHAYA_POSTGRES_ADMIN_PASSWORD="",
                   MSYS_NO_PATHCONV="1")
        # Key directories come from the synthetic source root and exist.
        compose_env = self.out / "compose.env"
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(compose_env), "-f", "compose.yml",
             "-f", "compose.dev.yml", "-f", "compose.dev.service-env.yml", "config",
             "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, "Compose rejected the split root (details withheld)")
        model = json.loads(result.stdout)
        worker = model["services"]["worker"]["environment"]
        self.assertEqual(worker["MYKHAYA_APNS_PRIVATE_KEY"].replace("$$", "$"), SYNTHETIC_PEM)
        self.assertEqual(model["services"]["api"]["environment"]["MYKHAYA_APNS_PRIVATE_KEY"], "")
        self.assertEqual(contract.check_provenance(model, self.out), [])

    def test_malformed_legacy_file_writes_nothing_and_discloses_nothing(self):
        broken = self.work / "broken.env"
        broken.write_text(f'A=1\nMYKHAYA_APNS_PRIVATE_KEY="{SYNTHETIC_PEM}\n', encoding="utf-8")
        code, output = self.split(broken)
        self.assertNotEqual(code, 0)
        self.assertIn("unterminated double-quoted value", output)
        self.assertEqual(list(self.out.iterdir()), [])
        for secret in SECRET_FRAGMENTS:
            self.assertNotIn(secret, output)

    def test_failed_round_trip_leaves_no_partial_output(self):
        with mock.patch.object(contract, "format_env_value", side_effect=lambda v: "x" + v):
            code, output = self.split(self.legacy)
        self.assertNotEqual(code, 0)
        self.assertIn("did not round-trip exactly; nothing was written", output)
        self.assertEqual(list(self.out.iterdir()), [], "no file, final or temporary, may remain")
        for secret in SECRET_FRAGMENTS:
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
