import json
import os
import re

import yaml


CLIENT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,49}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
INTERVAL_PATTERN = re.compile(r"^[1-9][0-9]*_(MINUTES|HOURS|DAYS)$")
SUPPORTED_SOURCE_TYPES = {"ODOO", "REST", "CSV", "EXCEL", "SQL"}
SUPPORTED_ODOO_MODULES = {"SALES", "PURCHASE", "INVENTORY", "ACCOUNTING"}


class ManifestValidationError(ValueError):
    pass


def load_manifest(path):
    if not os.path.isfile(path):
        raise ManifestValidationError(f"Manifest not found: {path}")
    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            manifest = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(f"Manifest YAML is invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest must be a YAML mapping.")
    validate_manifest(manifest)
    manifest["__manifest_path__"] = os.path.abspath(path)
    return manifest


def _require_mapping(parent, name):
    value = parent.get(name)
    if not isinstance(value, dict):
        raise ManifestValidationError(f"'{name}' must be a mapping.")
    return value


def _require_text(parent, name, prefix=""):
    value = parent.get(name)
    if not isinstance(value, str) or not value.strip():
        field = f"{prefix}.{name}" if prefix else name
        raise ManifestValidationError(f"'{field}' is required and must be text.")
    return value.strip()


def _validate_env_name(value, field):
    if not ENV_NAME_PATTERN.fullmatch(value or ""):
        raise ManifestValidationError(f"'{field}' must be an environment variable name.")


def validate_manifest(manifest):
    client = _require_mapping(manifest, "client")
    destination = _require_mapping(manifest, "destination")
    scheduling = _require_mapping(manifest, "scheduling")
    versions = _require_mapping(manifest, "versions")

    for field in ("name", "code", "environment", "country", "currency", "timezone"):
        _require_text(client, field, "client")
    code = client["code"]
    if not CLIENT_CODE_PATTERN.fullmatch(code):
        raise ManifestValidationError(
            "'client.code' must use lowercase snake_case and contain 3-50 characters."
        )
    if client["environment"] not in {"DEV", "PROD"}:
        raise ManifestValidationError("'client.environment' must be DEV or PROD.")
    if not re.fullmatch(r"[A-Z]{3}", client["currency"]):
        raise ManifestValidationError("'client.currency' must be an ISO-style 3-letter code.")

    if _require_text(destination, "engine", "destination") != "SQL_SERVER":
        raise ManifestValidationError("Only destination.engine SQL_SERVER is currently supported.")
    auth_mode = destination.get("auth_mode", "SQL_PASSWORD")
    if auth_mode not in {"SQL_PASSWORD", "MANAGED_IDENTITY"}:
        raise ManifestValidationError(
            "'destination.auth_mode' must be SQL_PASSWORD or MANAGED_IDENTITY."
        )
    for field in ("server_env", "database_env"):
        _validate_env_name(_require_text(destination, field, "destination"), f"destination.{field}")
    for field in ("user_env", "password_env"):
        if destination.get(field):
            _validate_env_name(destination[field], f"destination.{field}")
    if destination.get("managed_identity_client_id_env"):
        _validate_env_name(
            destination["managed_identity_client_id_env"],
            "destination.managed_identity_client_id_env",
        )
    for field in ("dev_server", "dev_database"):
        if field in destination:
            _require_text(destination, field, "destination")
    schema = _require_text(destination, "schema", "destination")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", schema):
        raise ManifestValidationError("'destination.schema' is invalid.")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ManifestValidationError("'sources' must be a non-empty list.")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ManifestValidationError(f"sources[{index}] must be a mapping.")
        source_type = _require_text(source, "type", f"sources[{index}]")
        if source_type not in SUPPORTED_SOURCE_TYPES:
            raise ManifestValidationError(f"sources[{index}].type is unsupported: {source_type}")
        if source.get("provider"):
            provider = _require_text(source, "provider", f"sources[{index}]")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", provider):
                raise ManifestValidationError(
                    f"sources[{index}].provider must use uppercase snake case."
                )
        if not isinstance(source.get("enabled"), bool):
            raise ManifestValidationError(f"sources[{index}].enabled must be boolean.")
        modules = source.get("modules")
        if not isinstance(modules, list) or not modules or not all(isinstance(x, str) for x in modules):
            raise ManifestValidationError(f"sources[{index}].modules must be a non-empty text list.")
        if len(modules) != len(set(modules)):
            raise ManifestValidationError(f"sources[{index}].modules contains duplicates.")
        if source_type == "ODOO":
            unsupported = sorted(set(modules) - SUPPORTED_ODOO_MODULES)
            if unsupported:
                raise ManifestValidationError(f"Unsupported Odoo modules: {unsupported}")
            connection = _require_mapping(source, "connection")
            for field in ("url_env", "db_env", "username_env", "api_key_env"):
                _validate_env_name(
                    _require_text(connection, field, f"sources[{index}].connection"),
                    f"sources[{index}].connection.{field}",
                )

    interval = _require_text(scheduling, "etl_interval", "scheduling")
    if not INTERVAL_PATTERN.fullmatch(interval):
        raise ManifestValidationError("'scheduling.etl_interval' has an invalid interval.")
    jobs = scheduling.get("automation_jobs")
    if not isinstance(jobs, list):
        raise ManifestValidationError("'scheduling.automation_jobs' must be a list.")
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            raise ManifestValidationError(f"automation_jobs[{index}] must be a mapping.")
        name = _require_text(job, "name", f"automation_jobs[{index}]")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ManifestValidationError(f"automation_jobs[{index}].name is invalid.")
        if not INTERVAL_PATTERN.fullmatch(_require_text(job, "interval", f"automation_jobs[{index}]")):
            raise ManifestValidationError(f"automation_jobs[{index}].interval is invalid.")
        if "enabled" in job and not isinstance(job["enabled"], bool):
            raise ManifestValidationError(f"automation_jobs[{index}].enabled must be boolean.")

    for field in ("framework", "ddl", "metadata"):
        _require_text(versions, field, "versions")
    return True


def referenced_environment_variables(manifest):
    values = {
        manifest["destination"]["server_env"],
        manifest["destination"]["database_env"],
    }
    if manifest["destination"].get("auth_mode", "SQL_PASSWORD") != "MANAGED_IDENTITY":
        for field in ("user_env", "password_env"):
            if manifest["destination"].get(field):
                values.add(manifest["destination"][field])
    if manifest["destination"].get("managed_identity_client_id_env"):
        values.add(manifest["destination"]["managed_identity_client_id_env"])
    for source in manifest["sources"]:
        connection = source.get("connection") or {}
        values.update(value for key, value in connection.items() if key.endswith("_env"))
        values.update(value for key, value in source.items() if key.endswith("_env"))
    return sorted(values)


def load_schema_document(repo_root):
    path = os.path.join(repo_root, "config", "client_manifest.schema.json")
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)
