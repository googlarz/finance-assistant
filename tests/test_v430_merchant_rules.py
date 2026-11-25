"""v4.3.0: merchant (payee) rules — safe matching, explicit add/remove, apply to history."""


def _acc():
    from account_manager import add_account
    add_account({"id": "chk", "name": "Checking", "type": "checking", "currency": "EUR"})


def test_short_payee_rule_does_not_match_everything():
    import category_learner as cl
    cl.learn_correction("x", "ab", "other_expense", "dining")
    assert cl.suggest_category("x", "Cabaret Bar") is None


def test_payee_match_respects_word_boundaries():
    import category_learner as cl
    cl.add_rule("rewe", "groceries")
    assert cl.suggest_category("x", "REWE Markt Berlin") == "groceries"
    assert cl.suggest_category("x", "Prewett Ltd") is None


def test_one_correction_does_not_create_generic_keyword_rules():
    import category_learner as cl
    cl.learn_correction("CARD PAYMENT ZORBA TAVERNA", "Zorba Taverna", "other_expense", "dining")
    assert cl.suggest_category("CARD PAYMENT SHELL STATION") is None
    assert cl.suggest_category("anything", "Zorba Taverna") == "dining"


def test_add_and_remove_rule():
    import category_learner as cl
    cl.add_rule("netflix", "subscriptions")
    assert cl.suggest_category("NETFLIX.COM 123") == "subscriptions"
    assert cl.remove_rule("netflix") is True
    assert cl.suggest_category("NETFLIX.COM 123") is None
    assert cl.remove_rule("netflix") is False


def test_apply_rules_dry_run_then_commit():
    import category_learner as cl, transaction_logger as tl
    _acc()
    t = tl.add_transaction("2026-02-02", "expense", -30.0, "other_expense", "ZORBA TAVERNA",
                           account_id="chk")["transaction_added"]
    cl.add_rule("zorba", "dining")
    preview = cl.apply_rules(dry_run=True)
    assert preview["would_change"] == 1
    assert tl.get_transactions(account_id="chk", year=2026)[0]["category"] == "other_expense"
    done = cl.apply_rules(dry_run=False)
    assert done["changed"] == 1
    assert tl.get_transactions(account_id="chk", year=2026)[0]["category"] == "dining"


def test_recategorize_updates_and_learns_payee():
    import category_learner as cl, transaction_logger as tl
    _acc()
    t = tl.add_transaction("2026-02-02", "expense", -30.0, "other_expense", "KARTE 4711",
                           account_id="chk", payee="Zorba Taverna")["transaction_added"]
    r = cl.recategorize_transaction(t["id"], "dining")
    assert r["updated"] is True and r["learned_payee"] == "zorba taverna"
    assert tl.get_transactions(account_id="chk", year=2026)[0]["category"] == "dining"
    assert cl.suggest_category("x", "Zorba Taverna") == "dining"


def test_recategorize_unknown_id():
    import category_learner as cl
    assert cl.recategorize_transaction("nope", "dining")["updated"] is False
