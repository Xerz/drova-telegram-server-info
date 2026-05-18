"""Pydantic models for Drova API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from drova_bot.domain.models import (
    Account,
    CatalogProduct,
    Endpoint,
    Promocode,
    Session,
    SessionPage,
    Station,
    StationProduct,
)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


class DrovaApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AccountResponse(DrovaApiModel):
    uuid: str
    name: str | None = None
    roles: list[str] = Field(default_factory=list)

    def to_domain(self) -> Account:
        return Account(uuid=self.uuid, name=self.name, roles=self.roles)


class StationResponse(DrovaApiModel):
    uuid: str
    name: str
    state: str
    published: bool
    verified: str | None = None
    city_name: str | None = None
    groups_list: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def sanitize_redacted_coordinate(cls, value: object) -> float | None:
        return _optional_float(value)

    def to_domain(self) -> Station:
        return Station(
            uuid=self.uuid,
            name=self.name,
            state=self.state,
            published=self.published,
            verified=self.verified,
            city_name=self.city_name,
            groups_list=self.groups_list,
            latitude=self.latitude,
            longitude=self.longitude,
        )


class SessionResponse(DrovaApiModel):
    uuid: str
    server_id: str
    merchant_id: str
    product_id: str
    client_id: str | None = None
    creator_ip: str | None = None
    created_on_ms: int = Field(alias="created_on")
    finished_on_ms: int | None = Field(default=None, alias="finished_on")
    billing_type: str | None = None
    status: str | None = None
    score_text: str | None = None

    def to_domain(self) -> Session:
        return Session(
            uuid=self.uuid,
            server_id=self.server_id,
            merchant_id=self.merchant_id,
            product_id=self.product_id,
            client_id=self.client_id,
            creator_ip=self.creator_ip,
            created_on_ms=self.created_on_ms,
            finished_on_ms=self.finished_on_ms,
            billing_type=self.billing_type,
            status=self.status,
            score_text=self.score_text,
        )


class SessionPageResponse(DrovaApiModel):
    sessions: list[SessionResponse] = Field(default_factory=list)

    @classmethod
    def parse_payload(cls, payload: Any) -> SessionPageResponse:
        if isinstance(payload, list):
            return cls(sessions=payload)
        return cls.model_validate(payload)

    def to_domain(self) -> SessionPage:
        return SessionPage(sessions=[session.to_domain() for session in self.sessions])


class StationProductResponse(DrovaApiModel):
    product_id: str = Field(alias="productId")
    title: str
    enabled: bool
    published: bool
    available: bool

    def to_domain(self) -> StationProduct:
        return StationProduct(
            product_id=self.product_id,
            title=self.title,
            enabled=self.enabled,
            published=self.published,
            available=self.available,
        )


class CatalogProductResponse(DrovaApiModel):
    product_id: str = Field(alias="productId")
    title: str

    def to_domain(self) -> CatalogProduct:
        return CatalogProduct(product_id=self.product_id, title=self.title)


class EndpointResponse(DrovaApiModel):
    uuid: str
    server_id: str
    ip: str
    base_port: int
    externally_routable: bool | None = None

    def to_domain(self) -> Endpoint:
        return Endpoint(
            uuid=self.uuid,
            server_id=self.server_id,
            ip=self.ip,
            base_port=self.base_port,
            externally_routable=self.externally_routable,
        )


class PromocodeResponse(DrovaApiModel):
    id: int
    promocode: str
    created_on_ms: int = Field(alias="created_on")
    expired_on_ms: int = Field(alias="expired_on")
    expired: bool
    merchant_id: str
    playtime_msecs: int

    def to_domain(self) -> Promocode:
        return Promocode(
            id=self.id,
            promocode=self.promocode,
            created_on_ms=self.created_on_ms,
            expired_on_ms=self.expired_on_ms,
            expired=self.expired,
            merchant_id=self.merchant_id,
            playtime_msecs=self.playtime_msecs,
        )
