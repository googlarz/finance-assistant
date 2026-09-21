"""v4.1.0: reconciliation, recurring double-count guard, learned categories, session hygiene."""
import datetime


def _acc():
    from account_manager import add_account
    add_account({"id": "chk", "name": "Checking", "type": "checking", "currency": "EUR"})


def test_reconciliation_flags_unexplained_delta_and_passes_when_balanced():
    import reconciliation as rc, transaction_logger as tl
    _acc()
    rc.assert_balance("chk", 1000.00, "2026-01-01")
    tl.add_transaction("2026-01-05", "expense", -100.0, "food", "a", account_id="chk")
    tl.add_transaction("2026-01-10", "income", 500.0, "salary", "b", account_id="chk")
    rc.assert_balance("chk", 1400.00, "2026-01-31")
    assert rc.check_all() == []
    rc.assert_balance("chk", 1250.00, "2026-01-31")  # 150 short of what was booked
    d = rc.check_all()
    assert len(d) == 1 and d[0]["unexplained"] == -150.0
    assert "unexplained" in rc.format_alerts(d)[0]


def test_recurring_skips_occurrence_already_imported():
    import recurring_engine as re_, transaction_logger as tl
    _acc()
    tl.add_transaction("2026-03-01", "expense", -900.0, "housing", "MIETE MARCH",
                       account_id="chk", import_source="csv")
    re_.add_recurring("Rent", -900.0, "housing", frequency="monthly", account_id="chk",
                      start_date="2026-03-01", day_of_month=1)
    r = re_.generate_due_transactions(as_of="2026-03-02")
    assert r["generated_count"] == 0 and len(r["already_booked"]) == 1
    rows = tl.get_transactions(account_id="chk", year=2026)
    assert len(rows) == 1


def test_learned_category_is_applied_to_new_transactions():
    import category_learner as cl, transaction_logger as tl
    _acc()
    cl.learn_correction("ZORBA TAVERNA ATHENS", "Zorba Taverna", "other_expense", "dining")
    t = tl.add_transaction("2026-02-02", "expense", -30.0, None, "ZORBA TAVERNA ATHENS",
                           account_id="chk")["transaction_added"]
    assert t["category"] == "dining"


def test_session_hygiene_reports_reconciliation_gap():
    import reconciliation as rc, session_hygiene
    _acc()
    rc.assert_balance("chk", 100.0, "2026-01-01")
    rc.assert_balance("chk", 300.0, "2026-01-31")
    notes = session_hygiene.run()
    assert any(n.startswith("Reconciliation:") for n in notes)


def test_digest_delivered_at_session_start_off_macos(monkeypatch):
    import sys, session_hygiene, weekly_digest
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(weekly_digest, "run_digest", lambda profile, notify=True: "digest body")
    monkeypatch.setattr(weekly_digest, "days_since_last_digest", lambda: 9)
    assert any(n.startswith("Weekly digest:") for n in session_hygiene.run())
    monkeypatch.setattr(weekly_digest, "days_since_last_digest", lambda: 2)
    assert not any(n.startswith("Weekly digest:") for n in session_hygiene.run())
