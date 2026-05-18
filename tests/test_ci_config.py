from __future__ import annotations

from pathlib import Path


def test_ci_runs_network_free_gates_and_docker_build() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv run pytest" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run mypy src tests" in workflow
    assert "docker/build-push-action" in workflow
    assert "--run-live" not in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "BOT_SECRET_KEY" not in workflow
    assert "DROVA_PROXY_TOKEN" not in workflow


def test_dockerignore_excludes_secrets_and_runtime_data() -> None:
    root = Path(__file__).resolve().parents[1]
    entries = set((root / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert ".env" in entries
    assert ".env.specing" in entries
    assert "persistentData.json" in entries
    assert "data" in entries
    assert "GeoLite2-City.mmdb" in entries
    assert "specs/v2/fixtures/api/raw" in entries
