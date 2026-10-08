"""Sync BigQuery query results into Meta (Facebook) Custom Audiences.

    export META_ACCESS_TOKEN=...        # system user token with ads_management
    export META_APP_SECRET=...          # optional, enables appsecret_proof
    python sync.py --config config.yaml [--audience NAME] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml

from bq_source import run_query
from meta_client import MetaClient
from normalize import build_row, expand_schema

log = logging.getLogger("bq_to_meta")

MAX_BATCH = 10_000  # Meta's per-request limit


def batches_with_last_flag(rows: Iterable[list[str]], size: int
                           ) -> Iterator[tuple[list[list[str]], bool]]:
    """Yield (batch, is_last). Looks one batch ahead so the final upload can
    carry last_batch_flag=true without knowing the row count up front."""
    it = iter(rows)
    current = list(islice(it, size))
    while current:
        nxt = list(islice(it, size))
        yield current, not nxt
        current = nxt


def upload_rows(client: MetaClient | None, audience_id: str, mode: str,
                schema: Sequence[str], rows: Iterable[list[str]], *,
                batch_size: int = MAX_BATCH, estimated_total: int = 0) -> dict[str, int]:
    """Upload rows in batches. client=None means dry run."""
    session_id = random.randint(1, 2**62)
    stats = {"batches": 0, "sent": 0, "received": 0, "invalid": 0}
    for seq, (batch, is_last) in enumerate(batches_with_last_flag(rows, batch_size), 1):
        stats["batches"] += 1
        stats["sent"] += len(batch)
        if client is None:
            log.info("[dry-run] batch %d: %d rows (last=%s) sample=%s",
                     seq, len(batch), is_last, batch[0])
            continue
        session = None
        if mode in ("add", "replace"):
            session = {"session_id": session_id, "batch_seq": seq,
                       "last_batch_flag": is_last}
            if estimated_total:
                session["estimated_num_total"] = estimated_total
        resp = client.upload(audience_id, mode, schema, batch, session)
        stats["received"] += int(resp.get("num_received", 0))
        stats["invalid"] += int(resp.get("num_invalid_entries", 0))
        if resp.get("num_invalid_entries"):
            log.warning("batch %d: %s invalid entries, samples: %s", seq,
                        resp["num_invalid_entries"], resp.get("invalid_entry_samples"))
        log.info("batch %d: sent %d, Meta received %s (last=%s)",
                 seq, len(batch), resp.get("num_received"), is_last)

    if mode == "replace" and stats["batches"] == 0:
        # A replace with zero rows would never open/close a session; refuse
        # rather than silently leaving the audience stale.
        raise RuntimeError("Query returned no usable rows; refusing to 'replace' with nothing")
    return stats


def resolve_audience(client: MetaClient | None, ad_account_id: str, cfg: dict) -> str:
    if cfg.get("audience_id"):
        return str(cfg["audience_id"])
    if client is None:
        return "<dry-run-audience>"
    existing = client.find_audience(ad_account_id, cfg["name"])
    if existing:
        log.info("Using existing audience %s (%s)", existing["id"], cfg["name"])
        return existing["id"]
    if not cfg.get("create_if_missing"):
        raise RuntimeError(f"Audience {cfg['name']!r} not found and create_if_missing is false")
    audience_id = client.create_audience(
        ad_account_id, cfg["name"], cfg.get("description", ""),
        cfg.get("customer_file_source", "USER_PROVIDED_ONLY"))
    log.info("Created audience %s (%s)", audience_id, cfg["name"])
    return audience_id


def sync_audience(client: MetaClient | None, config: dict, cfg: dict,
                  base_dir: Path) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    bq_cfg = config.get("bigquery", {})
    ad_account_id = str(cfg.get("ad_account_id") or config["meta"]["ad_account_id"])
    mode = cfg.get("mode", "add")
    if mode not in ("add", "replace", "remove"):
        raise ValueError(f"Invalid mode {mode!r}")

    default_country = cfg.get("default_country", defaults.get("default_country"))
    phone_cc = str(cfg.get("default_phone_country_code",
                           defaults.get("default_phone_country_code", "")) or "") or None
    batch_size = min(int(cfg.get("batch_size", defaults.get("batch_size", MAX_BATCH))), MAX_BATCH)
    columns = cfg["columns"]
    schema = expand_schema(columns, default_country)

    sql = cfg.get("sql") or (base_dir / cfg["sql_file"]).read_text()
    audience_id = resolve_audience(client, ad_account_id, cfg)

    log.info("Running query for %r", cfg["name"])
    total, records = run_query(sql, project=bq_cfg.get("project"),
                               location=bq_cfg.get("location"), params=cfg.get("params"),
                               page_size=batch_size)
    log.info("Query returned %d rows; schema=%s", total, schema)

    skipped = 0

    def rows() -> Iterator[list[str]]:
        nonlocal skipped
        for rec in records:
            missing = [c for c in columns.values() if c not in rec]
            if missing:
                raise KeyError(f"Query output is missing mapped columns: {missing}")
            row = build_row(rec, columns, schema, default_country=default_country,
                            default_phone_cc=phone_cc)
            if row is None:
                skipped += 1
            else:
                yield row

    stats = upload_rows(client, audience_id, mode, schema, rows(),
                        batch_size=batch_size, estimated_total=total)
    stats.update(query_rows=total, skipped_no_identifiers=skipped, audience_id=audience_id)
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--audience", action="append",
                    help="Only sync audiences with this name (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run queries and normalize/hash rows, but make no Meta API calls")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text())
    meta_cfg = config["meta"]

    client = None
    if not args.dry_run:
        token = os.environ.get("META_ACCESS_TOKEN")
        if not token:
            log.error("META_ACCESS_TOKEN is not set")
            return 2
        client = MetaClient(token, os.environ.get("META_APP_SECRET"),
                            api_version=meta_cfg.get("api_version", "v24.0"))

    audiences = config["audiences"]
    if args.audience:
        audiences = [a for a in audiences if a["name"] in set(args.audience)]
        if not audiences:
            log.error("No audiences matched %s", args.audience)
            return 2

    failures = 0
    for cfg in audiences:
        try:
            stats = sync_audience(client, config, cfg, config_path.parent)
            log.info("Done %r: %s", cfg["name"], stats)
        except Exception:
            failures += 1
            log.exception("Failed to sync %r", cfg["name"])
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
