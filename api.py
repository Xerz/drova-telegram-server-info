import logging
import time
import requests
from typing import Any, Dict, List, Optional, Tuple

from storage import replaceAuthToken


BASE_URL = "https://services.drova.io"
REQUEST_TIMEOUT = 5
RENEWAL_PATH = "/token-verifier/renewProxyToken"
logger = logging.getLogger(__name__)
renewedAuthTokens: Dict[str, str] = {}


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


def get_latest_auth_token(auth_token: Optional[str]) -> Optional[str]:
    if auth_token is None:
        return None

    current_token = auth_token
    visited_tokens = set()
    while current_token in renewedAuthTokens and current_token not in visited_tokens:
        visited_tokens.add(current_token)
        next_token = renewedAuthTokens[current_token]
        if next_token == current_token:
            break
        current_token = next_token
    return current_token


def _remember_renewed_auth_token(old_token: str, new_token: str):
    for token, latest_token in list(renewedAuthTokens.items()):
        if latest_token == old_token:
            renewedAuthTokens[token] = new_token
    renewedAuthTokens[old_token] = new_token
    renewedAuthTokens[new_token] = new_token


def _extract_auth_token(headers: Optional[Dict[str, str]]) -> Optional[str]:
    if not headers:
        return None
    for header_name, header_value in headers.items():
        if header_name.lower() == "x-auth-token":
            return header_value
    return None


def _apply_latest_auth_token(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    actual_headers = dict(headers or {})
    auth_token = _extract_auth_token(actual_headers)
    latest_auth_token = get_latest_auth_token(auth_token)
    if auth_token is not None and latest_auth_token is not None and latest_auth_token != auth_token:
        actual_headers["X-Auth-Token"] = latest_auth_token
    return actual_headers


def _parse_response_data(resp: requests.Response) -> Optional[Any]:
    try:
        return resp.json()
    except Exception:
        return None


def _renew_auth_token(auth_token: str) -> Optional[str]:
    url = f"{BASE_URL}{RENEWAL_PATH}"
    try:
        t0 = time.perf_counter()
        logger.info("Drova token expired, attempting renewal")
        resp = requests.post(url, json={"proxy_token": auth_token}, timeout=REQUEST_TIMEOUT)
        status = resp.status_code
        data = _parse_response_data(resp)
        dt = (time.perf_counter() - t0) * 1000
        logger.debug(f"POST {url} -> status={status} time_ms={dt:.1f} json={'yes' if data is not None else 'no'}")
        if status != 200 or data is None:
            logger.warning(f"Drova token renewal failed with status={status}")
            return None

        new_token = data.get("proxyToken")
        if not new_token:
            logger.warning("Drova token renewal did not return proxyToken")
            return None

        _remember_renewed_auth_token(auth_token, new_token)
        replaced_count = replaceAuthToken(auth_token, new_token)
        logger.info(f"Drova token renewed successfully, updated {replaced_count} stored token(s)")
        return new_token
    except Exception as e:
        logger.exception(f"POST {url} failed during token renewal: {e}")
        return None


def _request(method: str, path: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, json: Optional[Dict[str, Any]] = None, allow_token_renewal: bool = True) -> Tuple[Optional[Any], int]:
    url = f"{BASE_URL}{path}"
    actual_headers = _apply_latest_auth_token(headers)
    masked_headers = _mask_headers(actual_headers)
    try:
        t0 = time.perf_counter()
        logger.debug(f"{method} {url} params={params or {}} headers={masked_headers}")
        resp = requests.request(method, url, params=params or {}, headers=actual_headers, json=json, timeout=REQUEST_TIMEOUT)
        status = resp.status_code
        data = _parse_response_data(resp)
        logger.debug(f"{method} {url} status={status} data={data}")
        dt = (time.perf_counter() - t0) * 1000
        logger.debug(f"{method} {url} -> status={status} time_ms={dt:.1f} json={'yes' if data is not None else 'no'}")

        auth_token = _extract_auth_token(actual_headers)
        if status == 401 and allow_token_renewal and auth_token:
            renewed_token = _renew_auth_token(auth_token)
            if renewed_token is not None:
                retry_headers = dict(actual_headers)
                retry_headers["X-Auth-Token"] = renewed_token
                logger.info(f"Retrying {method} {url} after successful Drova token renewal")
                return _request(method, path, params=params, headers=retry_headers, json=json, allow_token_renewal=False)

        return data, status
    except Exception as e:
        logger.exception(f"{method} {url} failed: {e}")
        return None, 0


def _get(path: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[Any], int]:
    return _request("GET", path, params=params, headers=headers)


def _post(path: str, *, headers: Optional[Dict[str, str]] = None, json: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], int]:
    return _request("POST", path, headers=headers, json=json)


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


def set_server_published(auth_token: str, server_id: str, published: bool) -> Tuple[Optional[Any], int]:
    path = f"/server-manager/servers/{server_id}/set_published/{str(published).lower()}"
    return _post(path, headers={"X-Auth-Token": auth_token})
