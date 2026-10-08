"""Minimal Meta Marketing API (Graph API) client over plain HTTPS, covering
just the Custom Audience calls this sync needs. No facebook-business SDK.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
from typing import Any, Iterator, Sequence

import requests

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"

# Graph error codes worth retrying: rate limits / throttling / temporary issues.
# 80003 is the Custom Audience-specific business use case rate limit.
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613, 80003}


class MetaAPIError(Exception):
    def __init__(self, status: int, error: dict[str, Any]):
        self.status = status
        self.code = error.get("code")
        self.subcode = error.get("error_subcode")
        self.is_transient = bool(error.get("is_transient"))
        self.fbtrace_id = error.get("fbtrace_id")
        self.error = error
        msg = error.get("error_user_msg") or error.get("message") or "unknown error"
        super().__init__(f"HTTP {status} code={self.code} subcode={self.subcode} "
                         f"fbtrace_id={self.fbtrace_id}: {msg}")

    @property
    def retryable(self) -> bool:
        return self.is_transient or self.code in RETRYABLE_CODES or self.status >= 500


class MetaClient:
    def __init__(self, access_token: str, app_secret: str | None = None,
                 api_version: str = "v24.0", timeout: float = 120,
                 max_retries: int = 6, session: requests.Session | None = None):
        self.access_token = access_token
        self.appsecret_proof = (
            hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()
            if app_secret else None)
        self.base = f"{GRAPH_URL}/{api_version}"
        self.timeout = timeout
        self.max_retries = max_retries
        self.http = session or requests.Session()

    # ---- transport -------------------------------------------------------
    def _auth(self) -> dict[str, str]:
        auth = {"access_token": self.access_token}
        if self.appsecret_proof:
            auth["appsecret_proof"] = self.appsecret_proof
        return auth

    def request(self, method: str, path: str, params: dict | None = None,
                data: dict | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        params = dict(params or {})
        data = dict(data or {})
        # Keep the token out of URLs (and thus proxy/access logs) where we can.
        if method == "GET":
            if "access_token=" not in url:   # paging `next` URLs already carry it
                params.update(self._auth())
        else:
            data.update(self._auth())

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.request(method, url, params=params, data=data or None,
                                         timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.max_retries:
                    raise
                self._sleep(attempt, None, f"network error: {exc}")
                continue

            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": resp.text[:500]}}

            if resp.ok and "error" not in body:
                return body

            err = MetaAPIError(resp.status_code, body.get("error", {}))
            if not err.retryable or attempt == self.max_retries:
                raise err
            self._sleep(attempt, resp, str(err))
        raise AssertionError("unreachable")

    def _sleep(self, attempt: int, resp: requests.Response | None, why: str) -> None:
        delay = min(2 ** attempt * 5, 300) + random.uniform(0, 2)
        wait_hint = _regain_access_seconds(resp) if resp is not None else 0
        delay = max(delay, wait_hint)
        log.warning("Retrying in %.0fs (attempt %d/%d): %s",
                    delay, attempt + 1, self.max_retries, why)
        time.sleep(delay)

    def paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        page = self.request("GET", path, params=params)
        while True:
            yield from page.get("data", [])
            nxt = page.get("paging", {}).get("next")
            if not nxt:
                return
            page = self.request("GET", nxt)

    # ---- custom audiences ------------------------------------------------
    @staticmethod
    def act(ad_account_id: str) -> str:
        return ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"

    def find_audience(self, ad_account_id: str, name: str) -> dict | None:
        for aud in self.paginate(f"{self.act(ad_account_id)}/customaudiences",
                                 {"fields": "id,name,subtype", "limit": 500}):
            if aud.get("name") == name:
                return aud
        return None

    def create_audience(self, ad_account_id: str, name: str, description: str = "",
                        customer_file_source: str = "USER_PROVIDED_ONLY") -> str:
        body = self.request("POST", f"{self.act(ad_account_id)}/customaudiences", data={
            "name": name,
            "subtype": "CUSTOM",
            "description": description,
            "customer_file_source": customer_file_source,
        })
        return body["id"]

    def get_audience(self, audience_id: str) -> dict:
        return self.request("GET", audience_id, params={
            "fields": "id,name,approximate_count_lower_bound,"
                      "approximate_count_upper_bound,operation_status,delivery_status"})

    def upload(self, audience_id: str, mode: str, schema: Sequence[str],
               rows: Sequence[Sequence[str]], session: dict | None = None) -> dict:
        """mode: add -> POST /users, replace -> POST /usersreplace,
        remove -> DELETE /users. Max 10,000 rows per call."""
        payload = json.dumps({"schema": list(schema), "data": [list(r) for r in rows]},
                             separators=(",", ":"))
        data = {"payload": payload}
        if session:
            data["session"] = json.dumps(session, separators=(",", ":"))
        method, edge = {
            "add": ("POST", "users"),
            "replace": ("POST", "usersreplace"),
            "remove": ("DELETE", "users"),
        }[mode]
        return self.request(method, f"{audience_id}/{edge}", data=data)


def _regain_access_seconds(resp: requests.Response) -> float:
    """Meta reports throttling backoff (in minutes) in X-Business-Use-Case-Usage."""
    header = resp.headers.get("X-Business-Use-Case-Usage")
    if not header:
        return 0
    try:
        usage = json.loads(header)
        minutes = max((entry.get("estimated_time_to_regain_access", 0) or 0)
                      for entries in usage.values() for entry in entries)
        return minutes * 60
    except (ValueError, AttributeError, TypeError):
        return 0
