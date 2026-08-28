import logging
import os
import time
from urllib.parse import urljoin

import pandas as pd
import requests


logger = logging.getLogger(__name__)


class RestConnectorError(RuntimeError):
    pass


DEFAULT_RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _get_nested(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _with_dynamic_auth(source_config, headers, params):
    auth = source_config.get("auth") or {}
    auth_type = auth.get("type")

    if auth_type == "bearer":
        token = auth.get("token") or os.environ.get(auth.get("token_env", ""))
        if not token:
            raise RestConnectorError("Bearer authentication requires a token.")
        headers[auth.get("header", "Authorization")] = f"Bearer {token}"

    elif auth_type == "api_key":
        key = auth.get("key") or os.environ.get(auth.get("key_env", ""))
        if not key:
            raise RestConnectorError("API key authentication requires a key.")

        key_name = auth.get("name", "X-API-Key")
        location = auth.get("in", "header")
        if location == "query":
            params[key_name] = key
        elif location == "header":
            prefix = auth.get("prefix")
            headers[key_name] = f"{prefix} {key}" if prefix else key
        else:
            raise RestConnectorError(f"Unsupported API key location: {location}")

    elif auth_type:
        raise RestConnectorError(f"Unsupported auth type: {auth_type}")

    return headers, params


def _build_request(source_config, params):
    incremental = source_config.get("incremental") or {}
    watermark = source_config.get("_watermark")
    incremental_param = (
        source_config.get("incremental_param")
        or incremental.get("param")
    )

    if watermark is not None and incremental_param:
        params[incremental_param] = str(watermark)

    headers = dict(source_config.get("headers") or {})
    headers, params = _with_dynamic_auth(source_config, headers, params)
    return headers, params


def _retry_config(source_config):
    retry = source_config.get("retry") or {}
    attempts = int(retry.get("attempts", retry.get("total", source_config.get("retries", 3))))
    backoff = float(retry.get("backoff_factor", retry.get("backoff", 0.5)))
    statuses = set(retry.get("status_codes", DEFAULT_RETRY_STATUS_CODES))
    return max(attempts, 1), max(backoff, 0), statuses


def _rate_limit_interval(source_config):
    rate_limit = source_config.get("rate_limit")
    if isinstance(rate_limit, dict):
        per_second = rate_limit.get("requests_per_second")
    else:
        per_second = source_config.get("requests_per_second")

    if not per_second:
        return 0

    per_second = float(per_second)
    if per_second <= 0:
        return 0
    return 1 / per_second


def _safe_error(response):
    text = response.text or ""
    if len(text) > 300:
        text = text[:300] + "..."
    return f"HTTP {response.status_code} for {response.url}: {text}"


def _request_with_retry(session, method, url, headers, params, timeout, retry, rate_interval, last_request_at):
    attempts, backoff, statuses = retry
    last_error = None

    for attempt in range(1, attempts + 1):
        elapsed = time.monotonic() - last_request_at[0]
        if rate_interval and elapsed < rate_interval:
            time.sleep(rate_interval - elapsed)

        logger.info(
            "rest_request",
            extra={
                "url": url,
                "method": method,
                "attempt": attempt,
                "params": sorted(params.keys()),
            },
        )

        try:
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            last_request_at[0] = time.monotonic()

            if response.status_code in statuses and attempt < attempts:
                time.sleep(backoff * (2 ** (attempt - 1)))
                continue

            if response.status_code >= 400:
                raise RestConnectorError(_safe_error(response))

            return response

        except requests.RequestException as exc:
            last_error = exc
            if attempt >= attempts:
                raise RestConnectorError(f"REST request failed after {attempts} attempts: {exc}") from exc
            time.sleep(backoff * (2 ** (attempt - 1)))

    raise RestConnectorError(f"REST request failed: {last_error}")


def _extract_records(payload, data_key):
    data = _get_nested(payload, data_key) if data_key else payload
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise RestConnectorError("REST response data must be a list or object.")


def _pagination_config(source_config):
    pagination = source_config.get("pagination") or {}
    if not pagination:
        return {"type": "none", "max_pages": 1}
    pagination.setdefault("type", "page")
    pagination.setdefault("max_pages", 100)
    return pagination


def _next_page(url, params, payload, pagination, page_number):
    pagination_type = pagination.get("type")
    max_pages = int(pagination.get("max_pages", 100))
    if page_number >= max_pages:
        return None, params

    next_params = dict(params)

    if pagination_type == "none":
        return None, params

    if pagination_type == "page":
        page_param = pagination.get("page_param", "page")
        start_page = int(pagination.get("start_page", 1))
        next_params[page_param] = start_page + page_number
        if pagination.get("page_size"):
            next_params[pagination.get("page_size_param", "page_size")] = pagination["page_size"]
        return url, next_params

    if pagination_type == "offset":
        offset_param = pagination.get("offset_param", "offset")
        limit = int(pagination.get("limit", pagination.get("page_size", 100)))
        current_offset = int(next_params.get(offset_param, pagination.get("start_offset", 0)))
        next_params[offset_param] = current_offset + limit
        next_params[pagination.get("limit_param", "limit")] = limit
        return url, next_params

    if pagination_type == "cursor":
        cursor = _get_nested(payload, pagination.get("next_cursor_key", "next_cursor"))
        if not cursor:
            return None, params
        next_params[pagination.get("cursor_param", "cursor")] = cursor
        return url, next_params

    if pagination_type == "link":
        next_url = _get_nested(payload, pagination.get("next_url_key", "next"))
        if not next_url:
            return None, params
        return urljoin(url, next_url), next_params

    raise RestConnectorError(f"Unsupported pagination type: {pagination_type}")


def _initial_page(source_config, pagination):
    params = dict(source_config.get("params") or {})
    if pagination.get("type") == "page":
        params.setdefault(pagination.get("page_param", "page"), pagination.get("start_page", 1))
        if pagination.get("page_size"):
            params.setdefault(pagination.get("page_size_param", "page_size"), pagination["page_size"])
    elif pagination.get("type") == "offset":
        params.setdefault(pagination.get("offset_param", "offset"), pagination.get("start_offset", 0))
        params.setdefault(
            pagination.get("limit_param", "limit"),
            pagination.get("limit", pagination.get("page_size", 100)),
        )
    elif pagination.get("type") == "cursor" and pagination.get("initial_cursor"):
        params.setdefault(pagination.get("cursor_param", "cursor"), pagination["initial_cursor"])
    return params


def extract_data(source_config, watermark=None):
    source_config = dict(source_config)
    source_config["_watermark"] = watermark

    session = source_config.get("session") or requests.Session()
    method = source_config.get("method", "GET").upper()
    timeout = source_config.get("timeout", 30)
    retry = _retry_config(source_config)
    rate_interval = _rate_limit_interval(source_config)
    pagination = _pagination_config(source_config)
    data_key = source_config.get("data_key")

    url = source_config["url"]
    params = _initial_page(source_config, pagination)
    records = []
    page_number = 0
    last_request_at = [0]

    while url:
        headers, request_params = _build_request(source_config, dict(params))
        response = _request_with_retry(
            session,
            method,
            url,
            headers,
            request_params,
            timeout,
            retry,
            rate_interval,
            last_request_at,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RestConnectorError(f"Invalid JSON response from {response.url}") from exc
        page_records = _extract_records(payload, data_key)
        records.extend(page_records)

        logger.info(
            "rest_response",
            extra={
                "source": source_config.get("name", "api"),
                "page": page_number + 1,
                "records": len(page_records),
                "status_code": response.status_code,
            },
        )

        if not page_records and pagination.get("stop_on_empty", True):
            break

        page_number += 1
        url, params = _next_page(url, request_params, payload, pagination, page_number)

    df = pd.DataFrame(records)
    if df.empty:
        return df

    df["__source"] = source_config.get("name", "api")
    return df
