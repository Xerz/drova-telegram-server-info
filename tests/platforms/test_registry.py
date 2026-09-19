from drova_bot.domain.models import CatalogProduct
from drova_bot.drova.models import CatalogProductResponse
from drova_bot.steam_watcher.registry import catalog_objects


def product(pid: str, title: str, account: str) -> CatalogProduct:
    return CatalogProductResponse(productId=pid, title=title, requiredAccount=account).to_domain()


def test_exact_registry_mapping_and_shared_launcher() -> None:
    products = [
        product("cdb6d8f4-6b6f-4f92-a240-56447ed9b42d", "EFT", "Escape from Tarkov"),
        product("1b4253f2-11ae-4d14-92aa-b506a18cf247", "Arena", "Escape from Tarkov"),
        product("fake", "Genshin Impact", "hoYoverse"),
    ]
    objects, unmapped = catalog_objects(products, {"bsg", "hoyo"})
    assert len(objects) == 3
    launcher = next(o for o in objects if o.kind == "launcher")
    assert set(launcher.related_games) == {"bsg:eft", "bsg:arena"}
    assert all(o.coverage == "launcher_only" for o in objects if o.kind == "game")
    assert unmapped["hoyo"] == 1
    assert catalog_objects(products, {"steam"})[0] == []


def test_future_hi3_only_matches_official_global_channel() -> None:
    # Build using the same external response contract as the live catalog.
    def game(url: str) -> CatalogProduct:
        return CatalogProductResponse(
            productId="future-hi3",
            title="Different localized title",
            requiredAccount="hoYoverse",
            inShopUrl=url,
        ).to_domain()

    for url, expected in [
        ("https://honkaiimpact3.hoyoverse.com/global/", True),
        ("https://honkaiimpact3.hoyoverse.com/asia/", False),
        ("https://example.org/global/", False),
    ]:
        objects, _ = catalog_objects([game(url)], {"hoyo"})
        assert bool(objects) == expected
        if objects:
            assert objects[0].external_id == "5TIVvvcwtM"
