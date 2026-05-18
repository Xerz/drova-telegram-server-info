"""Session CSV/XLSX export services."""

from __future__ import annotations

import asyncio
import csv
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from io import BytesIO, StringIO
from typing import cast

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from drova_bot.domain.formatters import (
    datetime_from_ms,
    format_export_duration,
    session_duration_seconds,
    sort_stations,
)
from drova_bot.domain.models import Session, Station
from drova_bot.exports.models import ExportFile

SESSION_EXPORT_HEADERS = [
    "station_name",
    "game_name",
    "creator_ip",
    "city",
    "range_km",
    "asn",
    "date",
    "duration",
    "start_time",
    "finish_time",
    "billing_type",
    "status",
    "abort_comment",
    "client_id",
    "uuid",
    "server_id",
    "merchant_id",
    "product_id",
    "created_on",
    "finished_on",
    "score",
    "score_reason",
    "score_text",
    "parent",
    "sched_hints",
]

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv; charset=utf-8"


class SessionExportService:
    async def build_sessions_xlsx(
        self,
        *,
        sessions: Sequence[Session],
        stations: Sequence[Station],
        product_catalog: Mapping[str, str],
        now: datetime,
        timezone: str,
    ) -> ExportFile:
        return await asyncio.to_thread(
            self._build_sessions_xlsx,
            sessions,
            stations,
            product_catalog,
            now,
            timezone,
        )

    async def build_sessions_csv_by_station(
        self,
        *,
        sessions: Sequence[Session],
        stations: Sequence[Station],
        product_catalog: Mapping[str, str],
        now: datetime,
        timezone: str,
    ) -> list[ExportFile]:
        return await asyncio.to_thread(
            self._build_sessions_csv_by_station,
            sessions,
            stations,
            product_catalog,
            now,
            timezone,
        )

    @staticmethod
    def sessions_filename(now: datetime) -> str:
        return f"drova-sessions-{now.strftime('%Y%m%d-%H%M%S')}.xlsx"

    @staticmethod
    def station_csv_filename(station_name: str, now: datetime) -> str:
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        return f"drova-sessions-{_sanitize_filename(station_name)}-{timestamp}.csv"

    def _build_sessions_xlsx(
        self,
        sessions: Sequence[Session],
        stations: Sequence[Station],
        product_catalog: Mapping[str, str],
        now: datetime,
        timezone: str,
    ) -> ExportFile:
        workbook = Workbook()
        worksheet = cast(Worksheet, workbook.active)
        worksheet.title = "sessions"
        worksheet.append(SESSION_EXPORT_HEADERS)
        for row in _session_rows(sessions, stations, product_catalog, now, timezone):
            worksheet.append(row)

        output = BytesIO()
        workbook.save(output)
        return ExportFile(
            filename=self.sessions_filename(now),
            content_type=XLSX_CONTENT_TYPE,
            payload=output.getvalue(),
        )

    def _build_sessions_csv_by_station(
        self,
        sessions: Sequence[Session],
        stations: Sequence[Station],
        product_catalog: Mapping[str, str],
        now: datetime,
        timezone: str,
    ) -> list[ExportFile]:
        sessions_by_station: dict[str, list[Session]] = {station.uuid: [] for station in stations}
        for session in sessions:
            sessions_by_station.setdefault(session.server_id, []).append(session)

        files: list[ExportFile] = []
        for station in sort_stations(stations):
            output = StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(SESSION_EXPORT_HEADERS)
            writer.writerows(
                _session_rows(
                    sessions_by_station.get(station.uuid, []),
                    [station],
                    product_catalog,
                    now,
                    timezone,
                )
            )
            files.append(
                ExportFile(
                    filename=self.station_csv_filename(station.name, now),
                    content_type=CSV_CONTENT_TYPE,
                    payload=output.getvalue().encode("utf-8"),
                )
            )
        return files


def _session_rows(
    sessions: Sequence[Session],
    stations: Sequence[Station],
    product_catalog: Mapping[str, str],
    now: datetime,
    timezone: str,
) -> list[list[object]]:
    station_by_id = {station.uuid: station for station in stations}
    rows: list[list[object]] = []
    for session in sorted(sessions, key=lambda item: item.created_on_ms, reverse=True):
        station = station_by_id.get(session.server_id)
        started = datetime_from_ms(session.created_on_ms, timezone)
        finished = (
            datetime_from_ms(session.finished_on_ms, timezone)
            if session.finished_on_ms is not None
            else None
        )
        rows.append(
            [
                station.name if station is not None else "",
                product_catalog.get(session.product_id, "Неизвестная игра"),
                session.creator_ip or "",
                "",
                "",
                "",
                started.strftime("%Y-%m-%d"),
                format_export_duration(session_duration_seconds(session, now)),
                started.strftime("%H:%M:%S"),
                finished.strftime("%H:%M:%S") if finished is not None else "",
                session.billing_type or "",
                session.status or "",
                "",
                session.client_id or "",
                session.uuid,
                session.server_id,
                session.merchant_id,
                session.product_id,
                session.created_on_ms,
                session.finished_on_ms or "",
                "",
                "",
                session.score_text or "",
                "",
                "",
            ]
        )
    return rows


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9А-Яа-я_-]+", "-", value.strip())
    sanitized = sanitized.strip("-").lower()
    return sanitized or "station"
