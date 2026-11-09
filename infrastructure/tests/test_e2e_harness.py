from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def test_e2e_compose_has_no_environment_file_or_default_project() -> None:
    compose = (ROOT / "compose.e2e.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(compose)
    assert all("env_file" not in service for service in parsed["services"].values())
    assert parsed.get("name") is None
    assert set(parsed["services"]) == {
        "postgres",
        "redis",
        "mailpit",
        "oauth-provider",
        "migrate",
            "seed",
            "worker",
            "scheduler",
        "api",
        "web",
    }


def test_e2e_provider_internal_endpoints_are_not_host_published() -> None:
    provider = (ROOT / "infrastructure/e2e/oauth-provider.py").read_text(encoding="utf-8")
    assert 'self.headers.get("Host") != "oauth-provider:8081"' in provider
    compose = yaml.safe_load((ROOT / "compose.e2e.yml").read_text(encoding="utf-8"))
    assert compose["services"]["oauth-provider"]["ports"] == ["127.0.0.1:18081:8081"]


def test_e2e_teardown_is_project_scoped_and_rejects_default_name() -> None:
    script = (ROOT / "infrastructure/e2e/run-e2e.ps1").read_text(encoding="utf-8")
    assert "Unsafe E2E Compose project name" in script
    assert "docker compose -p $Project" in script
    assert "down -v --remove-orphans" in script
