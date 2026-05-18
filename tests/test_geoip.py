from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from drova_bot.domain.models import Session
from drova_bot.geoip import _GEODB_URLS, GeoLiteResolver


class FakeReader:
    def __init__(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        self.records = records
        self.closed = False

    def get(self, ip_address: str) -> Mapping[str, Any] | None:
        return self.records.get(ip_address)

    def close(self) -> None:
        self.closed = True


def test_geodb_urls_match_runtime_sources() -> None:
    assert _GEODB_URLS == {
        "GeoLite2-City.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb",
        "GeoLite2-ASN.mmdb": "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb",
    }


def test_geolite_resolver_reads_city_asn_and_closes_readers(tmp_path: Path) -> None:
    city_path = tmp_path / "GeoLite2-City.mmdb"
    asn_path = tmp_path / "GeoLite2-ASN.mmdb"
    city_path.write_bytes(b"fake")
    asn_path.write_bytes(b"fake")
    city_reader = FakeReader(
        {
            "8.8.8.8": {
                "city": {"names": {"ru": "Маунтин-Вью", "en": "Mountain View"}},
                "location": {"latitude": 37.386, "longitude": -122.084},
            },
        }
    )
    asn_reader = FakeReader(
        {
            "8.8.8.8": {
                "autonomous_system_organization": "Google LLC",
            },
        }
    )
    readers = {
        city_path.name: city_reader,
        asn_path.name: asn_reader,
    }

    resolver = GeoLiteResolver(
        city_db_path=city_path,
        asn_db_path=asn_path,
        reader_factory=lambda path: readers[path.name],
    )

    geo = resolver.lookup_ip("8.8.8.8")

    assert geo is not None
    assert geo.city == "Маунтин-Вью"
    assert geo.provider == "Google LLC"
    assert geo.latitude == 37.386
    assert geo.longitude == -122.084

    resolver.close()
    assert city_reader.closed
    assert asn_reader.closed


def test_geolite_resolver_is_optional_and_handles_bad_ip(tmp_path: Path) -> None:
    resolver = GeoLiteResolver(
        city_db_path=tmp_path / "missing-city.mmdb",
        asn_db_path=tmp_path / "missing-asn.mmdb",
        reader_factory=lambda path: (_ for _ in ()).throw(AssertionError(path)),
    )

    assert resolver.lookup_ip("not-an-ip") is None
    assert resolver.lookup_ip("8.8.8.8") is None


def test_geolite_resolver_can_lookup_session_creator_ip(tmp_path: Path) -> None:
    city_path = tmp_path / "GeoLite2-City.mmdb"
    asn_path = tmp_path / "GeoLite2-ASN.mmdb"
    city_path.write_bytes(b"fake")
    asn_path.write_bytes(b"fake")
    reader = FakeReader({"8.8.4.4": {"city": {"names": {"en": "Example City"}}}})
    session = Session(
        uuid="session-1",
        server_id="station-1",
        merchant_id="user-1",
        product_id="product-1",
        client_id="client-1",
        creator_ip="8.8.4.4",
        created_on_ms=1,
        finished_on_ms=2,
    )
    resolver = GeoLiteResolver(
        city_db_path=city_path,
        asn_db_path=asn_path,
        reader_factory=lambda path: reader,
    )

    geo = resolver.lookup_session(session)

    assert geo is not None
    assert geo.city == "Example City"
