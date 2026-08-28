import http.client
import logging
import os
import socket
import time
import xmlrpc.client

import pandas as pd


class OdooConnectorError(RuntimeError):
    pass


logger = logging.getLogger(__name__)
TRANSIENT_ODOO_ERRORS = (
    xmlrpc.client.ProtocolError,
    TimeoutError,
    socket.timeout,
    ConnectionError,
    http.client.HTTPException,
)


def _call_with_retry(operation, func, *args, attempts=4, backoff_seconds=5, **kwargs):
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except TRANSIENT_ODOO_ERRORS as exc:
            if attempt == attempts:
                logger.error(
                    "Odoo XML-RPC call failed operation=%s attempt=%s/%s error=%s retry=false",
                    operation,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )
                raise
            retry_delay = backoff_seconds * attempt
            logger.warning(
                "Odoo XML-RPC call failed operation=%s attempt=%s/%s error=%s "
                "retry=true retry_in_seconds=%s",
                operation,
                attempt,
                attempts,
                type(exc).__name__,
                retry_delay,
            )
            time.sleep(retry_delay)


def _get_required_env(name):
    if not name:
        raise OdooConnectorError("Missing required Odoo environment variable reference.")
    value = os.environ.get(name or "")
    if not value:
        raise OdooConnectorError(f"Missing required Odoo environment variable: {name}")
    return value


def _connection_settings(source_config):
    connection = source_config.get("connection") or {}
    return {
        "url": _get_required_env(connection.get("url_env")),
        "db": _get_required_env(connection.get("db_env")),
        "username": _get_required_env(connection.get("username_env")),
        "api_key": _get_required_env(connection.get("api_key_env")),
    }


def _odoo_clients(url):
    base_url = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/common", allow_none=True)
    models = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object", allow_none=True)
    return common, models


def _flatten_value(field, value):
    if isinstance(value, list) and len(value) >= 2 and isinstance(value[0], int):
        return {
            field: value[1],
            f"{field}_id": value[0],
            f"{field}_name": value[1],
        }
    if value is False:
        return {field: None}
    return {field: value}


def _flatten_record(record):
    output = {}
    for field, value in record.items():
        output.update(_flatten_value(field, value))
    return output


def _build_domain(source_config, watermark):
    domain = list(source_config.get("domain") or [])
    incremental_field = source_config.get("incremental_field") or source_config.get("incremental_column")
    if watermark is not None and incremental_field:
        domain.append([incremental_field, ">", str(watermark)])
    return domain


def _model_field_names(models, settings, uid, model):
    result = _call_with_retry(
        "fields_get",
        models.execute_kw,
        settings["db"],
        uid,
        settings["api_key"],
        model,
        "fields_get",
        [],
        {"attributes": ["type"]},
    )
    return set(result)


def _requested_fields(models, settings, uid, model, config):
    required = list(config.get("fields") or [])
    optional = list(config.get("optional_fields") or [])
    if not optional:
        return required
    available = _model_field_names(models, settings, uid, model)
    return required + [field for field in optional if field in available]


def _resolve_model_candidate(models, settings, uid, source_config):
    candidates = source_config.get("model_candidates") or []
    if not candidates:
        model = source_config.get("model") or source_config.get("object")
        if not model:
            raise OdooConnectorError("Odoo source requires 'model' or 'object'.")
        return model, source_config

    attempted = []
    for candidate in candidates:
        model = candidate.get("model") or candidate.get("object")
        if not model:
            raise OdooConnectorError("Every Odoo model candidate requires 'model' or 'object'.")
        attempted.append(model)
        try:
            available = _model_field_names(models, settings, uid, model)
        except xmlrpc.client.Fault:
            logger.info("Odoo model candidate unavailable model=%s", model)
            continue

        required = set(candidate.get("fields") or [])
        missing = sorted(required - available)
        if missing:
            logger.info(
                "Odoo model candidate missing required fields model=%s fields=%s",
                model,
                ",".join(missing),
            )
            continue

        resolved = {
            key: value
            for key, value in source_config.items()
            if key != "model_candidates"
        }
        resolved.update(candidate)
        logger.info("Odoo model candidate selected model=%s", model)
        return model, resolved

    raise OdooConnectorError(
        "No compatible Odoo model candidate is available: " + ", ".join(attempted)
    )


def _search_read_all(models, settings, uid, model, source_config, watermark, fields):
    page_size = int(source_config.get("page_size") or source_config.get("limit", 1000))
    max_records_value = source_config.get("max_records")
    max_records = int(max_records_value) if max_records_value is not None else None
    offset = int(source_config.get("offset", 0))
    if page_size <= 0:
        raise OdooConnectorError("Odoo page_size/limit must be greater than zero.")
    if max_records is not None and max_records <= 0:
        raise OdooConnectorError("Odoo max_records must be greater than zero.")
    records = []

    while max_records is None or len(records) < max_records:
        page_limit = page_size
        if max_records is not None:
            page_limit = min(page_size, max_records - len(records))
        kwargs = {
            "fields": fields,
            "limit": page_limit,
            "offset": offset,
            "order": source_config.get("order") or "id asc",
        }
        page = _call_with_retry(
            "search_read",
            models.execute_kw,
            settings["db"],
            uid,
            settings["api_key"],
            model,
            "search_read",
            [_build_domain(source_config, watermark)],
            kwargs,
        )
        records.extend(page)
        if len(page) < kwargs["limit"]:
            break
        offset += len(page)

    return records


def _lookup_ids(series):
    ids = []
    for value in series.dropna().tolist():
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


def _apply_lookups(df, source_config, models, settings, uid):
    for lookup in source_config.get("lookups") or []:
        local_field = lookup["local_field"]
        model = lookup["model"]
        prefix = lookup.get("prefix", f"{model.replace('.', '_')}_")
        if local_field not in df.columns:
            raise OdooConnectorError(f"Odoo lookup local field is missing: {local_field}")

        record_ids = _lookup_ids(df[local_field])
        if not record_ids:
            continue
        fields = _requested_fields(models, settings, uid, model, lookup)
        lookup_rows = {}
        chunk_size = int(lookup.get("chunk_size", 200))
        for start in range(0, len(record_ids), chunk_size):
            chunk = record_ids[start:start + chunk_size]
            records = _call_with_retry(
                "lookup_read",
                models.execute_kw,
                settings["db"],
                uid,
                settings["api_key"],
                model,
                "read",
                [chunk],
                {"fields": fields},
            )
            for record in records:
                flattened = _flatten_record(record)
                record_id = int(flattened.pop("id"))
                lookup_rows[record_id] = {
                    f"{prefix}{name}": value for name, value in flattened.items()
                }

        for column in sorted({name for row in lookup_rows.values() for name in row}):
            df[column] = df[local_field].map(
                lambda value: lookup_rows.get(int(value), {}).get(column)
                if pd.notna(value) else None
            )
    return df


def _apply_aggregate_lookups(df, source_config, models, settings, uid):
    """Enrich source rows with aggregates from a related Odoo model.

    This keeps the source grain intact. It is intended for reference values
    such as the current weighted inventory cost by product, not for creating
    additional fact rows.
    """
    for lookup in source_config.get("aggregate_lookups") or []:
        local_field = lookup["local_field"]
        model = lookup["model"]
        remote_field = lookup["remote_field"]
        prefix = lookup.get("prefix", f"{model.replace('.', '_')}_")
        if local_field not in df.columns:
            raise OdooConnectorError(
                f"Odoo aggregate lookup local field is missing: {local_field}"
            )

        record_ids = _lookup_ids(df[local_field])
        if not record_ids:
            continue

        aggregations = lookup.get("aggregations") or {}
        unsupported = sorted(
            definition.get("operation")
            for definition in aggregations.values()
            if definition.get("operation") != "sum"
        )
        if unsupported:
            raise OdooConnectorError(
                "Unsupported Odoo aggregate lookup operation: "
                + ", ".join(str(operation) for operation in unsupported)
            )

        try:
            fields = _requested_fields(models, settings, uid, model, lookup)
            if remote_field not in fields:
                fields.insert(0, remote_field)

            missing_fields = sorted(
                definition["field"]
                for definition in aggregations.values()
                if definition["field"] not in fields
            )
            if missing_fields:
                raise OdooConnectorError(
                    "Odoo aggregate lookup fields are unavailable: "
                    + ", ".join(missing_fields)
                )

            rows = []
            chunk_size = int(lookup.get("chunk_size", 200))
            for start in range(0, len(record_ids), chunk_size):
                chunk = record_ids[start:start + chunk_size]
                lookup_config = {
                    "domain": list(lookup.get("domain") or [])
                    + [[remote_field, "in", chunk]],
                    "page_size": lookup.get("page_size", 1000),
                    "order": lookup.get("order", "id asc"),
                }
                records = _search_read_all(
                    models,
                    settings,
                    uid,
                    model,
                    lookup_config,
                    None,
                    fields,
                )
                rows.extend(_flatten_record(record) for record in records)

            remote_key = f"{remote_field}_id"
            if not rows:
                continue
            aggregate_frame = pd.DataFrame(rows)
            if remote_key not in aggregate_frame.columns:
                continue
            aggregate_values = {}
            for output_name, definition in aggregations.items():
                field = definition["field"]
                numeric = pd.to_numeric(aggregate_frame[field], errors="coerce")
                aggregate_values[f"{prefix}{output_name}"] = numeric.groupby(
                    aggregate_frame[remote_key]
                ).sum(min_count=1)

            for column, values in aggregate_values.items():
                df[column] = df[local_field].map(
                    lambda value: values.get(int(value)) if pd.notna(value) else None
                )
        except (xmlrpc.client.Fault, OdooConnectorError):
            if not lookup.get("optional", False):
                raise
            logger.info(
                "Optional Odoo aggregate lookup unavailable model=%s",
                model,
            )
    return df


def extract_data(source_config, watermark=None):
    settings = _connection_settings(source_config)

    common, models = _odoo_clients(settings["url"])
    uid = _call_with_retry(
        "authenticate",
        common.authenticate,
        settings["db"],
        settings["username"],
        settings["api_key"],
        {},
    )
    if not uid:
        raise OdooConnectorError("Odoo authentication failed.")

    model, resolved_config = _resolve_model_candidate(
        models, settings, uid, source_config
    )
    fields = _requested_fields(models, settings, uid, model, resolved_config)
    records = _search_read_all(
        models,
        settings,
        uid,
        model,
        resolved_config,
        watermark,
        fields,
    )

    rows = [_flatten_record(record) for record in records]
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _apply_lookups(df, resolved_config, models, settings, uid)
    df = _apply_aggregate_lookups(df, resolved_config, models, settings, uid)

    source_name = resolved_config.get("name", model)
    df["__source"] = source_name
    df["__odoo_model"] = model
    return df
