# BigQuery → Meta Custom Audiences

Runs BigQuery queries and pushes the results into Meta (Facebook) Custom
Audiences by calling the Marketing API over plain HTTPS with `requests`.
It does **not** use the `facebook-business` SDK.

## How it works

1. For each audience in `config.yaml`, the sync runs its SQL (inline `sql` or `sql_file`, with optional `@params`).
2. It maps the output columns to Meta schema keys (`EMAIL`, `PHONE`, `FN`, `LN`, `CT`, `ST`, `ZIP`, `COUNTRY`, `GEN`, `DOB`→`DOBY/DOBM/DOBD`, `EXTERN_ID`, `MADID`).
3. It normalizes each value to Meta's rules and SHA-256 hashes it (`normalize.py`). Values that are already hashed (64 hex characters) pass through unchanged, so hashing can also happen in BigQuery if you prefer.
4. It uploads rows in batches of up to 10k through `POST /{audience_id}/users` (`add`), `POST /{audience_id}/usersreplace` (`replace`) or `DELETE /{audience_id}/users` (`remove`). Every batch in a run shares one upload `session`, and the final batch carries `last_batch_flag`.
5. It retries throttling and transient errors with backoff, honoring the `X-Business-Use-Case-Usage` header.

If an audience is given by `name`, the sync finds it in the ad account or
creates it (`create_if_missing`, `customer_file_source=USER_PROVIDED_ONLY`).

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml          # edit
gcloud auth application-default login       # or GOOGLE_APPLICATION_CREDENTIALS
export META_ACCESS_TOKEN=...                # system user token, ads_management
export META_APP_SECRET=...                  # optional; sends appsecret_proof
python sync.py --config config.yaml --dry-run   # query + hash, no Meta calls
python sync.py --config config.yaml
```

Run the tests with `python -m unittest discover -s tests`.

## Meta-side prerequisites

* A Business Manager **system user** whose token has `ads_management`, assigned to the ad account.
* The ad account has accepted the Custom Audience Terms of Service, or uploads fail with an error.
* `api_version` in the config is pinned. Meta retires Graph versions about 2 years after release, so bump it periodically.

## Notes and caveats (draft)

* `replace` swaps the audience's entire membership without resetting ad-set learning. It refuses to run with zero rows so a broken query can't empty an audience. Meta allows only one replace session per audience at a time, and it must finish within its time window (about 90 minutes), so very large audiences may need a faster BigQuery read path (e.g. the BigQuery Storage API).
* A row needs at least one of EMAIL / PHONE / LN / EXTERN_ID / MADID after normalization, otherwise it is skipped and counted as `skipped_no_identifiers`.
* Phone numbers without a `+`/`00` prefix get `default_phone_country_code` prepended. Make sure that is right for your data.
* Only include people you have consent to use for ad targeting. Hashing is required by Meta, but the data still counts as personal data.
