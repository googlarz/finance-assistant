"""v4.2.4 importer hardening: encodings/BOM, debit/credit columns, new bank
formats, per-file date order, per-row currency, and near-duplicate detection."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from csv_importer import (  # noqa: E402
    KNOWN_FORMATS, detect_bank_format, infer_date_format, parse_csv, count_data_rows,
)
from import_support import descriptions_match, drop_near_duplicates  # noqa: E402


def _write(tmp_path, name, content, encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(content.encode(encoding) if isinstance(content, str) else content)
    return str(p)


# ── 1. Encodings ─────────────────────────────────────────────────────────────

N26 = (
    '"Date","Payee","Account number","Transaction type","Payment reference","Amount (EUR)"\n'
    '"2024-04-03","Café Müller","DE00","Debit Card","Latte","-3.50"\n'
    '"2024-04-04","Employer","DE00","Income","Salary","2500.00"\n'
)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-le", "cp1252", "latin-1"])
def test_n26_any_encoding(tmp_path, encoding):
    path = _write(tmp_path, "n26.csv", N26, encoding)
    assert detect_bank_format(path) == "n26"
    rows = parse_csv(path)
    assert [r["amount"] for r in rows] == [-3.5, 2500.0]
    assert rows[0]["payee"] == "Café Müller"
    assert count_data_rows(path) == 2


def test_utf16_tab_export_generic(tmp_path):
    text = "Datum\tBetrag\tVerwendungszweck\n03.04.2024\t-12,50\tKaffee\n"
    rows = parse_csv(_write(tmp_path, "x.csv", text, "utf-16"))
    assert rows and rows[0]["amount"] == -12.5 and rows[0]["date"] == "2024-04-03"


def test_cp1250_polish_text_decodes(tmp_path):
    content = (
        "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji;\n"
        "2024-04-03;Zakupy żółć;mKonto;Jedzenie;-12,50;100,00;\n"
    )
    rows = parse_csv(_write(tmp_path, "mbank.csv", content, "cp1250"))
    assert rows[0]["description"] == "Zakupy żółć"
    assert rows[0]["amount"] == -12.5


# ── 2. Debit / credit columns ────────────────────────────────────────────────

def test_paid_out_paid_in_signs_unknown_bank_generic(tmp_path):
    content = (
        "Date,Description,Paid out,Paid in\n"
        "13/04/2024,Tesco,12.50,\n"
        "14/04/2024,Salary,,1000.00\n"
    )
    # Not a declared bank: header lacks "Balance", so this exercises the generic path.
    assert detect_bank_format(_write(tmp_path, "g.csv", content)) is None
    rows = parse_csv(str(tmp_path / "g.csv"), currency="GBP")
    assert [r["amount"] for r in rows] == [-12.5, 1000.0]


@pytest.mark.parametrize("debit,credit", [("Wypłata", "Wpłata"), ("Soll", "Haben")])
def test_generic_debit_credit_synonyms(tmp_path, debit, credit):
    content = f"Datum,Text,{debit},{credit}\n03.04.2024,A,10.00,\n04.04.2024,B,,20.00\n"
    rows = parse_csv(_write(tmp_path, "g.csv", content))
    assert [r["amount"] for r in rows] == [-10.0, 20.0]


def test_negative_debit_column_still_an_outflow(tmp_path):
    content = (
        "Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,"
        "Debit Amount,Credit Amount,Balance\n"
        "13/04/2024,DEB,'11-22-33,12345678,SHOP,-5.00,,95.00\n"
    )
    rows = parse_csv(_write(tmp_path, "l.csv", content))
    assert rows[0]["amount"] == -5.0


# ── 3. New formats ───────────────────────────────────────────────────────────

FORMAT_CASES = [
    ("monzo",
     "Transaction ID,Date,Time,Type,Name,Emoji,Category,Amount,Currency,Local amount,Local currency,"
     "Notes and #tags,Address,Receipt,Description,Category split,Money Out,Money In\n"
     "tx_1,13/04/2024,10:00:00,Card payment,Pret,,Eating out,-4.50,GBP,-4.50,GBP,,,,PRET A MANGER,,,\n",
     "utf-8", -4.5, "2024-04-13", "GBP"),
    ("starling",
     "Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category,Notes\n"
     "13/04/2024,Tesco,Food,CARD,-12.00,100.00,GROCERIES,\n",
     "utf-8", -12.0, "2024-04-13", "GBP"),
    ("barclays",
     "Number,Date,Account,Amount,Subcategory,Memo\n"
     "1,13/04/2024,20-00-00 12345678,-9.99,PAYMENT,SPOTIFY\n",
     "cp1252", -9.99, "2024-04-13", "GBP"),
    ("hsbc_uk",
     "Date,Description,Paid out,Paid in,Balance\n"
     "13/04/2024,SHOP,7.00,,50.00\n",
     "cp1252", -7.0, "2024-04-13", "GBP"),
    ("lloyds",
     "Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,"
     "Debit Amount,Credit Amount,Balance\n"
     "13/04/2024,FPO,'11-22-33,12345678,RENT,500.00,,100.00\n",
     "cp1252", -500.0, "2024-04-13", "GBP"),
    ("santander_uk",
     "Date,Description,Money in,Money out,Balance\n"
     "13/04/2024,Wages,1500.00,,2000.00\n",
     "cp1252", 1500.0, "2024-04-13", "GBP"),
    ("nationwide",
     "Account Name:,Flex\n\n"
     "Date,Transaction type,Description,Paid out,Paid in,Balance\n"
     "04 Jan 2024,Card,\xa3 Shop,\xa33.20,,\xa3100.00\n",
     "cp1252", -3.2, "2024-01-04", "GBP"),
    ("aib",
     "Posted Account, Posted Transactions Date, Description1, Description2, Description3, Debit Amount, "
     "Credit Amount, Balance, Posted Currency, Transaction Type, Local Currency Amount, Local Currency\n"
     "123,13/04/2024,TESCO,,,10.00,,90.00,EUR,POS,10.00,EUR\n",
     "cp1252", -10.0, "2024-04-13", "EUR"),
    ("bank_of_ireland",
     "Date,Details,Debit,Credit,Balance\n"
     "13/04/2024,SUPERVALU,20.00,,80.00\n",
     "cp1252", -20.0, "2024-04-13", "EUR"),
    ("pko_bp",
     '"Data operacji","Data waluty","Typ transakcji","Kwota","Waluta","Saldo po transakcji","Opis transakcji"\n'
     '"2024-04-03","2024-04-03","Płatność kartą","-12,50","PLN","100,00","BIEDRONKA"\n',
     "cp1250", -12.5, "2024-04-03", "PLN"),
    ("mbank",
     "#Data operacji;#Opis operacji;#Rachunek;#Kategoria;#Kwota;#Saldo po operacji;\n"
     "2024-04-03;ŻABKA;mKonto;Jedzenie;-1 234,56;100,00;\n",
     "cp1250", -1234.56, "2024-04-03", "PLN"),
    ("ing_pl",
     "Data transakcji;Data księgowania;Dane kontrahenta;Tytuł;Nr rachunku;Nazwa banku;Szczegóły;"
     "Nr transakcji;Kwota transakcji (waluta rachunku);Waluta rachunku\n"
     "2024-04-03;2024-04-03;SKLEP;Zakupy;PL00;Bank;;1;-45,00;PLN\n",
     "cp1250", -45.0, "2024-04-03", "PLN"),
    ("santander_pl",
     "Data operacji,Opis operacji,Nadawca/Odbiorca,Kwota,Saldo po operacji\n"
     "03-04-2024,Przelew,Jan,\"-100,00\",\"900,00\"\n",
     "cp1250", -100.0, "2024-04-03", "PLN"),
    ("ing_nl",
     '"Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code","Af Bij","Bedrag (EUR)",'
     '"Mutatiesoort","Mededelingen"\n'
     '"20240403","Albert Heijn","NL00","","BA","Af","12,50","Betaalautomaat","Pasvolgnr"\n'
     '"20240404","Werkgever","NL00","","OV","Bij","1.500,00","Overschrijving","Salaris"\n',
     "utf-8", -12.5, "2024-04-03", "EUR"),
    ("rabobank",
     '"IBAN/BBAN","Munt","BIC","Volgnr","Datum","Rentedatum","Bedrag","Saldo na trn",'
     '"Tegenrekening IBAN/BBAN","Naam tegenpartij","Naam uiteindelijke partij","Naam initiërende partij",'
     '"BIC tegenpartij","Code","Batch ID","Transactiereferentie","Machtigingskenmerk","Incassant ID",'
     '"Betalingskenmerk","Omschrijving-1"\n'
     '"NL00","EUR","X","1","2024-04-03","2024-04-03","-12,50","100,00","","Jumbo","","","","","","","","","","Boodschappen"\n',
     "utf-8", -12.5, "2024-04-03", "EUR"),
    ("bunq",
     "Date,Interest Date,Amount,Account,Counterparty,Name,Description\n"
     "2024-04-03,2024-04-03,-12.50,NL00,NL11,Jumbo,Groceries\n",
     "utf-8", -12.5, "2024-04-03", "EUR"),
    ("bunq",
     "Date;Interest Date;Amount;Account;Counterparty;Name;Description\n"
     "2024-04-03;2024-04-03;-12,50;NL00;NL11;Jumbo;Groceries\n",
     "utf-8", -12.5, "2024-04-03", "EUR"),
    ("bnp_paribas",
     "Date operation;Libelle;Montant\n"
     "03/04/2024;CARTE FNAC;-45,90\n",
     "cp1252", -45.9, "2024-04-03", "EUR"),
    ("boursorama",
     "dateOp;dateVal;label;category;categoryParent;supplierFound;amount;comment;accountNum;accountLabel;accountbalance\n"
     '2024-04-03;2024-04-03;CARTE FNAC;Loisirs;Loisirs;fnac;"-45,90";;0001;Compte;100\n',
     "utf-8", -45.9, "2024-04-03", "EUR"),
    ("credit_agricole",
     "Date;Libellé;Débit euros;Crédit euros;\n"
     "03/04/2024;PAIEMENT CB;45,90;;\n",
     "cp1252", -45.9, "2024-04-03", "EUR"),
    ("dkb_2023",
     '"Konto";"Girokonto DE00"\n\n'
     '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";'
     '"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n'
     '"03.04.24";"03.04.24";"Gebucht";"Ich";"REWE";"Einkauf";"Ausgang";"DE11";"-12,50";"";"";""\n',
     "utf-8", -12.5, "2024-04-03", "EUR"),
    ("sparkasse_camt",
     '"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";"Glaeubiger ID";'
     '"Mandatsreferenz";"Kundenreferenz (End-to-End)";"Sammlerreferenz";"Lastschrift Ursprungsbetrag";'
     '"Auslagenersatz Ruecklastschrift";"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";'
     '"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"\n'
     '"DE00";"03.04.24";"03.04.24";"KARTENZAHLUNG";"Edeka";"";"";"";"";"";"";"EDEKA";"DE22";"X";"-23,40";"EUR";"Umsatz"\n',
     "cp1252", -23.4, "2024-04-03", "EUR"),
]


@pytest.mark.parametrize("name,content,enc,amount,date,cur", FORMAT_CASES,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(FORMAT_CASES)])
def test_new_format_detected_and_parsed(tmp_path, name, content, enc, amount, date, cur):
    path = _write(tmp_path, "f.csv", content, enc)
    assert detect_bank_format(path) == name
    rows = parse_csv(path)
    assert len(rows) >= 1
    assert rows[0]["amount"] == amount
    assert rows[0]["date"] == date
    assert rows[0]["currency"] == cur


def test_ing_nl_credit_row_is_positive(tmp_path):
    path = _write(tmp_path, "f.csv", FORMAT_CASES[13][1])
    assert [r["amount"] for r in parse_csv(path)] == [-12.5, 1500.0]


def test_ing_nl_semicolon_variant(tmp_path):
    content = FORMAT_CASES[13][1].replace('","', '";"')
    path = _write(tmp_path, "f.csv", content)
    assert detect_bank_format(path) == "ing_nl"
    assert [r["amount"] for r in parse_csv(path)] == [-12.5, 1500.0]


def test_polish_description_not_mojibake(tmp_path):
    case = next(c for c in FORMAT_CASES if c[0] == "ing_pl")
    rows = parse_csv(_write(tmp_path, "f.csv", case[1], "cp1250"))
    assert rows[0]["description"] == "Zakupy"
    assert rows[0]["payee"] == "SKLEP"


def test_dkb_2023_payee_follows_direction(tmp_path):
    case = next(c for c in FORMAT_CASES if c[0] == "dkb_2023")
    content = case[1] + (
        '"04.04.24";"04.04.24";"Gebucht";"ARBEITGEBER";"Ich";"Lohn";"Eingang";"DE33";"2.000,00";"";"";""\n'
    )
    rows = parse_csv(_write(tmp_path, "f.csv", content))
    assert [(r["payee"], r["amount"]) for r in rows] == [("REWE", -12.5), ("ARBEITGEBER", 2000.0)]


def test_abn_amro_headerless_tab_export(tmp_path):
    content = "123456789\tEUR\t20240403\t1000,00\t987,50\t-12,50\tBEA NR:1 Albert Heijn\n"
    path = _write(tmp_path, "abn.tab", content)
    assert detect_bank_format(path) == "abn_amro"
    rows = parse_csv(path)
    assert rows[0]["amount"] == -12.5 and rows[0]["date"] == "2024-04-03"


def test_existing_formats_still_win_their_headers(tmp_path):
    """Detection of the pre-existing formats is unchanged by the new ones."""
    cases = {
        "dkb": "Buchungsdatum;Wertstellung;Status;Auftraggeber / Begünstigter;Verwendungszweck;Betrag (EUR)\n",
        "ing": "Buchung;Valuta;Auftraggeber/Empfänger;Buchungstext;Verwendungszweck;Betrag;Währung\n",
        "sparkasse": "Auftragskonto;Buchungstag;Wertstellung;Beguenstigter/Zahlungspflichtiger;Verwendungszweck;Betrag\n",
        "commerzbank": "Buchungstag;Wertstellung;Umsatzart;Buchungstext;Auftraggeber / Begünstigter;Betrag\n",
        "n26": "Date,Payee,Account number,Transaction type,Payment reference,Amount (EUR)\n",
        "wise": "TransferWise ID,Date,Amount,Currency,Description\n",
        "revolut": "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n",
        "capital_one": "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n",
    }
    for expected, header in cases.items():
        assert detect_bank_format(_write(tmp_path, f"{expected}.csv", header, "utf-8")) == expected, expected


def test_every_new_format_has_consistent_columns():
    for name, fmt in KNOWN_FORMATS.items():
        if fmt.get("positional"):
            continue
        assert fmt["detect"], name
        assert fmt["date"] and (fmt.get("amount") or fmt.get("amount_debit")), name


# ── 4. Ambiguous dates ───────────────────────────────────────────────────────

def test_infer_date_format_day_first_proof():
    assert infer_date_format(["03/04/2024", "13/04/2024"], "%m/%d/%Y") == "%d/%m/%Y"


def test_infer_date_format_month_first_proof():
    assert infer_date_format(["03/04/2024", "04/13/2024"], "%d/%m/%Y") == "%m/%d/%Y"


def test_infer_date_format_no_proof_keeps_locale():
    assert infer_date_format(["03/04/2024", "05/06/2024"], "%d/%m/%Y") == "%d/%m/%Y"
    assert infer_date_format(["03/04/2024", "05/06/2024"], "%m/%d/%Y") == "%m/%d/%Y"


def test_infer_date_format_contradiction_keeps_locale():
    assert infer_date_format(["13/04/2024", "04/13/2024"], "%d/%m/%Y") == "%d/%m/%Y"


def test_infer_date_format_ignores_unambiguous_formats():
    assert infer_date_format(["03.04.2024"], "%d.%m.%Y") == "%d.%m.%Y"
    assert infer_date_format(["2024-04-03"], "%Y-%m-%d") == "%Y-%m-%d"


def test_whole_file_uses_one_order_us_file_in_uk_format(tmp_path):
    """A UK-format bank file that is really mm/dd: a single 04/13 row decides
    ALL rows, including the ambiguous 03/04."""
    content = (
        "Date,Description,Paid out,Paid in,Balance\n"
        "03/04/2024,A,1.00,,10.00\n"
        "04/13/2024,B,2.00,,8.00\n"
    )
    rows = parse_csv(_write(tmp_path, "us.csv", content))
    assert [r["date"] for r in rows] == ["2024-03-04", "2024-04-13"]


def test_ambiguous_dates_default_to_locale(tmp_path):
    content = "Date,Description,Paid out,Paid in,Balance\n03/04/2024,A,1.00,,10.00\n05/06/2024,B,2.00,,8.00\n"
    rows = parse_csv(_write(tmp_path, "uk.csv", content))
    assert [r["date"] for r in rows] == ["2024-04-03", "2024-06-05"]  # dd/mm (UK)


def test_wells_fargo_style_slash_dates_stay_us(tmp_path):
    path = _write(tmp_path, "wf.csv", '"03/04/2024","-10.00","*","","COFFEE"\n')
    assert detect_bank_format(path) == "wells_fargo"
    assert parse_csv(path)[0]["date"] == "2024-03-04"


def test_generic_slash_dates_one_order_per_file(tmp_path):
    content = "Date,Amount,Description\n03/04/2024,-1.00,A\n25/04/2024,-2.00,B\n"
    rows = parse_csv(_write(tmp_path, "g.csv", content))
    assert [r["date"] for r in rows] == ["2024-04-03", "2024-04-25"]


# ── 5. Per-row currency ──────────────────────────────────────────────────────

def test_revolut_currency_per_row(tmp_path):
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "CARD_PAYMENT,Current,2024-04-03 10:00:00,2024-04-03 10:00:00,Shop,-10.00,0.00,PLN,COMPLETED,90.00\n"
        "CARD_PAYMENT,Current,2024-04-04 10:00:00,2024-04-04 10:00:00,Cafe,-3.00,0.00,GBP,COMPLETED,87.00\n"
    )
    rows = parse_csv(_write(tmp_path, "r.csv", content), currency="EUR")
    assert [r["currency"] for r in rows] == ["PLN", "GBP"]


def test_wise_currency_per_row_falls_back_when_blank(tmp_path):
    content = (
        "TransferWise ID,Date,Amount,Currency,Description,Merchant\n"
        "T1,03-04-2024,-10.00,USD,Shop,Shop\n"
        "T2,04-04-2024,-5.00,,Cafe,Cafe\n"
    )
    rows = parse_csv(_write(tmp_path, "w.csv", content), currency="EUR")
    assert [r["currency"] for r in rows] == ["USD", "EUR"]


def test_router_reports_mixed_currencies(tmp_path):
    from import_router import import_file
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "CARD_PAYMENT,Current,2024-04-03 10:00:00,2024-04-03 10:00:00,Shop,-10.00,0.00,PLN,COMPLETED,90.00\n"
        "CARD_PAYMENT,Current,2024-04-04 10:00:00,2024-04-04 10:00:00,Cafe,-3.00,0.00,GBP,COMPLETED,87.00\n"
    )
    result = import_file(_write(tmp_path, "r.csv", content), account_id="a", dry_run=True, keep_original=False)
    assert result["currencies"] == ["GBP", "PLN"]
    assert {t["currency"] for t in result["preview"]} == {"GBP", "PLN"}


def test_uk_format_defaults_to_gbp_but_explicit_currency_wins(tmp_path):
    case = next(c for c in FORMAT_CASES if c[0] == "hsbc_uk")
    path = _write(tmp_path, "h.csv", case[1])
    assert parse_csv(path)[0]["currency"] == "GBP"
    assert parse_csv(path, currency="USD")[0]["currency"] == "USD"


# ── 6. Near-duplicate detection ──────────────────────────────────────────────

def test_descriptions_match_variants():
    assert descriptions_match("REWE SAGT DANKE 1234 KARTE 5", "Rewe sagt danke")
    assert descriptions_match("Netflix.com", "NETFLIX COM 03.04.")
    assert not descriptions_match("Netflix", "Spotify")
    assert not descriptions_match("Netflix", "")


def test_drop_near_duplicates_one_to_one():
    existing = [{"date": "2024-04-03", "amount": -3.5, "description": "Starbucks Berlin 1234", "payee": ""}]
    rows = [
        {"date": "2024-04-03", "amount": -3.5, "description": "STARBUCKS BERLIN", "payee": ""},
        {"date": "2024-04-03", "amount": -3.5, "description": "STARBUCKS BERLIN", "payee": ""},  # second coffee
        {"date": "2024-04-03", "amount": -3.5, "description": "Kiosk", "payee": ""},
        {"date": "2024-04-04", "amount": -3.5, "description": "STARBUCKS BERLIN", "payee": ""},
    ]
    kept = drop_near_duplicates(rows, existing)
    assert len(kept) == 3  # only one new row absorbed by the one stored row


def test_reimport_with_reworded_description_is_deduplicated(tmp_path):
    from import_router import import_file
    first = (
        "Date,Payee,Account number,Transaction type,Payment reference,Amount (EUR)\n"
        "2024-04-03,Rewe,DE00,Debit Card,Einkauf 1234,-12.50\n"
        "2024-04-04,Netflix,DE00,Debit Card,Abo,-9.99\n"
    )
    second = first.replace("Einkauf 1234", "Einkauf 5678")
    p1 = _write(tmp_path, "a.csv", first)
    r1 = import_file(p1, account_id="acc", dry_run=False, keep_original=False)
    assert r1["imported"] == 2
    r2 = import_file(_write(tmp_path, "b.csv", second), account_id="acc", dry_run=True, keep_original=False)
    assert r2["duplicates_removed"] == 2 and r2["to_import"] == 0


def test_same_amount_different_merchant_is_not_a_duplicate(tmp_path):
    from import_router import import_file
    first = (
        "Date,Payee,Account number,Transaction type,Payment reference,Amount (EUR)\n"
        "2024-04-03,Rewe,DE00,Debit Card,Einkauf,-12.50\n"
    )
    second = first.replace("Rewe", "Lidl").replace("Einkauf", "Lebensmittel")
    import_file(_write(tmp_path, "a.csv", first), account_id="acc", dry_run=False, keep_original=False)
    r2 = import_file(_write(tmp_path, "b.csv", second), account_id="acc", dry_run=True, keep_original=False)
    assert r2["to_import"] == 1


# ── OFX encoding ─────────────────────────────────────────────────────────────

def test_ofx_with_bom_and_cp1252(tmp_path):
    from ofx_importer import parse_ofx
    ofx = (
        "OFXHEADER:100\nCHARSET:1252\n<OFX><CURDEF>EUR<BANKTRANLIST>"
        "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20240403<TRNAMT>-4.20<FITID>1<NAME>Bäckerei</STMTTRN>"
        "</BANKTRANLIST></OFX>"
    )
    for raw in (b"\xef\xbb\xbf" + ofx.encode("utf-8"), ofx.encode("cp1252")):
        rows = parse_ofx(_write(tmp_path, "s.ofx", raw))
        assert rows[0]["payee"] == "Bäckerei" and rows[0]["amount"] == -4.2
