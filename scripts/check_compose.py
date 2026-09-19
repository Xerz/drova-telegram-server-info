"""Validate deployment fixtures with Compose, without credentials or running containers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = json.loads((ROOT / "specs/v2/fixtures/runtime/deployment.json").read_text())
    with tempfile.TemporaryDirectory(prefix="drova-compose-") as directory:
        project = Path(directory)
        (project / "compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
        for case in cases:
            (project / ".env").write_text(
                "\n".join(f"{key}={value}" for key, value in case["environment"].items())
            )
            for steam in (False, True):
                result = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(project / "compose.yml"),
                        *(["--profile", "steam"] if steam else []),
                        "config",
                        "--format",
                        "json",
                    ],
                    cwd=project,
                    env={"PATH": os.environ["PATH"]},
                    check=True,
                    capture_output=True,
                    text=True,
                )
                services = json.loads(result.stdout)["services"]
                expected = case["images"] if steam else {"drova-bot": case["images"]["drova-bot"]}
                assert {name: service["image"] for name, service in services.items()} == expected
                for service in services.values():
                    assert "build" not in service
                    assert service["platform"] == "linux/amd64"
                    assert not service.get("ports")
                if steam:
                    watcher = services["steam-watcher"]
                    assert watcher["environment"]["UPDATE_PROVIDERS"] == case["environment"].get(
                        "UPDATE_PROVIDERS", "steam"
                    )
                    assert "TELEGRAM_BOT_TOKEN" not in watcher["environment"]
                    assert "BOT_SECRET_KEY" not in watcher["environment"]
                    assert watcher["volumes"][0]["source"] == "steam-watcher-data"
            print(f"{case['name']}: both Compose profiles passed")


if __name__ == "__main__":
    main()
