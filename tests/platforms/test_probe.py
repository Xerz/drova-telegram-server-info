import os

import pytest

from scripts.probe_updates import probe


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("UPDATES_LIVE") != "1", reason="Public metadata live checks require opt-in"
)
async def test_live_public_metadata() -> None:
    result = await probe({"hoyo", "wuwa", "endfield", "battlenet", "bsg"})
    for value in result.values():
        assert value["total"] > 0 and value["covered"] == value["total"]
        assert all(duration < 300 for duration in value["cycle_seconds"])


def test_probe_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.probe_updates import main

    monkeypatch.setattr("sys.argv", ["probe_updates.py"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("EPIC_LIVE") != "1", reason="Epic metadata requires opt-in credentials"
)
async def test_live_epic_metadata() -> None:
    result = (await probe({"epic"}))["epic"]
    assert result["total"] == result["covered"] == 1
    assert all(d < 300 for d in result["cycle_seconds"])
