import logging
import time
import requests
from typing import Any, Dict, List, Optional, Tuple


BASE_URL = "https://services.drova.io"
logger = logging.getLogger(__name__)


def _mask_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not headers:
        return {}
    masked = {}
    for k, v in headers.items():
        if k.lower() in {"x-auth-token", "authorization"} and isinstance(v, str):
            masked[k] = v[:4] + "***" if len(v) > 4 else "***"
        else:
            masked[k] = v
    return masked


def _get(path: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[Any], int]:
    url = f"{BASE_URL}{path}"
    masked_headers = _mask_headers(headers)
    try:
        t0 = time.perf_counter()
        logger.debug(f"GET {url} params={params or {}} headers={masked_headers}")
        resp = requests.get(url, params=params or {}, headers=headers or {})
        status = resp.status_code
        try:
            data = resp.json()
        except Exception:
            data = None
        logger.debug(f"GET {url} status={status} data={data}")
        dt = (time.perf_counter() - t0) * 1000
        logger.debug(f"GET {url} -> status={status} time_ms={dt:.1f} json={'yes' if data is not None else 'no'}")
        return data, status
    except Exception as e:
        logger.exception(f"GET {url} failed: {e}")
        return None, 0


def get_account_info(token: str) -> Tuple[Optional[Dict[str, Any]], int]:
    return _get("/accounting/myaccount", headers={"X-Auth-Token": token})


def get_sessions(auth_token: str, *, merchant_id: Optional[str] = None, server_id: Optional[str] = None, limit: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]], int]:
    params: Dict[str, Any] = {}
    if server_id is not None:
        params["server_id"] = server_id
    if limit is not None:
        params["limit"] = limit
    if merchant_id is not None:
        params["merchant_id"] = merchant_id
    return _get("/session-manager/sessions", params=params, headers={"X-Auth-Token": auth_token})


def get_servers(auth_token: str, user_id: str) -> Tuple[Optional[List[Dict[str, Any]]], int]:
    return _get("/server-manager/servers", params={"user_id": user_id}, headers={"X-Auth-Token": auth_token})


def get_server_products(auth_token: str, user_id: str, server_id: str) -> Tuple[Optional[List[Dict[str, Any]]], int]:
    path = f"/server-manager/serverproduct/list4edit2/{server_id}"
    return _get(path, params={"user_id": user_id}, headers={"X-Auth-Token": auth_token})


def get_server_endpoints(auth_token: str, server_id: str, *, limit: Optional[int] = None) -> Tuple[Optional[List[Dict[str, Any]]], int]:
    params: Dict[str, Any] = {"server_id": server_id}
    if limit is not None:
        params["limit"] = limit
    path = f"/server-manager/serverendpoint/list/{server_id}"
    return _get(path, params=params, headers={"X-Auth-Token": auth_token})


def get_products_full() -> Tuple[Optional[List[Dict[str, Any]]], int]:
    return _get("/product-manager/product/listfull2")
