#!/usr/bin/env python3
"""Collect sanitized Drova API fixtures for the V2 spec.

This script is intentionally separate from production bot code. It reads
`.env.specing`, stores raw responses in an ignored directory, and writes
sanitized fixtures that are safe to review and track.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.specing"
FIXTURE_DIR = ROOT / "specs" / "v2" / "fixtures" / "api"
RAW_DIR = FIXTURE_DIR / "raw"
BASE_URL = "https://services.drova.io"
REQUEST_TIMEOUT = 20

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def load_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        result[key] = value
    return result


class Sanitizer:
    def __init__(self) -> None:
        self.uuid_map: Dict[str, str] = {}
        self.ip_map: Dict[str, str] = {}
        self.id_map: Dict[Tuple[str, str], str] = {}

    def _alias(self, mapping: Dict[str, str], prefix: str, value: str) -> str:
        if value not in mapping:
            mapping[value] = f"<{prefix}:{len(mapping) + 1}>"
        return mapping[value]

    def _alias_by_key(self, key: str, value: str) -> str:
        map_key = (key, value)
        if map_key not in self.id_map:
            self.id_map[map_key] = f"<{key}:{len([k for k in self.id_map if k[0] == key]) + 1}>"
        return self.id_map[map_key]

    def sanitize(self, value: Any, key: str = "", path: Tuple[str, ...] = ()) -> Any:
        key_lower = key.lower()

        if key_lower.startswith("description") or key_lower in {
            "balance",
            "emails",
            "exportable_money",
            "latitude",
            "longitude",
            "mts_msisdn",
            "mts_pcr",
            "primary_qiwi_bankcard_id",
            "qiwi_wallet",
            "trial_msecs_left",
        }:
            return f"<{key_lower}:redacted>"

        if isinstance(value, dict):
            return {
                str(k): self.sanitize(v, str(k), path + (str(k),))
                for k, v in value.items()
            }

        if isinstance(value, list):
            return [
                self.sanitize(item, key, path + (str(index),))
                for index, item in enumerate(value)
            ]

        if not isinstance(value, str):
            return value

        if "token" in key_lower or key_lower in {"authorization", "x-auth-token"}:
            return "<redacted>"

        if key_lower in {"email", "name", "city_name", "score_text", "score_reason", "abort_comment"}:
            return f"<{key_lower}:redacted>"

        if key_lower in {"client_id", "merchant_id", "server_id", "user_id", "uuid", "parent"}:
            return self._alias_by_key(key_lower, value)

        if "ip" in key_lower:
            return IP_RE.sub(lambda m: self._alias(self.ip_map, "ip", m.group(0)), value)

        if key_lower in {"productid", "product_id"}:
            return value

        sanitized = UUID_RE.sub(lambda m: self._alias(self.uuid_map, "uuid", m.group(0)), value)
        sanitized = IP_RE.sub(lambda m: self._alias(self.ip_map, "ip", m.group(0)), sanitized)
        return sanitized


def merge_schemas(left: Any, right: Any) -> Any:
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        if left.get("type") != right.get("type"):
            types = sorted(set(as_type_list(left.get("type"))) | set(as_type_list(right.get("type"))))
            return {"type": types}
        if left.get("type") == "object":
            keys = sorted(set(left.get("fields", {})) | set(right.get("fields", {})))
            return {
                "type": "object",
                "fields": {
                    key: merge_schemas(left.get("fields", {}).get(key), right.get("fields", {}).get(key))
                    for key in keys
                },
            }
        if left.get("type") == "array":
            return {
                "type": "array",
                "count": max(left.get("count", 0), right.get("count", 0)),
                "items": merge_schemas(left.get("items"), right.get("items")),
            }
    if left is None:
        return right
    if right is None:
        return left
    return {"type": sorted(set(as_type_list(type_name(left))) | set(as_type_list(type_name(right))))}


def as_type_list(value: Any) -> List[str]:
    if value is None:
        return ["null"]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def infer_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            "type": "object",
            "fields": {str(key): infer_schema(item) for key, item in sorted(value.items())},
        }
    if isinstance(value, list):
        item_schema = None
        for item in value[:20]:
            item_schema = merge_schemas(item_schema, infer_schema(item))
        return {"type": "array", "count": len(value), "items": item_schema}
    return {"type": type_name(value)}


class DrovaSampler:
    def __init__(self, env: Dict[str, str]) -> None:
        self.token = env["DROVA_PROXY_TOKEN"]
        self.test_station_uuid = env["TEST_STATION_UUID"]
        self.session = requests.Session()
        self.proxy_enabled = False
        self.proxy_fallback_used = False
        proxies = {}
        if env.get("HTTP_PROXY"):
            proxies["http"] = env["HTTP_PROXY"]
        if env.get("HTTPS_PROXY"):
            proxies["https"] = env["HTTPS_PROXY"]
        if proxies:
            self.session.proxies.update(proxies)
            self.proxy_enabled = True
        self.sanitizer = Sanitizer()
        self.summary: List[Dict[str, Any]] = []
        self.schema_summary: Dict[str, Any] = {}

    def headers(self) -> Dict[str, str]:
        return {"X-Auth-Token": self.token}

    def request(
        self,
        label: str,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        auth: bool = True,
    ) -> Tuple[Any, int]:
        url = f"{BASE_URL}{path}"
        started = time.perf_counter()
        try:
            response = self.session.request(
                method,
                url,
                params=params or {},
                json=json_body,
                headers=self.headers() if auth else {},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.ProxyError:
            if not self.proxy_enabled or self.proxy_fallback_used:
                raise
            self.proxy_fallback_used = True
            self.proxy_enabled = False
            self.session = requests.Session()
            self.session.trust_env = False
            print("configured proxy is unreachable; retrying direct HTTPS without printing proxy details")
            response = self.session.request(
                method,
                url,
                params=params or {},
                json=json_body,
                headers=self.headers() if auth else {},
                timeout=REQUEST_TIMEOUT,
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        try:
            data: Any = response.json()
        except ValueError:
            data = response.text

        raw_payload = {
            "label": label,
            "method": method,
            "path": path,
            "params": params or {},
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "response": data,
        }
        sanitized_payload = self.sanitizer.sanitize(raw_payload)
        sanitized_path = self.sanitizer.sanitize(path)

        write_json(RAW_DIR / f"{label}.raw.json", raw_payload)
        write_json(FIXTURE_DIR / f"{label}.json", sanitized_payload)

        self.schema_summary[label] = infer_schema(sanitized_payload)
        self.summary.append(
            {
                "label": label,
                "method": method,
                "path": sanitized_path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
                "proxy_fallback_used": self.proxy_fallback_used,
            }
        )
        print(f"{label}: {method} {sanitized_path} -> {response.status_code} ({elapsed_ms} ms)")
        return data, response.status_code

    def maybe_renew_token(self) -> bool:
        data, status = self.request(
            "token_renewal_if_needed",
            "POST",
            "/token-verifier/renewProxyToken",
            json_body={"proxy_token": self.token},
            auth=False,
        )
        if status == 200 and isinstance(data, dict) and data.get("proxyToken"):
            self.token = data["proxyToken"]
            return True
        return False

    def run(self) -> None:
        account, status = self.request("account", "GET", "/accounting/myaccount")
        if status == 401:
            print("account returned 401; attempting token renewal")
            if self.maybe_renew_token():
                account, status = self.request("account_after_renewal", "GET", "/accounting/myaccount")

        require_status("account", status, 200)
        if not isinstance(account, dict) or not account.get("uuid"):
            raise RuntimeError("account response does not include uuid")
        user_id = account["uuid"]

        products, products_status = self.request(
            "products_full",
            "GET",
            "/product-manager/product/listfull2",
            auth=False,
        )
        require_status("products_full", products_status, 200)

        servers, servers_status = self.request(
            "servers",
            "GET",
            "/server-manager/servers",
            params={"user_id": user_id},
        )
        require_status("servers", servers_status, 200)
        if not isinstance(servers, list):
            raise RuntimeError("servers response is not a list")

        sessions_all, sessions_status = self.request(
            "sessions_all_limit_5",
            "GET",
            "/session-manager/sessions",
            params={"merchant_id": user_id, "limit": 5},
        )
        require_status("sessions_all_limit_5", sessions_status, 200)

        for index, server in enumerate(servers, start=1):
            server_uuid = server.get("uuid")
            if not server_uuid:
                continue
            suffix = f"server_{index}"
            _, status = self.request(
                f"{suffix}_sessions_limit_5",
                "GET",
                "/session-manager/sessions",
                params={"server_id": server_uuid, "limit": 5},
            )
            require_status(f"{suffix}_sessions_limit_5", status, 200)

            _, status = self.request(
                f"{suffix}_products",
                "GET",
                f"/server-manager/serverproduct/list4edit2/{server_uuid}",
                params={"user_id": user_id},
            )
            require_status(f"{suffix}_products", status, 200)

            _, status = self.request(
                f"{suffix}_endpoints_limit_5",
                "GET",
                f"/server-manager/serverendpoint/list/{server_uuid}",
                params={"server_id": server_uuid, "limit": 5},
            )
            require_status(f"{suffix}_endpoints_limit_5", status, 200)

        self.sample_publish_write_flow(servers, user_id)
        write_json(FIXTURE_DIR / "schema-summary.json", self.schema_summary)
        write_json(FIXTURE_DIR / "sampling-report.json", {"requests": self.summary})

    def sample_publish_write_flow(self, servers: List[Dict[str, Any]], user_id: str) -> None:
        test_server = next(
            (server for server in servers if server.get("uuid") == self.test_station_uuid),
            None,
        )
        if test_server is None:
            raise RuntimeError("TEST_STATION_UUID is not present in /server-manager/servers")
        if "published" not in test_server:
            raise RuntimeError("test station does not include published field")

        original = bool(test_server["published"])
        target = not original
        rollback_status: Optional[int] = None
        try:
            _, status = self.request(
                "test_station_publish_toggle",
                "POST",
                f"/server-manager/servers/{self.test_station_uuid}/set_published/{str(target).lower()}",
            )
            require_status("test_station_publish_toggle", status, 200)

            confirm, status = self.request(
                "test_station_publish_toggle_confirm",
                "GET",
                "/server-manager/servers",
                params={"user_id": user_id},
            )
            require_status("test_station_publish_toggle_confirm", status, 200)
            require_published_state(confirm, self.test_station_uuid, target, "toggle confirm")
        finally:
            _, rollback_status = self.request(
                "test_station_publish_rollback",
                "POST",
                f"/server-manager/servers/{self.test_station_uuid}/set_published/{str(original).lower()}",
            )
            if rollback_status != 200:
                raise RuntimeError(f"rollback failed with status {rollback_status}")

        confirm, status = self.request(
            "test_station_publish_rollback_confirm",
            "GET",
            "/server-manager/servers",
            params={"user_id": user_id},
        )
        require_status("test_station_publish_rollback_confirm", status, 200)
        require_published_state(confirm, self.test_station_uuid, original, "rollback confirm")


def require_published_state(data: Any, server_uuid: str, expected: bool, label: str) -> None:
    if not isinstance(data, list):
        raise RuntimeError(f"{label}: servers response is not a list")
    target = next((item for item in data if item.get("uuid") == server_uuid), None)
    if target is None:
        raise RuntimeError(f"{label}: test station missing from servers response")
    actual = bool(target.get("published"))
    if actual != expected:
        raise RuntimeError(f"{label}: expected published={expected}, got {actual}")


def require_status(label: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} returned status {actual}, expected {expected}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    env = load_env_file(ENV_PATH)
    for key, value in env.items():
        if value:
            os.environ[key] = value

    missing = [key for key in ("DROVA_PROXY_TOKEN", "TEST_STATION_UUID") if not env.get(key)]
    if missing:
        print(f"Missing required keys in .env.specing: {', '.join(missing)}", file=sys.stderr)
        return 2

    sampler = DrovaSampler(env)
    sampler.run()
    print(f"wrote sanitized fixtures to {FIXTURE_DIR}")
    print(f"wrote raw fixtures to ignored directory {RAW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
