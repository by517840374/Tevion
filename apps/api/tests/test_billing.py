from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tevion_api import models
from tevion_api.services import (
    InsufficientCreditsError,
    adjust_credit_balance,
    credit_balance_for_user,
    release_generation_credits,
    reserve_generation_credits,
    settle_generation_credits,
)


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    models.CreditAccount.__table__.create(engine)
    models.CreditLedgerEntry.__table__.create(engine)
    models.CreditReservation.__table__.create(engine)
    session = Session(engine)
    session.info["engine"] = engine
    return session


def test_credit_reservation_settlement_is_idempotent() -> None:
    db = _db()
    adjust_credit_balance(db, user_id="user-1", points=100, reason="测试充值")
    reservation = reserve_generation_credits(db, user_id="user-1", run_id="run-1", points=20)
    assert reservation.status == "reserved"
    assert credit_balance_for_user(db, user_id="user-1") == 80
    assert reserve_generation_credits(db, user_id="user-1", run_id="run-1", points=20).id == reservation.id
    settle_generation_credits(db, run_id="run-1")
    settle_generation_credits(db, run_id="run-1")
    assert db.scalar(select(models.CreditReservation).where(models.CreditReservation.id == reservation.id)).status == "settled"
    assert credit_balance_for_user(db, user_id="user-1") == 80


def test_failed_generation_releases_reserved_points_once() -> None:
    db = _db()
    adjust_credit_balance(db, user_id="user-2", points=10, reason="测试充值")
    reserve_generation_credits(db, user_id="user-2", run_id="run-2", points=10)
    release_generation_credits(db, run_id="run-2", reason="Provider 失败")
    release_generation_credits(db, run_id="run-2", reason="重复释放")
    assert credit_balance_for_user(db, user_id="user-2") == 10


def test_reservation_rejects_insufficient_balance() -> None:
    db = _db()
    adjust_credit_balance(db, user_id="user-3", points=9, reason="测试充值")
    try:
        reserve_generation_credits(db, user_id="user-3", run_id="run-3", points=10)
    except InsufficientCreditsError as exc:
        assert "需要 10 点" in str(exc)
    else:
        raise AssertionError("expected insufficient credits")
