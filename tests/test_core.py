from datetime import datetime, timezone, timedelta
from kalshi_quant.features import RollingBTCFeatures
from kalshi_quant.kalshi import Book
from kalshi_quant.risk import fractional_kelly

def test_book_prices():
    b = Book()
    b.apply_snapshot({"yes": [[60, 10], [61, 5]], "no": [[37, 9]]})
    assert b.yes_bid == .61
    assert b.yes_ask == .63

def test_features():
    r = RollingBTCFeatures()
    now = datetime.now(timezone.utc)
    for i in range(61):
        r.add(now-timedelta(seconds=60-i), 64000+i)
    f = r.snapshot(now, 64060, 64000, now+timedelta(seconds=60), .1)
    assert f.distance_usd == 60
    assert f.seconds_remaining == 60
    assert f.ret_60s > 0

def test_kelly_cap():
    r = fractional_kelly(1000, .80, .60, .25, .02)
    assert r.stake_dollars <= 20.01
