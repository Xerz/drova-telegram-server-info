"""Application service layer for Telegram command behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from drova_bot.application.export_jobs import ExportJob
from drova_bot.application.protocols import DrovaClientFactory, DrovaClientProtocol, TokenPersister
from drova_bot.config import Settings
from drova_bot.domain.formatters import normalize_session_limit
from drova_bot.domain.models import ChatProfile, ServerSource, Session, Station
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
    render_account_menu,
    render_current,
    render_disabled,
    render_error,
    render_game_enabled_result,
    render_game_hide_all_confirmation,
    render_promocode_issued,
    render_publish_confirmation,
    render_server_control_confirmation,
    render_server_control_result,
    render_server_description_preview,
    render_server_description_request,
    render_server_description_result,
    render_server_source,
    render_sessions,
    render_sessions_station_picker,
    render_start_connected,
    render_start_not_connected,
    render_station_game_detail,
    render_station_games,
    render_station_manage_panel,
    render_station_manage_picker,
    render_station_picker,
    render_station_publish_manage_confirmation,
    render_stations,
    render_unused_promocodes,
    render_usage_statistics,
)

UnitOfWorkFactory = Callable[[], StorageUnitOfWork]
DESCRIPTION_DRAFT_TTL_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class PendingDescriptionRequest:
    station: Station
    revision: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DescriptionDraft:
    station_id: str
    description: str
    revision: str
    created_at: datetime


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
        self._description_requests: dict[int, PendingDescriptionRequest] = {}
        self._description_drafts: dict[str, DescriptionDraft] = {}

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

    async def station_manage_picker(
        self,
        telegram_chat_id: int,
        *,
        page: int = 0,
    ) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            stations = await client.get_servers(profile.drova_user_id or "")
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_station_manage_picker(stations, page=page)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_manage_select(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        return await self.station_manage_panel(telegram_chat_id, station_id=station_id)

    async def station_manage_panel(
        self,
        telegram_chat_id: int,
        *,
        station_id: str | None = None,
        toast: str | None = None,
    ) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            if station_id is None:
                station_id = profile.selected_station_id
            if station_id is None:
                return render_error("station_required")
            station_source = await self._station_and_source(
                telegram_chat_id,
                profile,
                client,
                station_id,
            )
            if isinstance(station_source, RenderedMessage):
                return station_source
            station, source = station_source
            return await self._render_station_manage_panel(
                telegram_chat_id,
                profile,
                client,
                station,
                source,
                toast=toast,
            )
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

    async def account_menu(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        _profile, client = loaded
        await client.aclose()
        return render_account_menu()

    async def account_menu_result(
        self,
        telegram_chat_id: int,
        action: str,
    ) -> RenderedMessage:
        if action == "balance":
            rendered = await self.account_billing(telegram_chat_id)
        elif action == "usage":
            rendered = await self.usage_statistics(telegram_chat_id)
        elif action == "promocodes":
            rendered = await self.unused_promocodes(telegram_chat_id)
        else:
            return render_error("unknown_command")
        if rendered.text == render_error("not_connected").text:
            return rendered
        return render_account_menu(rendered.text)

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

    async def sessions_station_picker(
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
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            return render_sessions_station_picker(stations, short_mode=short_mode, page=page)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def sessions_select_station(
        self,
        telegram_chat_id: int,
        station_id: str | None,
        *,
        short_mode: bool = False,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        async with self._uow_factory() as uow:
            station_name = await uow.station_cache.station_name(telegram_chat_id, station_id)
            if station_name is None:
                return render_error("station_not_found")
            await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
        return await self.sessions(telegram_chat_id, short_mode=short_mode)

    async def sessions_select_all_stations(
        self,
        telegram_chat_id: int,
        *,
        short_mode: bool = False,
    ) -> RenderedMessage:
        async with self._uow_factory() as uow:
            await uow.chat_profiles.set_selected_station(telegram_chat_id, None)
        return await self.sessions(telegram_chat_id, short_mode=short_mode)

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

    async def station_games(self, telegram_chat_id: int, *, page: int = 0) -> RenderedMessage:
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
            return render_station_games(station, products, page=page)
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
        *,
        page: int = 0,
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
            return render_station_game_detail(station, product, page=page)
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
        page: int = 0,
        render_panel: bool = False,
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
            if render_panel:
                toast = "Игра открыта." if enabled else "Игра скрыта."
                rendered = render_station_game_detail(station, product, page=page)
                return RenderedMessage(
                    rendered.text,
                    rendered.keyboard,
                    rendered.parse_mode,
                    toast,
                )
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

    async def hide_game_all_confirmation(
        self,
        telegram_chat_id: int,
        raw_product_id: str | None,
        *,
        page: int = 0,
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
            return render_game_hide_all_confirmation(station, product, page=page)
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

    async def server_control_confirmation(
        self,
        telegram_chat_id: int,
        action: str,
    ) -> RenderedMessage:
        if not _is_server_control_action(action):
            return render_error("invalid_server_control")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return render_server_control_confirmation(station, source, action=action)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def server_control_confirm(
        self,
        telegram_chat_id: int,
        action: str,
        raw_expected_state: str | None,
    ) -> RenderedMessage:
        expected_on = _parse_control_expected_state(raw_expected_state)
        if not _is_server_control_action(action) or expected_on is None:
            return render_error("invalid_server_control_confirmation")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            if _server_control_current_on(source, action) != expected_on:
                return render_error("stale_server_control")
            target_on = _server_control_target_on(action)
            if expected_on != target_on:
                await _apply_server_control(client, station.uuid, action, target_on)
                source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return render_server_control_result(station, source, action=action)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def server_source(self, telegram_chat_id: int) -> RenderedMessage:
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return render_server_source(station, source)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def server_description_preview(
        self,
        telegram_chat_id: int,
        raw_description: str | None,
    ) -> RenderedMessage:
        description = _parse_server_description(raw_description)
        if description is None:
            return render_error("invalid_server_description")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return render_server_description_preview(
                station,
                description=description,
                revision=_server_source_revision(source),
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def server_description_apply(
        self,
        telegram_chat_id: int,
        raw_payload: str | None,
    ) -> RenderedMessage:
        parsed = _parse_server_description_apply(raw_payload)
        if parsed is None:
            return render_error("invalid_server_description")
        expected_revision, description = parsed
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            context = await self._selected_station_context(telegram_chat_id, profile, client)
            if isinstance(context, RenderedMessage):
                return context
            station = context
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            if _server_source_revision(source) != expected_revision:
                return render_error("stale_server_source")
            await client.update_server_source(
                station.uuid,
                name=source.name,
                description=description,
            )
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return render_server_description_result(
                station,
                revision=_server_source_revision(source),
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_publish_manage_confirmation(
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
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
                await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
            return render_station_publish_manage_confirmation(station)
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_publish_manage_confirm(
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
            station = _find_station(refreshed, station_id)
            if station is None:
                return render_error("station_not_found")
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            async with self._uow_factory() as uow:
                await uow.station_cache.replace_for_chat(telegram_chat_id, refreshed)
                await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
            toast = "Станция опубликована." if station.published else "Станция скрыта."
            return await self._render_station_manage_panel(
                telegram_chat_id,
                profile,
                client,
                station,
                source,
                toast=toast,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_control_toggle(
        self,
        telegram_chat_id: int,
        station_id: str | None,
        control: str | None,
        expected_state: bool | None,
    ) -> RenderedMessage:
        if station_id is None or control not in {"desktop", "updates"} or expected_state is None:
            return render_error("invalid_server_control_confirmation")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            station_source = await self._station_and_source(
                telegram_chat_id,
                profile,
                client,
                station_id,
            )
            if isinstance(station_source, RenderedMessage):
                return station_source
            station, source = station_source
            current_on = (
                source.allow_desktop if control == "desktop" else not source.disable_updates
            )
            if current_on != expected_state:
                return render_error("stale_server_control")
            target_on = not current_on
            if control == "desktop":
                await client.set_server_allow_desktop(station.uuid, target_on)
            else:
                await client.set_server_disable_updates(station.uuid, not target_on)
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            label = "Полный доступ" if control == "desktop" else "Обновления"
            state = "включены" if target_on else "выключены"
            if control == "desktop":
                state = "включен" if target_on else "выключен"
            return await self._render_station_manage_panel(
                telegram_chat_id,
                profile,
                client,
                station,
                source,
                toast=f"{label} {state}.",
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def station_manage_games(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        async with self._uow_factory() as uow:
            await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
        return await self.station_games(telegram_chat_id)

    async def station_manage_source(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        async with self._uow_factory() as uow:
            await uow.chat_profiles.set_selected_station(telegram_chat_id, station_id)
        return await self.server_source(telegram_chat_id)

    async def begin_station_description_update(
        self,
        telegram_chat_id: int,
        station_id: str | None,
    ) -> RenderedMessage:
        if station_id is None:
            return render_error("station_not_found")
        self._cleanup_description_state()
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            station_source = await self._station_and_source(
                telegram_chat_id,
                profile,
                client,
                station_id,
            )
            if isinstance(station_source, RenderedMessage):
                return station_source
            station, source = station_source
            self._description_requests[telegram_chat_id] = PendingDescriptionRequest(
                station=station,
                revision=_server_source_revision(source),
                created_at=self._clock(),
            )
            return render_server_description_request(
                station,
                current_description=source.description,
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def consume_station_description_text(
        self,
        telegram_chat_id: int,
        text: str | None,
    ) -> RenderedMessage | None:
        self._cleanup_description_state()
        request = self._description_requests.get(telegram_chat_id)
        if request is None:
            return None
        if self._is_description_state_expired(request.created_at):
            self._description_requests.pop(telegram_chat_id, None)
            return render_error("description_draft_expired")
        description = _parse_server_description(text)
        if description is None:
            return render_error("invalid_server_description")
        draft_id = uuid4().hex[:10]
        self._description_drafts[draft_id] = DescriptionDraft(
            station_id=request.station.uuid,
            description=description,
            revision=request.revision,
            created_at=self._clock(),
        )
        self._description_requests.pop(telegram_chat_id, None)
        return render_server_description_preview(
            request.station,
            description=description,
            revision=request.revision,
            draft_id=draft_id,
        )

    async def apply_station_description_draft(
        self,
        telegram_chat_id: int,
        draft_id: str | None,
    ) -> RenderedMessage:
        if not draft_id:
            return render_error("invalid_server_description")
        self._cleanup_description_state()
        draft = self._description_drafts.get(draft_id)
        if draft is None or self._is_description_state_expired(draft.created_at):
            self._description_drafts.pop(draft_id, None)
            return render_error("description_draft_expired")
        loaded = await self._load_client(telegram_chat_id)
        if loaded is None:
            return render_error("not_connected")
        profile, client = loaded
        try:
            station_source = await self._station_and_source(
                telegram_chat_id,
                profile,
                client,
                draft.station_id,
            )
            if isinstance(station_source, RenderedMessage):
                return station_source
            station, source = station_source
            if _server_source_revision(source) != draft.revision:
                return render_error("stale_server_source")
            await client.update_server_source(
                station.uuid,
                name=source.name,
                description=draft.description,
            )
            self._description_drafts.pop(draft_id, None)
            source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
            return await self._render_station_manage_panel(
                telegram_chat_id,
                profile,
                client,
                station,
                source,
                toast="Описание обновлено.",
            )
        except (DrovaUnauthorized, DrovaPermissionDenied):
            return render_error("drova_unauthorized")
        except DrovaUnavailable:
            return render_error("drova_unavailable")
        finally:
            await client.aclose()

    async def cancel_station_description(
        self,
        telegram_chat_id: int,
        *,
        station_id: str | None = None,
        draft_id: str | None = None,
    ) -> RenderedMessage:
        self._description_requests.pop(telegram_chat_id, None)
        if draft_id is not None:
            draft = self._description_drafts.pop(draft_id, None)
            if station_id is None and draft is not None:
                station_id = draft.station_id
        if station_id is not None:
            return await self.station_manage_panel(
                telegram_chat_id,
                station_id=station_id,
                toast="Отменено.",
            )
        return RenderedMessage("Отменено.")

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

    async def _render_station_manage_panel(
        self,
        telegram_chat_id: int,
        profile: ChatProfile,
        client: DrovaClientProtocol,
        station: Station,
        source: ServerSource,
        *,
        toast: str | None = None,
    ) -> RenderedMessage:
        latest_session: Session | None = None
        latest_session_failed = False
        product_catalog: dict[str, str] = {}
        try:
            page = await client.get_sessions(server_id=station.uuid, limit=1)
            latest_session = page.sessions[0] if page.sessions else None
        except DrovaUnavailable:
            latest_session_failed = True
        if latest_session is not None:
            product_catalog = await self._product_catalog(telegram_chat_id, client)
        return render_station_manage_panel(
            station,
            source,
            latest_session=latest_session,
            latest_session_failed=latest_session_failed,
            product_catalog=product_catalog,
            now=self._clock(),
            timezone=profile.timezone,
            geo_resolver=self._session_geo_resolver,
            toast=toast,
        )

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
        if callback.action == "station_manage_page":
            return await self.station_manage_picker(telegram_chat_id, page=callback.page or 0)
        if callback.action == "station_manage_select":
            return await self.station_manage_select(telegram_chat_id, callback.station_id)
        if callback.action == "station_panel":
            return await self.station_manage_panel(
                telegram_chat_id,
                station_id=callback.station_id,
            )
        if callback.action == "station_publish_prompt":
            return await self.station_publish_manage_confirmation(
                telegram_chat_id,
                callback.station_id,
                callback.expected_published,
            )
        if callback.action == "station_publish_confirm":
            return await self.station_publish_manage_confirm(
                telegram_chat_id,
                callback.station_id,
                callback.expected_published,
            )
        if callback.action == "station_control_toggle":
            return await self.station_control_toggle(
                telegram_chat_id,
                callback.station_id,
                callback.control,
                callback.expected_state,
            )
        if callback.action == "station_games":
            return await self.station_manage_games(telegram_chat_id, callback.station_id)
        if callback.action == "station_source":
            return await self.station_manage_source(telegram_chat_id, callback.station_id)
        if callback.action == "station_description_begin":
            return await self.begin_station_description_update(
                telegram_chat_id,
                callback.station_id,
            )
        if callback.action == "station_description_apply":
            return await self.apply_station_description_draft(
                telegram_chat_id,
                callback.draft_id,
            )
        if callback.action == "station_description_cancel":
            return await self.cancel_station_description(
                telegram_chat_id,
                station_id=callback.station_id,
                draft_id=callback.draft_id,
            )
        if callback.action == "account_menu":
            return await self.account_menu(telegram_chat_id)
        if callback.action == "account_balance":
            return await self.account_menu_result(telegram_chat_id, "balance")
        if callback.action == "account_usage":
            return await self.account_menu_result(telegram_chat_id, "usage")
        if callback.action == "account_promocodes":
            return await self.account_menu_result(telegram_chat_id, "promocodes")
        if callback.action == "sessions_station_picker":
            return await self.sessions_station_picker(
                telegram_chat_id,
                short_mode=callback.short_mode or False,
                page=callback.page or 0,
            )
        if callback.action == "sessions_station_select":
            return await self.sessions_select_station(
                telegram_chat_id,
                callback.station_id,
                short_mode=callback.short_mode or False,
            )
        if callback.action == "sessions_station_all":
            return await self.sessions_select_all_stations(
                telegram_chat_id,
                short_mode=callback.short_mode or False,
            )
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
            return await self.station_manage_picker(telegram_chat_id)
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
        if callback.action == "game_page":
            return await self.station_games(telegram_chat_id, page=callback.page or 0)
        if callback.action == "game_select":
            return await self.station_game(
                telegram_chat_id,
                callback.product_id,
                page=callback.page or 0,
            )
        if callback.action == "game_hide":
            return await self.set_station_game_enabled(
                telegram_chat_id,
                callback.product_id,
                enabled=False,
                page=callback.page or 0,
                render_panel=True,
            )
        if callback.action == "game_show":
            return await self.set_station_game_enabled(
                telegram_chat_id,
                callback.product_id,
                enabled=True,
                page=callback.page or 0,
                render_panel=True,
            )
        if callback.action in {"game_hide_all", "game_hide_all_prompt"}:
            return await self.hide_game_all_confirmation(
                telegram_chat_id,
                callback.product_id,
                page=callback.page or 0,
            )
        if callback.action == "game_hide_all_confirm":
            return await self.hide_game_all(telegram_chat_id, callback.product_id)
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

    async def _station_and_source(
        self,
        telegram_chat_id: int,
        profile: ChatProfile,
        client: DrovaClientProtocol,
        station_id: str,
    ) -> tuple[Station, ServerSource] | RenderedMessage:
        stations = await client.get_servers(profile.drova_user_id or "")
        station = _find_station(stations, station_id)
        if station is None:
            return render_error("station_not_found")
        source = await client.get_server_source(station.uuid, profile.drova_user_id or "")
        async with self._uow_factory() as uow:
            await uow.station_cache.replace_for_chat(telegram_chat_id, stations)
            await uow.chat_profiles.set_selected_station(telegram_chat_id, station.uuid)
        return station, source

    def _cleanup_description_state(self) -> None:
        expired_chats = [
            chat_id
            for chat_id, request in self._description_requests.items()
            if self._is_description_state_expired(request.created_at)
        ]
        for chat_id in expired_chats:
            self._description_requests.pop(chat_id, None)
        expired_drafts = [
            draft_id
            for draft_id, draft in self._description_drafts.items()
            if self._is_description_state_expired(draft.created_at)
        ]
        for draft_id in expired_drafts:
            self._description_drafts.pop(draft_id, None)

    def _is_description_state_expired(self, created_at: datetime) -> bool:
        return (self._clock() - created_at).total_seconds() > DESCRIPTION_DRAFT_TTL_SECONDS

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


def _parse_server_description(raw_description: str | None) -> str | None:
    if raw_description is None:
        return None
    description = raw_description.strip()
    return description or None


def _parse_server_description_apply(raw_payload: str | None) -> tuple[str, str] | None:
    if raw_payload is None:
        return None
    revision, separator, description = raw_payload.strip().partition(" ")
    if not separator or not revision.strip():
        return None
    parsed_description = _parse_server_description(description)
    if parsed_description is None:
        return None
    return revision.strip(), parsed_description


def _server_source_revision(source: ServerSource) -> str:
    payload = f"{source.name}\0{source.description}".encode()
    return sha256(payload).hexdigest()[:12]


SERVER_CONTROL_ACTIONS = frozenset(
    {
        "desktop_on",
        "desktop_off",
        "updates_on",
        "updates_off",
    }
)


def _is_server_control_action(action: str) -> bool:
    return action in SERVER_CONTROL_ACTIONS


def _parse_control_expected_state(raw_expected_state: str | None) -> bool | None:
    if raw_expected_state is None:
        return None
    expected = raw_expected_state.strip().casefold()
    if expected == "on":
        return True
    if expected == "off":
        return False
    return None


def _server_control_current_on(source: ServerSource, action: str) -> bool:
    if action.startswith("desktop_"):
        return source.allow_desktop
    return not source.disable_updates


def _server_control_target_on(action: str) -> bool:
    return action.endswith("_on")


async def _apply_server_control(
    client: DrovaClientProtocol,
    station_id: str,
    action: str,
    target_on: bool,
) -> None:
    if action.startswith("desktop_"):
        await client.set_server_allow_desktop(station_id, target_on)
    else:
        await client.set_server_disable_updates(station_id, not target_on)


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
