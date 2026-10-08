"""Run a BigQuery query and stream its rows as dicts."""
from __future__ import annotations

from typing import Any, Iterator, Mapping


def _param(name: str, value: Any):
    from google.cloud import bigquery

    if isinstance(value, bool):
        kind = "BOOL"
    elif isinstance(value, int):
        kind = "INT64"
    elif isinstance(value, float):
        kind = "FLOAT64"
    elif isinstance(value, (list, tuple)):
        inner = "INT64" if value and all(isinstance(v, int) for v in value) else "STRING"
        return bigquery.ArrayQueryParameter(name, inner, list(value))
    else:
        kind = "STRING"
    return bigquery.ScalarQueryParameter(name, kind, value)


def run_query(sql: str, *, project: str | None = None, location: str | None = None,
              params: Mapping[str, Any] | None = None,
              page_size: int = 10_000) -> tuple[int, Iterator[dict[str, Any]]]:
    """Returns (total_rows, row iterator). Rows are fetched page by page, so
    large audiences are never held in memory all at once."""
    from google.cloud import bigquery  # imported lazily so tests don't need it

    client = bigquery.Client(project=project, location=location)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in (params or {}).items()])
    result = client.query(sql, job_config=job_config).result(page_size=page_size)
    return result.total_rows or 0, (dict(row.items()) for row in result)
