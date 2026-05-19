"""Application service layer for Telegram command behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from drova_bot.application.export_jobs import ExportJob
from drova_bot.application.protocols import DrovaClientFactory, DrovaClientProtocol, TokenPersister
from drova_bot.config import Settings
from drova_bot.domain.formatters import normalize_session_limit
from drova_bot.domain.models import ChatProfile, Session, Station
from drova_bot.drova import DrovaClient
from drova_bot.drova.errors import (
    DrovaPermissionDenied,
    DrovaUnauthorized,
    DrovaUnavailable,
    ExportTooLarge,
)
from drova_bot.exports import ExportKind, ExportResult, ProductExportService, SessionExportService
from drova_bot.storage.uow import StorageUnitOfWork
from drova_bot.telegram.callbacks import ParsedCallback
from drova_bot.telegram.renderers import (
    RenderedMessage,
    SessionGeoResolver,
    latest_sessions_by_station,
    render_account_billing,
    render_current,
    render_disabled,
    render_error,
    render_game_enabled_result,
    render_promocode_issued,
    render_publish_confirmation,
    render_sessions,
    render_start_connected,
    render_start_not_connected,
    render_station_game_detail,
    render_station_games,
    render_station_picker,
    render_stations,
    render_unused_promocodes,
    render_usage_statistics,
)

UnitOfWorkFactory = Callable[[], StorageUnitOfWork]


class DefaultDrovaClientFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(
        self,
        proxy_token: str,
        *,
        token_persister: TokenPersister | None = None,
    ) -> DrovaClientProtocol:
        return DrovaClient(
            proxy_token=proxy_token,
            base_url=self._settings.drova_base_url,
            token_persister=token_persister,
            proxy=self._settings.https_proxy or self._settings.http_proxy,
        )


class BotService:
    """Owns command behavior while Telegram handlers remain transport adapters."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        client_factory: DrovaClientFactory,
        clock: Callable[[], datetime] | None = None,
        session_export_service: SessionExportService | None = None,
        product_export_service: ProductExportService | None = None,
        export_row_limit: int = 50_000,
        export_timeout_seconds: float = 120,
        session_geo_resolver: SessionGeoResolver | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._client_factory = client_factory
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._session_export_service = session_export_service or SessionExportService()
        self._product_export_service = product_export_service or ProductExportService()
        self._export_row_limit = export_row_limit
        self._export_timeout_seconds = export_timeout_seconds
        self._session_geo_resolver = session_geo_resolver

    async def start(self, telegram_chat_id: int) -> RenderedMessage:
        async with self._uow_factory() as uow:
            profile = await uow.chat_profiles.get(telegram_chat_id)
            if profile is None or profile.encrypted_proxy_token is None:
                return render_start_not_connected()
            station_names = await uow.station_cache.station_names(telegram_chat_id)
            selected_name = (
                station_names.get(profile.selected_station_id)
                if profile.selected_station_id is not None
                else None
            )
            return render_start_connected(
                station_count=len(station_names),
                selected_station_name=selected_name,
                session_limit=profile.session_limit,
            )

    async def connect_token(self, telegram_chat_id: int, proxy_token: str) -> RenderedMessage:
        if not proxy_token.strip():
            return render_error("drova_unauthorized")
        client = self._client_factory.create(proxy_token.strip())
        try:
            account = await client.get_account()
            products = await client.get_products_full()
            stations = await client.get_servers(account.uuid)
        except DrovaUnauthorized:
            return render_error("drova_unauthorized")
        except (DrovaPermissionDenied, DrovaUnavailable):
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

        async with self._uow_factory() as uow:
            profile = await uow.chat_profiles.connect_token(
                telegram_chat_id,
                drova_user_id=account.uuid,
                proxy_token=client.proxy_token,
            )
            await uow.product_cache.upsert_catalog(products)
            await uow.station_cache.replace_for_chat(telegram_chat_id, stations)

        return render_start_connected(
            station_count=len(stations),
            selected_station_name=None,
            session_limit=profile.session_limit,
        )

    async def logout(self, telegram_chat_id: int) -> RenderedMessage:
        async with self._uow_factory() as uow:
            await uow.chat_profiles.logout(telegram_chat_id)
        return RenderedMessage("Токен и настройки чата удалены.")

    async def station_picker(self, telegram_chat_id: int, *, page: int = 0) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_station_picker(stations, page=page)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def select_station(self, telegram_chat_id: int, station_id: str) -> RenderedMessage:
        async with self._uow_factory() as uow:
            station_name = await uow.station_cache.station_name(telegram_chat_id, station_id)
            if station_name is None:
                return render_error("station_not_found")
            await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
        return RenderedMessage(f"Выбрана станция: {station_name}")

    async def select_all_stations(self, telegram_chat_id: int) -> RenderedMessage:
        async with self._uow_factory() as uow:
            await uow.chat_profiles.set_selected_station(telegram_chat_id, None)
        return RenderedMessage("Выбраны все станции.")

    async def set_limit(self, telegram_chat_id: int, raw_limit: str | None) -> RenderedMessage:
        if raw_limit is None:
            return render_error("invalid_limit")
        limit = normalize_session_limit(raw_limit)
        if str(limit) != raw_limit.strip():
            return render_error("invalid_limit")
        async with self._uow_factory() as uow:
            await uow.chat_profiles.set_session_limit(telegram_chat_id, limit)
        return RenderedMessage(f"Лимит сессий: {limit}")

    async def issue_promocode(
        self,
        telegram_chat_id: int,
        raw_minutes: str | None,
    ) -> RenderedMessage:
        minutes = _parse_promocode_minutes(raw_minutes)
        if minutes is None:
            return render_error("invalid_promocode_minutes")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            promocodes = await client.issue_promocode(minutes)
            return render_promocode_issued(
                promocodes,
                requested_minutes=minutes,
                timezone=profile.timezone,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def unused_promocodes(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            promocodes = await client.get_unused_promocodes()
            return render_unused_promocodes(promocodes, timezone=profile.timezone)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def account_billing(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            merchant_id = profile.drova_user_id or ""
            stats = await client.get_prepaid_stats(merchant_id)
            settlements = await client.get_prepaid_settlements(merchant_id)
            opened_deals = await client.get_opened_prepaid_deals()
            return render_account_billing(
                stats,
                settlements=settlements,
                opened_deals=opened_deals,
                timezone=profile.timezone,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def sessions(
        self,
        telegram_chat_id: int,
        *,
        short_mode: bool = False,
        page: int = 0,
    ) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            sessions_page = await client.get_sessions(
                merchant_id=None if profile.selected_station_id else profile.drova_user_id,
                server_id=profile.selected_station_id,
                limit=profile.session_limit,
            )
            product_catalog = await self._product_catalog(telegram_chat_id, client)
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_sessions(
                profile,
                sessions_page.sessions,
                stations,
                product_catalog,
                now=self._clock(),
                short_mode=short_mode,
                page=page,
                geo_resolver=self._session_geo_resolver,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def current(
        self,
        telegram_chat_id: int,
        *,
        publish_panel_open: bool = False,
    ) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            product_catalog = await self._product_catalog(telegram_chat_id, client)
            latest: dict[str, Session | None] = {}
            failed_station_ids: set[str] = set()
            for station in stations:
                try:
                    page = await client.get_sessions(server_id=station.uuid, limit=1)
                    latest[station.uuid] = page.sessions[0] if page.sessions else None
                except DrovaUnavailable:
                    failed_station_ids.add(station.uuid)
                    latest[station.uuid] = None
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_current(
                profile,
                stations,
                latest,
                product_catalog,
                now=self._clock(),
                publish_panel_open=publish_panel_open,
                failed_station_ids=failed_station_ids,
                geo_resolver=self._session_geo_resolver,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def usage_statistics(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            statistics = await client.get_server_usage_statistics()
            catalog = await self._product_catalog(telegram_chat_id, client)
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_usage_statistics(statistics, stations, catalog)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def disabled(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            products_by_station = {
                station.uuid: await client.get_server_products(
                    profile.drova_user_id or "",
                    station.uuid,
                )
                for station in stations
            }
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_disabled(stations, products_by_station)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def stations(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            endpoints_by_station = {
                station.uuid: await client.get_server_endpoints(station.uuid, limit=5)
                for station in stations
            }
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_stations(stations, endpoints_by_station)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_games(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            products = await client.get_server_products(profile.drova_user_id or "", station.uuid)
            return render_station_games(station, products)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_game(
        self,
        telegram_chat_id: int,
        raw_product_id: str | None,
    ) -> RenderedMessage:
        product_id = _parse_product_id(raw_product_id)
        if product_id is None:
            return render_error("invalid_product_id")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            product = await client.get_server_product_edit(station.uuid, product_id)
            return render_station_game_detail(station, product)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def set_station_game_enabled(
        self,
        telegram_chat_id: int,
        raw_product_id: str | None,
        *,
        enabled: bool,
    ) -> RenderedMessage:
        product_id = _parse_product_id(raw_product_id)
        if product_id is None:
            return render_error("invalid_product_id")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            await client.set_server_product_enabled(station.uuid, product_id, enabled)
            product = await client.get_server_product_edit(station.uuid, product_id)
            return render_game_enabled_result(
                product_title=product.title,
                product_id=product.product_id,
                enabled=enabled,
                updated_station_names=[station.name],
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def hide_game_all(
        self,
        telegram_chat_id: int,
        raw_product_id: str | None,
    ) -> RenderedMessage:
        product_id = _parse_product_id(raw_product_id)
        if product_id is None:
            return render_error("invalid_product_id")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            updated: list[str] = []
            failed: list[str] = []
            for station in stations:
                try:
                    await client.set_server_product_enabled(station.uuid, product_id, False)
                    updated.append(station.name)
                except DrovaUnavailable:
                    failed.append(station.name)
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_game_enabled_result(
                product_title=None,
                product_id=product_id,
                enabled=False,
                updated_station_names=updated,
                failed_station_names=failed,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def export(self, telegram_chat_id: int, kind: ExportKind) -> ExportResult:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return ExportResult(files=[], message=render_error("not_connected").text)
        profile, client = loaded
        try:
            return await asyncio.wait_for(
                self._export_with_client(profile, client, kind),
                timeout=self._export_timeout_seconds,
            )
        except ExportTooLarge:
            return ExportResult(
                files=[],
                message="Выгрузка слишком большая. Уменьшите объем данных.",
            )
        except TimeoutError:
            return ExportResult(
                files=[],
                message="Не удалось подготовить файл за отведенное время.",
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return ExportResult(files=[], message=render_error("drova_unauthorized").text)
        except DrovaUnavailable:
            return ExportResult(files=[], message=render_error("drova_unavailable").text)
        finally:
            await client.aclose()

    async def create_export_job(self, telegram_chat_id: int, kind: ExportKind) -> ExportJob:
        job_id = uuid4().hex
        async with self._uow_factory() as uow:
            row = await uow.export_jobs.create(
                job_id=job_id,
                telegram_chat_id=telegram_chat_id,
                kind=kind.value,
            )
            return ExportJob(
                id=row.id,
                telegram_chat_id=row.telegram_chat_id,
                kind=kind,
                status=row.status,
                error_code=row.error_code,
            )

    async def run_export_job(
        self,
        *,
        job_id: str,
        telegram_chat_id: int,
        kind: ExportKind,
    ) -> ExportResult:
        async with self._uow_factory() as uow:
            await uow.export_jobs.mark_running(job_id)
        try:
            result = await self.export(telegram_chat_id, kind)
        except Exception:
            async with self._uow_factory() as uow:
                await uow.export_jobs.mark_failed(job_id, "unexpected_export_error")
            return ExportResult(files=[], message="Не удалось подготовить файл.")

        async with self._uow_factory() as uow:
            if result.files:
                await uow.export_jobs.mark_done(job_id)
            else:
                await uow.export_jobs.mark_failed(job_id, _export_error_code(result.message))
        return result

    async def fail_export_job(self, job_id: str, error_code: str) -> None:
        async with self._uow_factory() as uow:
            await uow.export_jobs.mark_failed(job_id, error_code)

    async def publish_confirmation(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            station = _find_station(stations, station_id)
            if station is None:
                return render_error("station_not_found")
            return render_publish_confirmation(station, new_state=not station.published)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def confirm_publish(
        self,
        telegram_chat_id: int,
        station_id: str | None,
        expected_published: bool | None,
    ) -> RenderedMessage:
        if station_id is None or expected_published is None:
            return render_error("station_not_found")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            station = _find_station(stations, station_id)
            if station is None:
                return render_error("station_not_found")
            if station.published != expected_published:
                return render_error("stale_publish")
            await client.set_server_published(station_id, not expected_published)
            refreshed = await client.get_servers(profile.drova_user_id or "")
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, refreshed)
            product_catalog = await self._product_catalog(telegram_chat_id, client)
            latest = await self._latest_for_stations(client, refreshed)
            return render_current(
                profile,
                refreshed,
                latest,
                product_catalog,
                now=self._clock(),
                publish_panel_open=True,
                geo_resolver=self._session_geo_resolver,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def cancel_publish(self, telegram_chat_id: int) -> RenderedMessage:
        return RenderedMessage("Отменено.")

    async def handle_callback(
        self,
        telegram_chat_id: int,
        callback: ParsedCallback,
    ) -> RenderedMessage:
        if callback.action == "station_all":
            return await self.select_all_stations(telegram_chat_id)
        if callback.action == "station_select" and callback.station_id is not None:
            return await self.select_station(telegram_chat_id, callback.station_id)
        if callback.action == "station_page":
            return await self.station_picker(telegram_chat_id, page=callback.page or 0)
        if callback.action == "sessions_refresh":
            return await self.sessions(telegram_chat_id, page=callback.page or 0)
        if callback.action == "sessions_page":
            return await self.sessions(telegram_chat_id, page=callback.page or 0)
        if callback.action == "sessions_short_page":
            return await self.sessions(
                telegram_chat_id,
                short_mode=True,
                page=callback.page or 0,
            )
        if callback.action == "sessions_short":
            return await self.sessions(
                telegram_chat_id,
                short_mode=True,
                page=callback.page or 0,
            )
        if callback.action == "sessions_all":
            return await self.sessions(telegram_chat_id, page=callback.page or 0)
        if callback.action == "current_refresh":
            return await self.current(telegram_chat_id)
        if callback.action == "current_refresh_panel":
            return await self.current(telegram_chat_id, publish_panel_open=True)
        if callback.action == "publish_panel":
            return await self.current(telegram_chat_id, publish_panel_open=True)
        if callback.action == "publish_hide":
            return await self.current(telegram_chat_id)
        if callback.action == "publish_select":
            return await self.publish_confirmation(telegram_chat_id, callback.station_id)
        if callback.action == "publish_confirm":
            return await self.confirm_publish(
                telegram_chat_id,
                callback.station_id,
                callback.expected_published,
            )
        if callback.action == "publish_cancel":
            return await self.cancel_publish(telegram_chat_id)
        return render_error("unknown_command")

    async def _selected_station_context(
        self,
        telegram_chat_id: int,
        profile: ChatProfile,
        client: DrovaClientProtocol,
    ) -> Station | RenderedMessage:
        if profile.selected_station_id is None:
            return render_error("station_required")
        stations = await client.get_servers(profile.drova_user_id or "")
        station = _find_station(stations, profile.selected_station_id)
        if station is None:
            return render_error("station_not_found")
        async with self._uow_factory() as uow:
            await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
        return station

    async def _load_client(
        self,
        telegram_chat_id: int,
    ) -> tuple[ChatProfile, DrovaClientProtocol] | None:
        async with self._uow_factory() as uow:
            profile = await uow.chat_profiles.get(telegram_chat_id)
            token = await uow.chat_profiles.decrypt_token(telegram_chat_id)
        if profile is None or not profile.drova_user_id or token is None:
            return None

        async def persist_token(new_token: str) -> None:
            async with self._uow_factory() as token_uow:
                await token_uow.chat_profiles.update_token(telegram_chat_id, new_token)

        return profile, self._client_factory.create(token, token_persister=persist_token)

    async def _product_catalog(
        self,
        telegram_chat_id: int,
        client: DrovaClientProtocol,
    ) -> dict[str, str]:
        async with self._uow_factory() as uow:
            catalog = await uow.product_cache.title_map()
        if catalog:
            return catalog
        products = await client.get_products_full()
        async with self._uow_factory() as uow:
            await uow.product_cache.upsert_catalog(products)
        return {product.product_id: product.title for product in products}

    async def _latest_for_stations(
        self,
        client: DrovaClientProtocol,
        stations: list[Station],
    ) -> dict[str, Session | None]:
        sessions: list[Session] = []
        latest: dict[str, Session | None] = {}
        for station in stations:
            page = await client.get_sessions(server_id=station.uuid, limit=1)
            if page.sessions:
                sessions.extend(page.sessions)
            latest[station.uuid] = page.sessions[0] if page.sessions else None
        return latest_sessions_by_station(sessions) | {
            station.uuid: latest.get(station.uuid)
            for station in stations
            if station.uuid not in latest
        }

    async def _export_with_client(
        self,
        profile: ChatProfile,
        client: DrovaClientProtocol,
        kind: ExportKind,
    ) -> ExportResult:
        if kind in {ExportKind.SESSIONS, ExportKind.SESSIONS_CSV}:
            return await self._export_sessions(profile, client, kind)
        if kind == ExportKind.PRODUCTS:
            return await self._export_products(profile, client)
        if kind == ExportKind.PRODUCT_TIME:
            return await self._export_product_time(profile, client)
        return ExportResult(files=[], message="Неизвестный тип выгрузки.")

    async def _export_sessions(
        self,
        profile: ChatProfile,
        client: DrovaClientProtocol,
        kind: ExportKind,
    ) -> ExportResult:
        stations = await client.get_servers(profile.drova_user_id or "")
        selected_stations = _selected_stations(stations, profile)
        if profile.selected_station_id is not None and not selected_stations:
            return ExportResult(files=[], message=render_error("station_not_found").text)
        page = await client.get_sessions(
            merchant_id=None if profile.selected_station_id else profile.drova_user_id,
            server_id=profile.selected_station_id,
            limit=None,
        )
        self._ensure_row_limit(len(page.sessions))
        product_catalog = await self._product_catalog(profile.telegram_chat_id, client)
        if kind == ExportKind.SESSIONS_CSV:
            files = await self._session_export_service.build_sessions_csv_by_station(
                sessions=page.sessions,
                stations=selected_stations,
                product_catalog=product_catalog,
                now=self._clock(),
                timezone=profile.timezone,
            )
        else:
            files = [
                await self._session_export_service.build_sessions_xlsx(
                    sessions=page.sessions,
                    stations=selected_stations,
                    product_catalog=product_catalog,
                    now=self._clock(),
                    timezone=profile.timezone,
                )
            ]
        return ExportResult(files=files, message=_export_ready_message(files))

    async def _export_products(
        self,
        profile: ChatProfile,
        client: DrovaClientProtocol,
    ) -> ExportResult:
        stations = await client.get_servers(profile.drova_user_id or "")
        products_by_station = {
            station.uuid: await client.get_server_products(
                profile.drova_user_id or "",
                station.uuid,
            )
            for station in stations
        }
        self._ensure_row_limit(sum(len(products) for products in products_by_station.values()))
        file = await self._product_export_service.build_products_xlsx(
            stations=stations,
            products_by_station=products_by_station,
            now=self._clock(),
        )
        return ExportResult(files=[file], message="Файл готов.")

    async def _export_product_time(
        self,
        profile: ChatProfile,
        client: DrovaClientProtocol,
    ) -> ExportResult:
        stations = await client.get_servers(profile.drova_user_id or "")
        page = await client.get_sessions(merchant_id=profile.drova_user_id, limit=None)
        self._ensure_row_limit(len(page.sessions))
        product_catalog = await self._product_catalog(profile.telegram_chat_id, client)
        file = await self._product_export_service.build_product_time_xlsx(
            stations=stations,
            sessions=page.sessions,
            product_catalog=product_catalog,
            now=self._clock(),
        )
        return ExportResult(files=[file], message="Файл готов.")

    def _ensure_row_limit(self, row_count: int) -> None:
        if row_count > self._export_row_limit:
            raise ExportTooLarge("export row limit exceeded")


def _find_station(stations: list[Station], station_id: str) -> Station | None:
    return next((station for station in stations if station.uuid == station_id), None)


def _selected_stations(stations: list[Station], profile: ChatProfile) -> list[Station]:
    if profile.selected_station_id is None:
        return stations
    return [station for station in stations if station.uuid == profile.selected_station_id]


def _parse_promocode_minutes(raw_minutes: str | None) -> int | None:
    if raw_minutes is None:
        return None
    try:
        minutes = int(raw_minutes.strip())
    except ValueError:
        return None
    if minutes <= 0:
        return None
    return minutes


def _parse_product_id(raw_product_id: str | None) -> str | None:
    if raw_product_id is None:
        return None
    product_id = raw_product_id.strip()
    return product_id or None


def _export_ready_message(files: Sequence[object]) -> str:
    if len(files) == 1:
        return "Файл готов."
    return f"Файлы готовы: {len(files)}."


def _export_error_code(message: str) -> str:
    if "Сначала подключите" in message:
        return "not_connected"
    if "слишком большая" in message:
        return "export_too_large"
    if "отведенное время" in message:
        return "export_timeout"
    if "Токен недействителен" in message:
        return "drova_unauthorized"
    if "Drova" in message:
        return "drova_unavailable"
    return "export_failed"
