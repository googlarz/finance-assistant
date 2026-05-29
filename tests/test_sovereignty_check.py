"""Tests for sovereignty_check harness (no Ollama required)."""
import sovereignty_check as sc


def test_extract_number_handles_currency():
    assert sc._extract_number("€13,924.20") == 13924.20
    assert sc._extract_number("about $13,100") == 13100.0
    assert sc._extract_number("13924.2") == 13924.2


def test_extract_number_none_when_no_number():
    assert sc._extract_number("no idea, ask an accountant") is None


def test_ground_truth_cases_compute(isolated_finance_dir):
    cases = sc._ground_truth_cases()
    assert len(cases) >= 1
    # DE 2025 60k case should have a positive ground-truth tax
    de = cases[0]
    assert de["truth"] > 0
    assert "question" in de


def test_recommended_models_listed():
    assert "llama3.3:70b" in sc.RECOMMENDED_MODELS
    assert len(sc.RECOMMENDED_MODELS) >= 3
