import requests
from typing import Any, Dict, List, Optional, Tuple


BASE_URL = "https://services.drova.io"


def _get(path: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[Any], int]:
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params or {}, headers=headers or {})
        status = resp.status_code
        try:
            data = resp.json()
        except Exception:
            data = None
        return data, status
    except Exception:
        return None, 0


def get_account_info(token: str) -> Tuple[Optional[Dict[str, Any]], int]:
    return _get("/accounting/myaccount", headers={"X-Auth-Token": token})


def get_sessions(auth_token: str, *, server_id: Optional[str] = None, limit: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]], int]:
    params: Dict[str, Any] = {}
    if server_id is not None:
        params["server_id"] = server_id
    if limit is not None:
        params["limit"] = limit
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

