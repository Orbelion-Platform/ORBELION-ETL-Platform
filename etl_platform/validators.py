import os
import sys
import re
import yaml
import argparse
from urllib.parse import urlparse
from sqlalchemy import inspect, text

from etl_platform.core.config import _load_yaml_file
from etl_platform.core.config import ConfigValidationError
from etl_platform.core.db.connection import get_engine
from etl_platform.client_manifest import (
    ManifestValidationError,
    load_manifest,
    referenced_environment_variables,
)


class ValidationError(Exception):
    pass


ENV_VAR_PATTERN = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
SECRET_FIELD_NAMES = {
    "user",
    "username",
    "password",
    "passwd",
    "pwd",
    "token",
    "api_token",
    "api_key",
    "secret",
    "client_secret",
    "access_token",
    "refresh_token",
}


def _is_env_reference(value):
    return isinstance(value, str) and bool(re.fullmatch(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", value.strip()))


def _contains_env_reference(value):
    return isinstance(value, str) and bool(ENV_VAR_PATTERN.search(value))


def _find_hardcoded_secrets(node, path=""):
    findings = []

    if isinstance(node, dict):
        for key, value in node.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            normalized_key = key_text.lower()

            if normalized_key in SECRET_FIELD_NAMES:
                if value not in (None, "") and not _is_env_reference(value):
                    findings.append(child_path)

            if normalized_key == "authorization" and isinstance(value, str):
                if ("bearer " in value.lower() or "apikey " in value.lower()) and not _contains_env_reference(value):
                    findings.append(child_path)

            findings.extend(_find_hardcoded_secrets(value, child_path))

    elif isinstance(node, list):
        for index, value in enumerate(node):
            findings.extend(_find_hardcoded_secrets(value, f"{path}[{index}]"))

    return findings


def validate_no_hardcoded_secrets(config):
    findings = _find_hardcoded_secrets(config)
    if findings:
        raise ValidationError(
            "Hardcoded secrets are not allowed. Use environment variables for: "
            + ", ".join(sorted(set(findings)))
        )


def find_env_vars_in_file(path):
    text = open(path, 'r', encoding='utf-8-sig').read()
    return set(ENV_VAR_PATTERN.findall(text))


def validate_yaml_syntax(path):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            yaml.safe_load(f)
    except Exception as e:
        raise ValidationError(f"YAML syntax error in {path}: {e}")


def validate_env_vars(path):
    vars_needed = find_env_vars_in_file(path)
    missing = [v for v in vars_needed if v not in os.environ]
    if missing:
        raise ValidationError(f"Missing environment variables referenced in config: {missing}")


def validate_api_source(src):
    url = src.get('url')
    if not url:
        raise ValidationError(f"API source '{src.get('name')}' missing 'url'")
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValidationError(f"API source '{src.get('name')}' has invalid URL: {url}")

    auth = src.get("auth") or {}
    if auth:
        auth_type = auth.get("type")
        if auth_type not in ("bearer", "api_key"):
            raise ValidationError(f"API source '{src.get('name')}' has invalid auth.type: {auth_type}")
        if auth_type == "bearer" and not (auth.get("token_env") or auth.get("token")):
            raise ValidationError(f"API source '{src.get('name')}' bearer auth requires token_env or token env reference")
        if auth_type == "api_key" and not (auth.get("key_env") or auth.get("key")):
            raise ValidationError(f"API source '{src.get('name')}' api_key auth requires key_env or key env reference")


def validate_file_source(src):
    path = src.get('path')
    if not path:
        raise ValidationError(f"File source '{src.get('name')}' missing 'path'")
    if not os.path.isabs(path):
        # allow relative paths; resolve
        cfg_dir = os.path.dirname(src.get('__config_path__', ''))
        if cfg_dir:
            path = os.path.abspath(os.path.join(cfg_dir, path))
    if not os.path.exists(path):
        raise ValidationError(f"File source '{src.get('name')}' path not found: {path}")
    # If it's a directory, ensure at least one matching file exists
    if os.path.isdir(path):
        ext = '.csv' if src.get('type') == 'csv' else ('.xls', '.xlsx', '.xlsm')
        if not any(f.lower().endswith(ext if isinstance(ext, str) else tuple(ext)) for f in os.listdir(path)):
            raise ValidationError(f"File source '{src.get('name')}' directory is empty or has no matching files: {path}")


def validate_database_connection(config):
    try:
        engine = get_engine(config)
        with engine.begin() as conn:
            current = conn.execute(text("SELECT DB_NAME()")) .scalar()
            expected = config.get("database")
            if expected and str(current).lower() != str(expected).lower():
                raise ValidationError("INVALID: destination database mismatch")
            conn.execute(text("SELECT 1"))
    except ValidationError:
        raise
    except Exception as exc:
        status = "INSUFFICIENT_PERMISSIONS" if "permission" in str(exc).lower() or "login failed" in str(exc).lower() else "UNREACHABLE"
        raise ValidationError(f"{status}: SQL Server destination") from exc


def _validate_env_reference_names(config):
    invalid = []
    for source in config.get("sources", []):
        for container_name, container in (("source", source), ("connection", source.get("connection") or {})):
            for key, value in container.items():
                if key.endswith("_env") and (
                    not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", value)
                ):
                    invalid.append(f"{source.get('name')}.{container_name}.{key}")
    if invalid:
        raise ValidationError("INVALID environment references: " + ", ".join(invalid))


def _required_runtime_env(config):
    required = set()
    for source in config.get("sources", []):
        for container in (source, source.get("connection") or {}):
            required.update(
                value for key, value in container.items()
                if key.endswith("_env") and isinstance(value, str)
            )
    return sorted(required)


def validate_runtime_environment(config):
    missing = [name for name in _required_runtime_env(config) if not os.environ.get(name)]
    if missing:
        raise ValidationError("MISSING environment variables: " + ", ".join(missing))
    return True


def validate_odoo_diagnostic(config):
    import xmlrpc.client

    def validate_model(models, values, uid, model, fields, label):
        if not model:
            raise ValidationError(f"INVALID Odoo model: {label}")
        available = models.execute_kw(
            values["db"], uid, values["api_key"], model, "fields_get", [],
            {"attributes": ["type"]},
        )
        missing_fields = sorted(set(fields or []) - set(available))
        if missing_fields:
            raise ValidationError(
                f"INVALID Odoo fields for {model}: {', '.join(missing_fields)}"
            )

    for source in config.get("sources", []):
        if source.get("type") != "odoo":
            continue
        connection = source.get("connection") or {}
        values = {key[:-4]: os.environ.get(value) for key, value in connection.items() if key.endswith("_env")}
        try:
            url = values["url"].rstrip("/")
            common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
            models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
            uid = common.authenticate(values["db"], values["username"], values["api_key"], {})
            if not uid:
                raise ValidationError(f"INVALID Odoo authentication: {source.get('name')}")
            candidates = source.get("model_candidates") or [source]
            selected = None
            for candidate in candidates:
                model = candidate.get("model") or candidate.get("object")
                try:
                    validate_model(
                        models, values, uid, model, candidate.get("fields"),
                        candidate.get("name") or source.get("name"),
                    )
                except (ValidationError, xmlrpc.client.Fault):
                    if len(candidates) == 1:
                        raise
                    continue
                selected = candidate
                break
            if selected is None:
                attempted = ", ".join(
                    candidate.get("model") or candidate.get("object") or "<missing>"
                    for candidate in candidates
                )
                raise ValidationError(
                    f"INVALID Odoo model candidates: {attempted}"
                )
            for lookup in selected.get("lookups") or []:
                if not lookup.get("local_field"):
                    raise ValidationError("INVALID Odoo lookup local_field")
                validate_model(
                    models,
                    values,
                    uid,
                    lookup.get("model"),
                    lookup.get("fields"),
                    f"{source.get('name')} lookup",
                )
            for lookup in selected.get("aggregate_lookups") or []:
                if not lookup.get("local_field") or not lookup.get("remote_field"):
                    raise ValidationError("INVALID Odoo aggregate lookup fields")
                try:
                    validate_model(
                        models,
                        values,
                        uid,
                        lookup.get("model"),
                        lookup.get("fields"),
                        f"{source.get('name')} aggregate lookup",
                    )
                except (ValidationError, xmlrpc.client.Fault):
                    if not lookup.get("optional", False):
                        raise
        except ValidationError:
            raise
        except Exception as exc:
            status = "INSUFFICIENT_PERMISSIONS" if "access" in str(exc).lower() else "UNREACHABLE"
            raise ValidationError(f"{status}: Odoo source {source.get('name')}") from exc
    return True


def validate_destination_schema(config):
    try:
        inspector = inspect(get_engine(config))
        schema = config.get("schema", "dw")
        if schema not in inspector.get_schema_names():
            raise ValidationError(f"INVALID destination schema: {schema}")
        tables = set(inspector.get_table_names(schema=schema))
        required_control = {"etl_runs", "etl_files_processed", "etl_watermark"}
        missing = sorted(required_control - tables)
        if missing:
            raise ValidationError("INVALID control tables: " + ", ".join(missing))
        required_standard = {"dim_fecha"}
        missing = sorted(required_standard - tables)
        if missing:
            raise ValidationError("INVALID standard tables: " + ", ".join(missing))
        for table in [config.get("staging_table")] + [d.get("name") for d in config.get("dimensions", [])] + [f.get("name") for f in config.get("facts", [])]:
            if table and table not in tables:
                raise ValidationError(f"INVALID destination table: {schema}.{table}")
        staging = config.get("staging_table")
        if staging:
            staging_columns = {item["name"] for item in inspector.get_columns(staging, schema=schema)}
            missing = sorted(set(config.get("required_columns", [])) - staging_columns)
            if missing:
                raise ValidationError("INVALID staging columns: " + ", ".join(missing))
        for dimension in config.get("dimensions", []):
            actual = {item["name"] for item in inspector.get_columns(dimension["name"], schema=schema)}
            expected = set((dimension.get("columns") or {}).keys()) | {
                dimension.get("surrogate_key"), dimension.get("natural_key")
            }
            missing = sorted(item for item in expected - actual if item)
            if missing:
                raise ValidationError(f"INVALID dimension columns {dimension['name']}: " + ", ".join(missing))
        for fact in config.get("facts", []):
            actual = {item["name"] for item in inspector.get_columns(fact["name"], schema=schema)}
            expected = set((fact.get("columns") or {}).keys()) | {fact.get("business_key")}
            missing = sorted(item for item in expected - actual if item)
            if missing:
                raise ValidationError(f"INVALID fact columns {fact['name']}: " + ", ".join(missing))
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("UNREACHABLE: destination metadata") from exc
    return True


def _resolve_rules_dir(meta_root):
    for candidate in ('rules', 'Rules'):
        candidate_dir = os.path.join(meta_root, candidate)
        if os.path.isdir(candidate_dir):
            return candidate_dir
    return os.path.join(meta_root, 'rules')


def _extract_metadata_references(section):
    if isinstance(section, dict):
        names = []
        for name, definition in section.items():
            if isinstance(definition, dict):
                continue
            if isinstance(definition, str):
                names.append(definition)
            else:
                names.append(name)
        return names
    if isinstance(section, list):
        return section
    if isinstance(section, str):
        return [section]
    return []


def _check_metadata_section(config, meta_root, client, section_name, direct_root=False):
    names = _extract_metadata_references(config.get(section_name) or {})
    missing = []
    for name in names:
        if direct_root:
            client_path = os.path.join(meta_root, client, f"{name}.yaml") if client else None
            generic_path = os.path.join(meta_root, f"{name}.yaml")
        else:
            client_path = os.path.join(meta_root, section_name, client, f"{name}.yaml") if client else None
            generic_path = os.path.join(meta_root, section_name, f"{name}.yaml")

        if client and client_path and os.path.exists(client_path):
            continue
        if os.path.exists(generic_path):
            continue
        missing.append(name)
    return missing


def validate_metadata_references(config, config_path, metadata_root=None):
    if metadata_root is None:
        metadata_root = config.get('metadata_root')

    client = os.path.basename(os.path.dirname(os.path.abspath(config_path)))
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    meta_root = os.path.join(repo_root, 'metadata') if not metadata_root else metadata_root
    if meta_root and not os.path.isabs(meta_root):
        meta_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(config_path)), meta_root))

    missing = []
    missing += _check_metadata_section(config, meta_root, client, 'mappings')
    missing += _check_metadata_section(config, meta_root, client, 'schemas')
    missing += _check_metadata_section(config, _resolve_rules_dir(meta_root), client, 'rules', direct_root=True)

    if missing:
        raise ValidationError(f"Missing metadata files for: {sorted(set(missing))}")

    return True


def _migration_paths_for_config(config, repo_root, client):
    paths = []
    if config.get("analytical_contract_version"):
        paths.append(os.path.join(repo_root, "ddl", "migrations", "analytics"))
    if any(source.get("type") == "odoo" for source in config.get("sources", [])):
        paths.append(os.path.join(repo_root, "ddl", "migrations", "odoo"))
    paths.append(os.path.join(repo_root, "ddl", "migrations", client))
    return paths


def validate_dwh_contract(config, config_path):
    for dim in config.get("dimensions", []):
        columns = dim.get("columns") or {}
        natural_key = dim.get("natural_key")
        if not natural_key or natural_key not in columns:
            raise ValidationError(f"INVALID dimension natural key: {dim.get('name')}")
        if not dim.get("surrogate_key"):
            raise ValidationError(f"INVALID dimension surrogate key: {dim.get('name')}")
    for fact in config.get("facts", []):
        columns = fact.get("columns") or {}
        business_key = fact.get("business_key")
        if not business_key or business_key not in columns:
            raise ValidationError(f"INVALID fact business key: {fact.get('name')}")
        if business_key.lower() not in str(fact.get("query", "")).lower():
            raise ValidationError(f"INVALID fact query business key: {fact.get('name')}")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    base_path = os.path.join(repo_root, "ddl", "base")
    base_sql_text = "\n".join(
        open(os.path.join(base_path, name), "r", encoding="utf-8-sig").read()
        for name in os.listdir(base_path) if name.endswith(".sql")
    ).lower()
    if "dim_fecha" not in base_sql_text:
        raise ValidationError("INVALID base migration contract for dimension: dim_fecha")
    client = config.get("client") or os.path.basename(os.path.dirname(os.path.abspath(config_path)))
    paths = _migration_paths_for_config(config, repo_root, client)
    missing_paths = [path for path in paths if not os.path.isdir(path)]
    if missing_paths:
        raise ValidationError("INVALID migration folders: " + ", ".join(os.path.basename(p) for p in missing_paths))
    sql_text = "\n".join(
        open(os.path.join(path, name), "r", encoding="utf-8-sig").read()
        for path in paths for name in os.listdir(path) if name.endswith(".sql")
    ).lower()
    staging = config.get("staging_table")
    if staging and staging.lower() not in sql_text:
        raise ValidationError(f"INVALID migration contract for staging table: {staging}")
    required_ddl_columns = set(config.get("required_columns", []))
    required_ddl_columns.update(
        column for dimension in config.get("dimensions", [])
        for column in list((dimension.get("columns") or {}).keys())
        + [dimension.get("surrogate_key"), dimension.get("natural_key")]
        if column
    )
    required_ddl_columns.update(
        column for fact in config.get("facts", [])
        for column in list((fact.get("columns") or {}).keys()) + [fact.get("business_key")]
        if column
    )
    missing_columns = sorted(column for column in required_ddl_columns if column.lower() not in sql_text)
    if missing_columns:
        raise ValidationError("INVALID migration column contract: " + ", ".join(missing_columns))
    for fact in config.get("facts", []):
        if fact.get("name", "").lower() not in sql_text:
            raise ValidationError(f"INVALID migration contract for fact: {fact.get('name')}")
    return True


def validate_manifest_file(manifest_path, diagnostic=False):
    try:
        manifest = load_manifest(manifest_path)
    except ManifestValidationError as exc:
        raise ValidationError(str(exc)) from exc
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    versions_path = os.path.join(repo_root, "config", "framework_versions.yml")
    with open(versions_path, "r", encoding="utf-8") as stream:
        supported = yaml.safe_load(stream)
    requested = manifest["versions"]
    compatibility = {
        "framework": supported.get("compatible_manifest_framework", []),
        "ddl": supported.get("compatible_ddl", []),
        "metadata": supported.get("compatible_metadata", []),
    }
    incompatible = [name for name, allowed in compatibility.items() if requested.get(name) not in allowed]
    if incompatible:
        raise ValidationError("INVALID compatibility versions: " + ", ".join(incompatible))
    if diagnostic:
        missing = [name for name in referenced_environment_variables(manifest) if not os.environ.get(name)]
        if missing:
            raise ValidationError("MISSING environment variables: " + ", ".join(missing))
    return True


def validate_config_full(config_path, check_db=True, diagnostic=None):
    if diagnostic is None:
        diagnostic = check_db
    # 1. Existence
    if not os.path.exists(config_path):
        raise ValidationError(f"Config file not found: {config_path}")

    # 2. YAML syntax
    validate_yaml_syntax(config_path)

    # 3. Required env vars (presence is diagnostic; syntax is checked statically)
    if diagnostic:
        validate_env_vars(config_path)

    # 4. Load config (expands vars)
    cfg = _load_yaml_file(config_path)
    validate_no_hardcoded_secrets(cfg)
    _validate_env_reference_names(cfg)

    # attach config path to sources for relative resolution
    cfg['__config_path__'] = os.path.abspath(config_path)

    # 6. Files existence
    sources = cfg.get('sources', [])
    is_template = 'template' in os.path.basename(config_path).lower()
    for src in sources:
        src['__config_path__'] = cfg['__config_path__']
        stype = src.get('type')
        if stype in ('csv', 'excel'):
            # Skip strict file existence for template configs to allow onboarding copies
            if is_template:
                continue
            validate_file_source(src)
        elif stype in ('api', 'rest'):
            validate_api_source(src)
        elif stype == 'database':
            if diagnostic:
                validate_database_connection({**cfg, **(src.get('connection') or {})})
        elif stype == 'odoo':
            connection = src.get('connection')
            if not isinstance(connection, dict):
                raise ValidationError("INVALID Odoo connection section")
            required_keys = {'url_env', 'db_env', 'username_env', 'api_key_env'}
            missing_keys = sorted(required_keys - set(connection))
            if missing_keys:
                raise ValidationError("INVALID Odoo connection references: " + ", ".join(missing_keys))

    # 9. metadata
    is_template = 'template' in os.path.basename(config_path).lower()
    if not is_template:
        try:
            validate_metadata_references(cfg, config_path)
        except ValidationError:
            # If no mappings specified, skip
            if cfg.get('mappings'):
                raise

    # 10. DDL & pipeline consistency
    # check ddl base exists
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    ddl_base = os.path.join(repo_root, 'ddl', 'base')
    if not os.path.isdir(ddl_base):
        raise ValidationError('DDL base directory not found: ddl/base')

    validate_dwh_contract(cfg, config_path)

    if diagnostic:
        validate_runtime_environment(cfg)
        validate_database_connection(cfg)
        validate_destination_schema(cfg)
        validate_odoo_diagnostic(cfg)

    return True


def main(argv=None):
    p = argparse.ArgumentParser(description='Pre-run config validator for ETL Platform')
    p.add_argument('config', nargs='?', help='Path to YAML config file')
    p.add_argument('--manifest', help='Path to a client manifest')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--static', action='store_true', help='Static validation only')
    mode.add_argument('--diagnostic', action='store_true', help='Validate variables and live connections')
    p.add_argument('--no-db', dest='static', action='store_true', help='Backward-compatible alias for --static')
    args = p.parse_args(argv)

    try:
        if not args.config and not args.manifest:
            p.error('config or --manifest is required')
        diagnostic = args.diagnostic or not args.static
        if args.manifest:
            validate_manifest_file(args.manifest, diagnostic=diagnostic)
        if args.config:
            validate_config_full(args.config, check_db=diagnostic, diagnostic=diagnostic)
        print('VALIDATION OK:', 'DIAGNOSTIC' if diagnostic else 'STATIC')
        return 0
    except (ValidationError, ManifestValidationError, ConfigValidationError) as e:
        print('VALIDATION FAILED:', e)
        return 2


if __name__ == '__main__':
    sys.exit(main())
