"""Optional GeoLite IP lookup helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Protocol, cast

import structlog

from drova_bot.domain.models import Session
from drova_bot.telegram.renderers import EndpointGeo

_GEODB_URLS = {
    "GeoLite2-City.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb",
    "GeoLite2-ASN.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb",
}

logger = structlog.get_logger(__name__)


class GeoReader(Protocol):
    def get(self, ip_address: str) -> Mapping[str, Any] | None: ...

    def close(self) -> None: ...


ReaderFactory = Callable[[Path], GeoReader]


def _open_maxmind_reader(path: Path) -> GeoReader:
    module = cast(Any, import_module("maxminddb"))
    return cast(GeoReader, module.open_database(str(path)))


class GeoLiteResolver:
    """Lazy local GeoLite reader used by renderers through a safe callback."""

    def __init__(
        self,
        *,
        city_db_path: str | Path,
        asn_db_path: str | Path,
        reader_factory: ReaderFactory = _open_maxmind_reader,
    ) -> None:
        self.city_db_path = Path(city_db_path)
        self.asn_db_path = Path(asn_db_path)
        self._reader_factory = reader_factory
        self._city_reader: GeoReader | None = None
        self._asn_reader: GeoReader | None = None
        self._city_open_attempted = False
        self._asn_open_attempted = False

    def lookup_session(self, session: Session) -> EndpointGeo | None:
        return self.lookup_ip(session.creator_ip)

    def lookup_ip(self, raw_ip: str | None) -> EndpointGeo | None:
        ip = _normalize_ip(raw_ip)
        if ip is None:
            return None

        city_record = _reader_get(self._city(), ip)
        asn_record = _reader_get(self._asn(), ip)
        city = _city_name(city_record)
        provider = _provider_name(asn_record)
        latitude, longitude = _coordinates(city_record)
        if city is None and provider is None and latitude is None and longitude is None:
            return None
        return EndpointGeo(city=city, provider=provider, latitude=latitude, longitude=longitude)

    def close(self) -> None:
        for reader in (self._city_reader, self._asn_reader):
            if reader is not None:
                reader.close()

    def _city(self) -> GeoReader | None:
        if not self._city_open_attempted:
            self._city_open_attempted = True
            self._city_reader = self._open_optional(self.city_db_path)
        return self._city_reader

    def _asn(self) -> GeoReader | None:
        if not self._asn_open_attempted:
            self._asn_open_attempted = True
            self._asn_reader = self._open_optional(self.asn_db_path)
        return self._asn_reader

    def _open_optional(self, path: Path) -> GeoReader | None:
        if not path.is_file():
            return None
        try:
            return self._reader_factory(path)
        except Exception as exc:
            logger.warning(
                "geolite_reader_unavailable",
                database=path.name,
                error_code=type(exc).__name__,
            )
            return None


def _normalize_ip(raw_ip: str | None) -> str | None:
    if not raw_ip:
        return None
    try:
        return str(ip_address(raw_ip))
    except ValueError:
        return None


def _reader_get(reader: GeoReader | None, ip: str) -> Mapping[str, Any] | None:
    if reader is None:
        return None
    try:
        return reader.get(ip)
    except Exception as exc:
        logger.warning("geolite_lookup_failed", error_code=type(exc).__name__)
        return None


def _city_name(record: Mapping[str, Any] | None) -> str | None:
    names = _mapping(_mapping(record).get("city")).get("names")
    if not isinstance(names, Mapping):
        return None
    return _first_text(names.get("ru"), names.get("en"))


def _provider_name(record: Mapping[str, Any] | None) -> str | None:
    return _text(_mapping(record).get("autonomous_system_organization"))


def _coordinates(record: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    location = _mapping(_mapping(record).get("location"))
    return _float(location.get("latitude")), _float(location.get("longitude"))


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _first_text(*values: object) -> str | None:
    for value in values:
        text = _text(value)
        if text is not None:
            return text
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
