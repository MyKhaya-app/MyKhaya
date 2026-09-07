from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_lab_compose_has_only_explicit_lab_resources() -> None:
    compose = read("compose.lab.yml")
    assert "name: mykhaya-lab" in compose
    for network in ("mykhaya_lab_edge", "mykhaya_lab_app", "mykhaya_lab_data"):
        assert network in compose
    for volume in (
        "mykhaya_lab_postgres_data",
        "mykhaya_lab_redis_data",
        "mykhaya_lab_avatar_data",
        "mykhaya_lab_caddy_data",
        "mykhaya_lab_caddy_config",
    ):
        assert volume in compose
    assert "\n  postgres_data:" not in compose
    assert "\n  redis_data:" not in compose
    assert "\n  caddy_data:" not in compose


def test_lab_environment_is_distinct_and_stripe_is_test_only() -> None:
    env = read(".env.lab.example")
    assert "MYKHAYA_ENVIRONMENT=lab" in env
    assert "MYKHAYA_NODE_ID=mk-lab-01" in env
    assert "MYKHAYA_REGION=uk" in env
    assert "MYKHAYA_COOKIE_SECURE=true" in env
    assert "MYKHAYA_COOKIE_DOMAIN=" in env
    assert "MYKHAYA_STRIPE_SECRET_KEY=sk_test_" in env
    assert "MYKHAYA_STRIPE_PUBLISHABLE_KEY=pk_test_" in env
    assert "MYKHAYA_APNS_DELIVERY_CONFIGURED=false" in env
    assert "dev.mykhaya.app" not in env


def test_lab_scripts_have_protective_guards() -> None:
    deploy = read("infrastructure/scripts/lab-deploy.sh")
    seed = read("infrastructure/scripts/lab-seed.sh")
    assert "feature/multi-node-platform" in deploy
    assert "MYKHAYA_ENVIRONMENT" in deploy
    assert "MYKHAYA_NODE_ID" in deploy
    assert "mykhaya-lab" in deploy
    assert "down --volumes --remove-orphans" in deploy
    assert "RESET LAB" in deploy
    assert "Lab seed refuses non-Lab environment" in seed


def test_lab_ingress_contains_only_lab_hosts() -> None:
    caddy = read("infrastructure/caddy/Caddyfile.lab")
    for host in (
        "lab.mykhaya.app",
        "admin.lab.mykhaya.app",
        "api.lab.mykhaya.app",
        "status.lab.mykhaya.app",
    ):
        assert host in caddy
    assert "dev.mykhaya.app" not in caddy
