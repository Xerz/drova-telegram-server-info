"""Container liveness probe of the event loop and database, not Steam availability."""

import os

import httpx


def main() -> None:
    token = os.environ.get("STEAM_WATCHER_TOKEN", "")
    port = os.environ.get("STEAM_API_PORT", "8080")
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            response = client.get(
                f"http://127.0.0.1:{port}/health", headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
    except httpx.HTTPError:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
