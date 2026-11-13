from datetime import datetime, timezone
from portfolio.paper_futures import LONG, PaperPortfolio

def test_daily_loss_limit_resets_on_next_utc_day():
    pf=PaperPortfolio(1_000.0,daily_loss_limit_pct=0.05,max_utilisation=1.0)
    day1=int(datetime(2023,11,14,23,59,30,tzinfo=timezone.utc).timestamp()*1000)
    day2=int(datetime(2023,11,15,0,0,15,tzinfo=timezone.utc).timestamp()*1000)
    assert pf.open_position('b','X',LONG,100.,200.,leverage=5.,step_size=.001,now_ms=day1).ok
    pf.close_position('b','X',90.,now_ms=day1+1)
    assert pf.daily_loss_limit_hit()
    assert pf.open_position('b','Y',LONG,100.,100.,leverage=5.,step_size=.001,now_ms=day2).ok

def test_open_position_rolls_daily_risk_with_live_position():
    pf=PaperPortfolio(1000.,daily_loss_limit_pct=.05,max_utilisation=1.)
    before=int(datetime(2023,11,14,23,59,30,tzinfo=timezone.utc).timestamp()*1000)
    after=int(datetime(2023,11,15,0,0,10,tzinfo=timezone.utc).timestamp()*1000)
    assert pf.open_position('b','X',LONG,100.,200.,leverage=5.,step_size=.001,now_ms=before).ok
    pf.mark_price('b','X',90.,before+20000)
    assert pf.daily_loss_limit_hit()
    pf.mark_price('b','X',90.,after)
    assert not pf.daily_period_unknown
    assert not pf.daily_loss_limit_hit()
    pf.mark_price('b','X',80.,after+10000)
    assert pf.daily_loss_limit_hit()

def test_missed_midnight_equity_blocks_new_positions():
    pf=PaperPortfolio(1000.,daily_loss_limit_pct=.05,max_utilisation=1.)
    before=int(datetime(2023,11,14,12,0,tzinfo=timezone.utc).timestamp()*1000)
    after=int(datetime(2023,11,15,12,0,tzinfo=timezone.utc).timestamp()*1000)
    pf.roll_daily_period(before)
    assert pf.roll_daily_period(after)
    assert pf.daily_period_unknown
    result=pf.open_position('b','X',LONG,100.,100.,leverage=5.,step_size=.001,now_ms=after)
    assert not result.ok and 'özsermayesi bilinmiyor' in result.reason

def test_stale_open_position_makes_midnight_equity_unknown():
    pf=PaperPortfolio(1000.,daily_loss_limit_pct=.05,max_utilisation=1.)
    opened=int(datetime(2023,11,14,23,57,30,tzinfo=timezone.utc).timestamp()*1000)
    before=int(datetime(2023,11,14,23,59,50,tzinfo=timezone.utc).timestamp()*1000)
    after=int(datetime(2023,11,15,0,0,10,tzinfo=timezone.utc).timestamp()*1000)
    assert pf.open_position('b','X',LONG,100.,200.,leverage=5.,step_size=.001,now_ms=opened).ok
    pf.roll_daily_period(before)
    assert pf.roll_daily_period(after) and pf.daily_period_unknown
    result=pf.open_position('b','Y',LONG,100.,100.,leverage=5.,step_size=.001,now_ms=after)
    assert not result.ok and 'özsermayesi bilinmiyor' in result.reason
