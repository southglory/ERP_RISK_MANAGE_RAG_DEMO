import pytest
from core.agents.vendor_repo import lookup_vendor, reset_cache


@pytest.mark.asyncio
async def test_lookup_returns_overseas_for_amazonkr():
    reset_cache()
    info = await lookup_vendor("V-AmazonKR")
    assert info is not None
    assert info["type"] == "overseas"
    assert info["country"] == "US"


@pytest.mark.asyncio
async def test_lookup_returns_unregistered_for_unknown():
    reset_cache()
    info = await lookup_vendor("V-Unknown")
    assert info is not None
    assert info["type"] == "unregistered"


@pytest.mark.asyncio
async def test_lookup_returns_none_for_missing_vendor():
    reset_cache()
    info = await lookup_vendor("V-DoesNotExist")
    assert info is None


@pytest.mark.asyncio
async def test_cache_hit_on_second_call():
    reset_cache()
    a = await lookup_vendor("V-Samsung")
    b = await lookup_vendor("V-Samsung")
    assert a is b
