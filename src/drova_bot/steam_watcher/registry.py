"""Reviewed public Drova IDs; never infer a distribution channel from a title.

Registry revision 2; Fortnite added 2026-10-15. Protocol references: specs/v2/platform-updates.md.
Unverified Battle.net products remain unmapped instead of guessing NGDP product codes.
"""

from __future__ import annotations

from drova_bot.domain.models import CatalogProduct
from drova_bot.game_updates.models import UpdateObject, steam_games

REGISTRY_VERSION = 2
ACCOUNTS = {
    "hoyo": "hoYoverse",
    "wuwa": "KuroGames",
    "endfield": "Hypergryph",
    "battlenet": "Battle.net",
    "bsg": "Escape from Tarkov",
    "epic": "Epic Games",
}
# product UUID, compact key, external delivery ID, official information page
ENTRIES = {
    "epic": [
        (
            "d5f88d94-87d5-11e7-bb31-000000003778",
            "fortnite",
            "Fortnite",
            "https://www.fortnite.com/news",
        )
    ],
    "hoyo": [
        (
            "b05acb00-93ab-4b6d-ab6c-792f72e43665",
            "genshin",
            "gopR6Cufr3",
            "https://genshin.hoyoverse.com/en/",
        ),
        ("5e3c271e-da2a-4898-a420-9b49d74f2695", "hsr", "4ziysqXOQ8", "https://hsr.hoyoverse.com/"),
        (
            "0864eddb-d20d-437d-a322-329ccda51ad0",
            "zzz",
            "U5hbdsT9W7",
            "https://zenless.hoyoverse.com/",
        ),
    ],
    "wuwa": [
        (
            "934386db-5b9e-4635-ab70-59d02b6a988d",
            "global",
            "game",
            "https://wutheringwaves.kurogames.com/en/",
        )
    ],
    "endfield": [
        (
            "b155980e-02e8-4d2d-898b-6d659c6f6aab",
            "global",
            "game",
            "https://endfield.gryphline.com/en-us/",
        )
    ],
    "bsg": [
        ("cdb6d8f4-6b6f-4f92-a240-56447ed9b42d", "eft", "eft", "https://www.escapefromtarkov.com/"),
        ("1b4253f2-11ae-4d14-92aa-b506a18cf247", "arena", "arena", "https://arena.tarkov.com/"),
    ],
    "battlenet": [
        (
            "d5f88d94-87d5-11e7-bb31-000000003604",
            "wow-eu",
            "wow",
            "https://worldofwarcraft.blizzard.com/",
        ),
        ("7ef2d90d-b082-4f9a-928f-e8779cd0439f", "d3-eu", "d3", "https://diablo3.blizzard.com/"),
        ("8560ca9a-f695-4e32-83bf-8cfb0fcee940", "d2-eu", "osi", "https://diablo2.blizzard.com/"),
        (
            "dabe7fc3-9b56-4677-ad61-b2bb20251272",
            "d4-eu",
            "fenris",
            "https://diablo4.blizzard.com/",
        ),
        (
            "bff9243e-d776-4aa4-b454-de2605c42f49",
            "sc2-eu",
            "s2",
            "https://starcraft2.blizzard.com/",
        ),
        ("d5f88d94-87d5-11e7-bb31-000000003752", "ow-eu", "pro", "https://overwatch.blizzard.com/"),
        (
            "e1f23d6f-5bed-401f-9eaa-966953a8a758",
            "hs-eu",
            "hsb",
            "https://hearthstone.blizzard.com/",
        ),
    ],
}
LINKS = {
    "wuwa": [("launcher", "launcher", "Лаунчер WuWa", "launcher")],
    "endfield": [
        ("launcher", "Official", "GRYPHLINK", "launcher"),
        ("resources", "resources", "Arknights Endfield · ресурсы", "resources"),
    ],
    "battlenet": [("launcher-eu", "bna", "Battle.net App", "launcher")],
    "bsg": [("launcher", "launcher", "BSG Launcher", "launcher")],
}


def catalog_objects(
    products: list[CatalogProduct], enabled: set[str]
) -> tuple[list[UpdateObject], dict[str, int]]:
    objects = steam_games(products) if "steam" in enabled else []
    unmapped = {p: 0 for p in enabled}
    by_id = {p.product_id: p for p in products}
    for provider, entries in ENTRIES.items():
        if provider not in enabled:
            continue
        games = []
        matched = set()
        for pid, key, external, url in entries:
            product = by_id.get(pid)
            if not product or product.required_account != ACCOUNTS[provider]:
                continue
            matched.add(pid)
            games.append(
                UpdateObject.model_validate(
                    dict(
                        id=f"{provider}:{key}",
                        provider=provider,
                        external_id=external,
                        title=product.title,
                        channel=(
                            "live"
                            if provider == "epic"
                            else "eu"
                            if provider == "battlenet"
                            else "global"
                        ),
                        news_url=url,
                        coverage="launcher_only" if provider == "bsg" else "full",
                    )
                )
            )
        if provider == "hoyo":
            # No current Drova UUID for HI3. Explicit official Global URL only;
            # SEA/JP/KR/TW and arbitrary matching titles must remain unmapped.
            from urllib.parse import urlsplit

            for product in products:
                parsed_url = urlsplit(product.in_shop_url or "")
                if (
                    product.required_account == ACCOUNTS[provider]
                    and parsed_url.scheme == "https"
                    and parsed_url.hostname == "honkaiimpact3.hoyoverse.com"
                    and parsed_url.path.rstrip("/") in {"/global", "/global/en-us"}
                    and not parsed_url.username
                    and not parsed_url.password
                ):
                    matched.add(product.product_id)
                    if not any(g.id == "hoyo:hi3-global" for g in games):
                        games.append(
                            UpdateObject(
                                id="hoyo:hi3-global",
                                provider="hoyo",
                                external_id="5TIVvvcwtM",
                                title=product.title,
                                channel="global",
                                news_url="https://honkaiimpact3.hoyoverse.com/global/",
                            )
                        )
        unmapped[provider] = sum(
            p.required_account == ACCOUNTS[provider] and p.product_id not in matched
            for p in products
        )
        for key, external, title, kind in LINKS.get(provider, []):
            if not games:
                continue
            linked = UpdateObject.model_validate(
                dict(
                    id=f"{provider}:{key}",
                    provider=provider,
                    external_id=external,
                    title=title,
                    kind=kind,
                    channel="eu" if provider == "battlenet" else "global",
                    related_games=[g.id for g in games],
                    news_url=games[0].news_url,
                )
            )
            if provider == "battlenet":
                linked.news_url = "https://news.blizzard.com/"
            for game in games:
                game.linked_objects.append(linked.id)
            objects.append(linked)
        objects.extend(games)
    if "steam" in enabled:
        unmapped["steam"] = sum(
            p.required_account == "Steam" and not steam_games([p]) for p in products
        )
    return objects, unmapped
