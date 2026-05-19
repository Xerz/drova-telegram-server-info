"""Typed domain DTOs used across application layers."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SESSION_LIMIT = 5
MIN_SESSION_LIMIT = 1
MAX_SESSION_LIMIT = 100
DEFAULT_TIMEZONE = "Asia/Yekaterinburg"

ONLINE_STATES = frozenset({"LISTEN", "HANDSHAKE", "BUSY"})


@dataclass(frozen=True, slots=True)
class Account:
    uuid: str
    name: str | None
    roles: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChatProfile:
    telegram_chat_id: int
    drova_user_id: str | None = None
    encrypted_proxy_token: bytes | None = None
    selected_station_id: str | None = None
    session_limit: int = DEFAULT_SESSION_LIMIT
    timezone: str = DEFAULT_TIMEZONE


@dataclass(frozen=True, slots=True)
class Station:
    uuid: str
    name: str
    state: str
    published: bool
    verified: str | None = None
    city_name: str | None = None
    groups_list: list[str] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class Session:
    uuid: str
    server_id: str
    merchant_id: str
    product_id: str
    client_id: str | None
    creator_ip: str | None
    created_on_ms: int
    finished_on_ms: int | None
    billing_type: str | None = None
    status: str | None = None
    score_text: str | None = None


@dataclass(frozen=True, slots=True)
class SessionPage:
    sessions: list[Session]


@dataclass(frozen=True, slots=True)
class StationProduct:
    product_id: str
    title: str
    enabled: bool
    published: bool
    available: bool


@dataclass(frozen=True, slots=True)
class CatalogProduct:
    product_id: str
    title: str


@dataclass(frozen=True, slots=True)
class Endpoint:
    uuid: str
    server_id: str
    ip: str
    base_port: int
    externally_routable: bool | None = None


@dataclass(frozen=True, slots=True)
class Promocode:
    id: int
    promocode: str
    created_on_ms: int
    expired_on_ms: int
    expired: bool
    merchant_id: str
    playtime_msecs: int


@dataclass(frozen=True, slots=True)
class PrepaidStats:
    merchant_id: str
    allowed_to_sell_minutes: int
    sold_minutes: int
    used_minutes: int
    balance: float | None = None


@dataclass(frozen=True, slots=True)
class PrepaidSettlement:
    uuid: str
    client_id: str | None
    created_on_ms: int
    has_order: bool
    playtime_msecs: int


@dataclass(frozen=True, slots=True)
class OpenedPrepaidDeal:
    created_on_ms: int
    deal_id: str | None
    payout_amount: float | None
    gross_amount: float | None
    terminal_index: int | None = None


@dataclass(frozen=True, slots=True)
class ServerSource:
    uuid: str
    user_id: str
    name: str
    description: str
    state: str
    published: bool
    verified: str | None
    allow_desktop: bool
    disable_updates: bool
    product_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LaunchParameters:
    allowed_paths: str | None = None
    args: str | None = None
    game_path: str | None = None
    work_path: str | None = None


@dataclass(frozen=True, slots=True)
class ServerProductEdit:
    product_id: str
    title: str
    enabled: bool
    published: bool
    available: bool
    verified: int | None
    default_launch: LaunchParameters
    current_launch: LaunchParameters
