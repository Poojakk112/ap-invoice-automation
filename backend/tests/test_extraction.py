from datetime import date
from decimal import Decimal

import pytest

from apflow.generator.documents import render
from apflow.pipeline.extraction import (ExtractionError, extract, normalise_invoice_number, parse_amount,
                                        parse_date)

VENDOR = {"vendor_name": "Apex Office Solutions LLC", "tax_id": "08-1234567"}


def _invoice(po="PO-2026-000010"):
    return {"vendor_invoice_number": "APE01-26-0042", "invoice_date": date(2026, 3, 4), "po_id": po,
            "currency": "USD", "subtotal_amount": Decimal("1255.00"), "tax_amount": Decimal("103.54"),
            "total_amount": Decimal("1358.54"),
            "lines": [{"sku": "SKU-OFF-0001", "description": "Premium Ballpoint Pens", "quantity": 10,
                       "unit_price": Decimal("125.50"), "tax_code": "TX8", "line_amount": Decimal("1255.00")}]}


@pytest.mark.parametrize("channel,layout", [("EMAIL", "A"), ("PORTAL", "B"), ("EDI", "C")])
def test_round_trip_every_layout(channel, layout):
    ext = extract(render(_invoice(), VENDOR, channel))
    assert ext.layout == layout
    assert ext.vendor_tax_id == "08-1234567"
    assert ext.vendor_invoice_number == "APE01-26-0042"
    assert ext.invoice_date == date(2026, 3, 4)       # DD/MM vs ISO vs DD-Mon all normalise
    assert ext.po_number == "PO-2026-000010"
    assert ext.stated_total == Decimal("1358.54")
    assert ext.lines[0].unit_price == Decimal("125.50") and ext.lines[0].quantity == 10


@pytest.mark.parametrize("channel", ["EMAIL", "PORTAL", "EDI"])
def test_non_po_invoice_has_no_po(channel):
    assert extract(render(_invoice(po=None), VENDOR, channel)).po_number is None


def test_dates_and_amounts():
    assert parse_date("04/03/2026") == date(2026, 3, 4)          # day first
    assert parse_date("04-Mar-2026") == date(2026, 3, 4)
    assert parse_amount("$12,345.60") == Decimal("12345.60")
    with pytest.raises(ExtractionError):
        parse_date("March 4th")
    with pytest.raises(ExtractionError):
        parse_amount("12.3.4")


def test_unknown_layout_and_missing_field_raise():
    with pytest.raises(ExtractionError):
        extract("RECEIPT\nfoo")
    broken = render(_invoice(), VENDOR, "EMAIL").replace("Invoice No:", "Ref:")
    with pytest.raises(ExtractionError):
        extract(broken)


def test_invoice_number_normalisation():
    assert normalise_invoice_number("ape01-26-0042") == normalise_invoice_number("APE01260042")
    assert normalise_invoice_number("APE/2026/00042") == "APE202600042"


@pytest.mark.parametrize("channel", ["EMAIL", "PORTAL", "EDI"])
def test_windows_line_endings_and_trailing_spaces_are_tolerated(channel):
    text = render(_invoice(), VENDOR, channel)
    messy = "\r\n".join(line + "   " for line in text.split("\n"))
    assert extract(messy).stated_total == Decimal("1358.54")


@pytest.mark.parametrize("channel", ["EMAIL", "PORTAL", "EDI"])
def test_unreadable_item_line_is_an_error_not_a_silent_drop(channel):
    text = render(_invoice(), VENDOR, channel).replace("1,255.00", "1,2S5.00").replace("1255.00", "12S5.00")
    with pytest.raises(ExtractionError):
        extract(text)
