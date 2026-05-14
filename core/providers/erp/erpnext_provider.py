from __future__ import annotations
import os
import httpx
from core.providers.base import ERPProvider


class ERPNextProvider(ERPProvider):
    """Frappe/ERPNext v15 REST API adapter.

    Accessed ONLY via REST — GPL boundary maintained.
    Swap target: any ERP REST API (SAP OData, custom ERP).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("ERPNEXT_URL", "http://localhost:8080")).rstrip("/")
        key = api_key or os.environ.get("ERPNEXT_API_KEY", "")
        secret = api_secret or os.environ.get("ERPNEXT_API_SECRET", "")
        self._headers = {"Authorization": f"token {key}:{secret}"} if key else {}

    async def _get(self, doctype: str, filters: dict, fields: list[str]) -> list[dict]:
        import json
        params = {
            "doctype": doctype,
            "fields": json.dumps(fields),
            "filters": json.dumps([[k, ">=", v] if k.endswith("_from") else [k, "<=", v]
                                   if k.endswith("_to") else [k, "=", v]
                                   for k, v in filters.items()]),
            "limit_page_length": 500,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/resource/{doctype}",
                params=params,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def get_journal_entries(self, from_date: str, to_date: str) -> list[dict]:
        return await self._get(
            "Journal Entry",
            {"posting_date": from_date, "to_date": to_date},
            ["name", "posting_date", "total_debit", "total_credit", "voucher_type", "accounts"],
        )

    async def get_sales_invoices(self, from_date: str, to_date: str) -> list[dict]:
        return await self._get(
            "Sales Invoice",
            {"posting_date": from_date, "to_date": to_date},
            ["name", "posting_date", "customer", "grand_total", "outstanding_amount",
             "is_return", "items", "taxes"],
        )

    async def get_purchase_invoices(self, from_date: str, to_date: str) -> list[dict]:
        return await self._get(
            "Purchase Invoice",
            {"posting_date": from_date, "to_date": to_date},
            ["name", "posting_date", "supplier", "grand_total", "outstanding_amount",
             "is_return", "items", "taxes"],
        )

    async def get_gl_entries(self, account: str, from_date: str, to_date: str) -> list[dict]:
        return await self._get(
            "GL Entry",
            {"account": account, "posting_date": from_date, "to_date": to_date},
            ["name", "posting_date", "account", "debit", "credit", "voucher_type",
             "voucher_no", "party_type", "party", "cost_center"],
        )
