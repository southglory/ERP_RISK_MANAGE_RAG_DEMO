"""KEC v3.0 전자세금계산서 XML 빌더."""

from __future__ import annotations

from datetime import date
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from .models import TaxInvoice, TaxInvoiceTypeCode, Party, TradeLineItem

_NS_RABIE = "urn:kr:or:kec:standard:Tax:ReusableAggregateBusinessInformationEntitySchemaModule:1:0"
_NS_DSBIE = "urn:kr:or:kec:standard:Tax:DocumentStandardBusinessInformationEntitySchemaModule:1:0"
_NS_DS    = "http://www.w3.org/2000/09/xmldsig#"


def generate_issue_id(brn: str, issue_date: date, seq: int = 1) -> str:
    """24자리 승인번호 생성: 작성일자(8) + 사업자번호(10) + 일련번호(6)."""
    date_part = issue_date.strftime("%Y%m%d")
    brn_part  = brn.replace("-", "")[:10].zfill(10)
    seq_part  = str(seq % 1000000).zfill(6)
    return date_part + brn_part + seq_part


class TaxInvoiceBuilder:
    """TaxInvoice 모델 → KEC v3.0 XML 문자열 변환기.

    Note: 실 운영에서는 XMLDSig 서명이 필요하지만
    이 플레이그라운드에서는 서명 엘리먼트를 placeholder로 포함한다.
    """

    def build(self, invoice: TaxInvoice, pretty: bool = True) -> str:
        """XML 문자열을 반환한다."""
        # 합계 재계산 (미리 안 했을 경우 대비)
        invoice.recalc_totals()

        # 승인번호 없으면 자동 생성
        if not invoice.issue_id:
            invoice.issue_id = generate_issue_id(
                invoice.invoicer.brn, invoice.issue_date
            )

        root = Element("TaxInvoice")
        root.set("xmlns",    _NS_RABIE)
        root.set("xmlns:ds", _NS_DS)

        self._add_exchanged_document(root, invoice)
        self._add_basic_info(root, invoice)
        self._add_party(root, "InvoicerParty", invoice.invoicer)
        self._add_party(root, "InvoiceeParty", invoice.invoicee)
        self._add_settlement(root, invoice)
        for line in invoice.lines:
            self._add_line_item(root, line, invoice.type_code)
        self._add_signature_placeholder(root)

        raw = tostring(root, encoding="unicode")
        if pretty:
            return minidom.parseString(raw).toprettyxml(indent="  ", encoding=None)
        return raw

    # ── 섹션별 빌더 ─────────────────────────────────────────────────────────────

    def _add_exchanged_document(self, root: Element, inv: TaxInvoice) -> None:
        doc = SubElement(root, "ExchangedDocument")
        _text(doc, "ID",              inv.issue_id)
        _text(doc, "TypeCode",        inv.type_code.value)
        _text(doc, "IssueDateTime",   inv.issue_datetime.strftime("%Y-%m-%dT%H:%M:%S"))
        _text(doc, "PurposeCode",     inv.purpose_code.value)
        if inv.is_amendment and inv.amendment_code:
            amend = SubElement(doc, "Amendment")
            _text(amend, "AmendmentCode",          inv.amendment_code.value)
            _text(amend, "ReferenceTaxInvoiceID",  inv.original_issue_id)
        if inv.note:
            _text(doc, "InformationText", inv.note)

    def _add_basic_info(self, root: Element, inv: TaxInvoice) -> None:
        basic = SubElement(root, "TaxInvoiceDocument")
        _text(basic, "IssueDate", inv.issue_date.strftime("%Y-%m-%d"))

    def _add_party(self, root: Element, tag: str, party: Party) -> None:
        el = SubElement(root, tag)
        _text(el, "BusinessRegistrationID", party.brn)
        _text(el, "Name",                   party.name)
        if party.representative:
            _text(el, "RepresentativeName", party.representative)
        if party.address:
            addr = SubElement(el, "AddressDetails")
            _text(addr, "Line", party.address)
        if party.business_type or party.business_item:
            bc = SubElement(el, "BusinessClassification")
            ind = SubElement(bc, "IndustryDetails")
            if party.business_type:
                _text(ind, "CategoryName", party.business_type)
            if party.business_item:
                _text(ind, "ItemName", party.business_item)
        if party.email:
            contact = SubElement(el, "Contact")
            _text(contact, "EmailURIID", party.email)

    def _add_settlement(self, root: Element, inv: TaxInvoice) -> None:
        settle = SubElement(root, "TaxInvoiceTradeSettlement")
        _text(settle, "TotalTaxableAmount", str(int(inv.total_supply)))
        _text(settle, "TotalTaxAmount",     str(int(inv.total_tax)))
        _text(settle, "GrandTotalAmount",   str(int(inv.grand_total)))
        if inv.cash_amount:
            _text(settle, "CashAmount",   str(int(inv.cash_amount)))
        if inv.credit_amount:
            _text(settle, "CreditAmount", str(int(inv.credit_amount)))

    def _add_line_item(
        self, root: Element, line: TradeLineItem, type_code: TaxInvoiceTypeCode
    ) -> None:
        item = SubElement(root, "TaxInvoiceTradeLineItem")
        _text(item, "SequenceNumeric",   str(line.seq))
        _text(item, "PurchaseExpiryDate", line.trade_date.strftime("%Y-%m-%d"))
        _text(item, "Name",              line.name)
        if line.spec:
            _text(item, "InformationText", line.spec)
        qty_el = SubElement(item, "InvoiceQuantity")
        qty_el.set("unitCode", "EA")
        qty_el.text = str(line.quantity)
        _text(item, "UnitPrice",        str(int(line.unit_price)))
        _text(item, "ChargeableAmount", str(int(line.supply_amount)))
        _text(item, "TaxAmount",        str(int(line.calc_tax(type_code))))
        if line.note:
            _text(item, "Description", line.note)

    def _add_signature_placeholder(self, root: Element) -> None:
        sig = SubElement(root, "ds:Signature")
        sig.set("Id", "TaxInvoiceSignature")
        SubElement(sig, "ds:SignedInfo")   # 실 운영 시 XMLDSig C14N 채움
        _text(sig, "ds:SignatureValue", "PLAYGROUND_NO_SIGNATURE")


def _text(parent: Element, tag: str, value: str) -> Element:
    el = SubElement(parent, tag)
    el.text = value
    return el
