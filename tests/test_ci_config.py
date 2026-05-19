from __future__ import annotations

from pathlib import Path


def test_ci_runs_network_free_gates_and_docker_build() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv run pytest" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run mypy src tests" in workflow
    assert "docker/build-push-action" in workflow
    assert "docker/login-action@v3" in workflow
    assert "docker/metadata-action@v5" in workflow
    assert "packages: write" in workflow
    assert "ghcr.io/${{ github.repository }}" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "cache-from: type=gha" in workflow
    assert "cache-to: type=gha,mode=max" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert '- "v*.*.*"' in workflow
    assert "type=raw,value=latest,enable={{is_default_branch}}" in workflow
    assert "type=sha,prefix=sha-,format=short" in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert "type=semver,pattern={{major}}.{{minor}}" in workflow
    assert "type=ref,event=branch" not in workflow
    assert "push: false" not in workflow
    assert "--run-live" not in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "BOT_SECRET_KEY" not in workflow
    assert "DROVA_PROXY_TOKEN" not in workflow


def test_dockerfile_keeps_runtime_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "RUN pip install --no-cache-dir uv" in dockerfile
    assert "RUN uv sync --frozen --no-dev" in dockerfile
    assert 'VOLUME ["/data"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "python -m drova_bot.tools.healthcheck" in dockerfile
    assert 'CMD ["drova-bot"]' in dockerfile


def test_dockerignore_excludes_secrets_and_runtime_data() -> None:
    root = Path(__file__).resolve().parents[1]
    entries = set((root / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert ".env" in entries
    assert ".env.specing" in entries
    assert "persistentData.json" in entries
    assert "data" in entries
    assert "GeoLite2-City.mmdb" in entries
    assert "specs/v2/fixtures/api/raw" in entries
