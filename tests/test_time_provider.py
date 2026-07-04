import pytest
from datetime import datetime, timedelta
from core.time_provider import RealTimeProvider, SimulatedTimeProvider

def test_real_time_provider_now():
    tp = RealTimeProvider()
    now = tp.utc_now()
    assert isinstance(now, datetime)

@pytest.mark.asyncio
async def test_simulated_time_provider_sleep():
    start = datetime(2023,1,1,12,0,0)
    tp = SimulatedTimeProvider(start)
    assert tp.utc_now() == start
    await tp.sleep(5)
    assert tp.utc_now() == start + timedelta(seconds=5)
