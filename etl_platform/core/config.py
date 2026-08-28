import os
import yaml
from urllib.parse import quote_plus

VALID_SOURCE_TYPES = {"csv", "excel", "api", "rest", "database", "odoo"}
VALID_LOAD_MODES = {"incremental", "files", "hybrid"}
VALID_ENVIRONMENTS = {"dev", "prod"}


class ConfigValidationError(ValueError):
    pass


def _load_yaml_file(path):
    if not os.path.isfile(path):
        raise ConfigValidationError(f"Archivo de configuración no encontrado: {path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        document = yaml.safe_load(f)

    if document is None:
        raise ConfigValidationError(f"Archivo de configuración vacío: {path}")

    if not isinstance(document, dict):
        raise ConfigValidationError("La configuración debe ser un objeto YAML de nivel superior.")

    document["__config_path__"] = os.path.abspath(path)
    document["config_dir"] = os.path.dirname(document["__config_path__"])
    return document


def _normalize_environment(config):
    environment = config.get("environment", "dev")
    if environment not in VALID_ENVIRONMENTS:
        raise ConfigValidationError(
            f"environment inválido: {environment}. Debe ser uno de {sorted(VALID_ENVIRONMENTS)}"
        )
    config["environment"] = environment
    return environment


def _normalize_connection_settings(config):
    environment = config["environment"]

    if environment == "dev":
        if "server" not in config or "database" not in config:
            raise ConfigValidationError(
                "En DEV se requieren los campos 'server' y 'database' en la configuracion."
            )
        config.setdefault("encrypt", False)
        config.setdefault("trust_server_certificate", True)
    else:
        if "server" not in config or "database" not in config:
            raise ConfigValidationError(
                "En PROD se requieren los campos 'server' y 'database' en la configuración." 
            )
        config.setdefault("encrypt", True)
        config.setdefault("trust_server_certificate", False)

    return config


def _validate_root_config(config):
    if "process_name" not in config or not isinstance(config["process_name"], str):
        raise ConfigValidationError("Se requiere process_name como texto.")

    config.setdefault("schema", "dw")
    config.setdefault("staging_table", "stg_load")
    config.setdefault("load_mode", "incremental")
    config.setdefault("incremental_column", None)
    config.setdefault("required_columns", [])
    config.setdefault("keys", {})
    config.setdefault("dimensions", [])
    config.setdefault("facts", [])
    config.setdefault("analytical_contract_version", None)

    if config["analytical_contract_version"] not in {None, "2.0.0"}:
        raise ConfigValidationError(
            "analytical_contract_version no soportada. Use 2.0.0."
        )

    if config["load_mode"] not in VALID_LOAD_MODES:
        raise ConfigValidationError(
            f"load_mode inválido: {config['load_mode']}. Debe ser uno de {sorted(VALID_LOAD_MODES)}"
        )

    if not isinstance(config["required_columns"], list):
        raise ConfigValidationError("required_columns debe ser una lista.")

    if not isinstance(config["keys"], dict):
        raise ConfigValidationError("keys debe ser un diccionario.")

    if not isinstance(config["dimensions"], list):
        raise ConfigValidationError("dimensions debe ser una lista.")

    if not isinstance(config["facts"], list):
        raise ConfigValidationError("facts debe ser una lista.")

    return config


def _validate_source(source, index, config):
    if not isinstance(source, dict):
        raise ConfigValidationError(f"La fuente en index {index} debe ser un objeto YAML.")

    source_type = source.get("type")
    if not source_type or source_type not in VALID_SOURCE_TYPES:
        raise ConfigValidationError(
            f"Fuente {index}: type inválido o faltante. Debe ser uno de {sorted(VALID_SOURCE_TYPES)}"
        )

    source_name = source.get("name", f"source_{index}")
    source["name"] = source_name

    if source_type in {"csv", "excel"}:
        if "path" not in source:
            raise ConfigValidationError(f"Fuente '{source_name}': se requiere path para el tipo {source_type}.")
        if not isinstance(source["path"], str):
            raise ConfigValidationError(f"Fuente '{source_name}': path debe ser texto.")

        if not os.path.isabs(source["path"]):
            source["path"] = os.path.abspath(os.path.join(config["config_dir"], source["path"]))

    if source_type == "excel":
        source.setdefault("sheet_name", 0)

    if source_type in {"api", "rest"}:
        if "url" not in source:
            raise ConfigValidationError(f"Fuente '{source_name}': se requiere url para tipo api/rest.")
        source.setdefault("headers", {})
        source.setdefault("params", {})
        source.setdefault("data_key", None)
        source.setdefault("timeout", 30)
        source.setdefault("retry", {})
        source.setdefault("pagination", {})
        source.setdefault("rate_limit", {})

    if source_type == "database":
        if "query" not in source:
            raise ConfigValidationError(f"Fuente '{source_name}': se requiere query para tipo database.")
        connection_string = source.get("connection_string")
        connection_settings = source.get("connection") or {}
        if not connection_string:
            connection_settings = {
                **{k: config.get(k) for k in ["server", "database", "user", "password"]},
                **connection_settings,
            }
            if not connection_settings.get("server") or not connection_settings.get("database"):
                raise ConfigValidationError(
                    f"Fuente '{source_name}': se requiere connection_string o connection.server y connection.database."
                )
            source["connection_string"] = _build_sqlserver_connection_string(connection_settings, config)
        else:
            if not isinstance(connection_string, str):
                raise ConfigValidationError(f"Fuente '{source_name}': connection_string debe ser texto.")

    if source_type == "odoo":
        source.setdefault("connection", {})
        source.setdefault("object", None)
        source.setdefault("domain", None)
        source.setdefault("fields", [])

    source["incremental_column"] = source.get("incremental_column") or config.get("incremental_column")
    return source


def _build_sqlserver_connection_string(connection, config):
    driver = connection.get("driver", "ODBC Driver 17 for SQL Server")
    server = connection["server"]
    database = connection["database"]
    user = connection.get("user")
    password = connection.get("password")
    trusted = connection.get("trusted_connection", False)
    encrypt = connection.get("encrypt", config.get("encrypt", False))
    trust_server_certificate = connection.get(
        "trust_server_certificate", config.get("trust_server_certificate", not encrypt)
    )

    if trusted or (not user and not password):
        auth_segment = "Trusted_Connection=yes;"
    else:
        auth_segment = f"UID={user};PWD={password};"

    encrypt_segment = "Encrypt=yes;" if encrypt else "Encrypt=no;"
    trust_segment = (
        "TrustServerCertificate=yes;" if trust_server_certificate else "TrustServerCertificate=no;"
    )

    odbc_conn = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"{auth_segment}"
        f"{encrypt_segment}"
        f"{trust_segment}"
        "Connection Timeout=60;"
        "Login Timeout=60;"
        "ConnectRetryCount=3;"
        "ConnectRetryInterval=10;"
    )

    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_conn)}"


def _normalize_sources(config):
    sources = config.get("sources")
    if not sources or not isinstance(sources, list):
        raise ConfigValidationError("Se requiere una lista de sources en la configuración.")

    normalized = []
    for idx, source in enumerate(sources):
        normalized.append(_validate_source(source, idx, config))

    config["sources"] = normalized
    return config


def load_config(config_path):
    config = _load_yaml_file(config_path)
    _expand_env_vars(config)
    _normalize_environment(config)
    _normalize_connection_settings(config)
    _validate_root_config(config)
    _normalize_sources(config)
    return config


def _expand_env_vars(node):
    """Recursively expand environment variables in all string values of the config.

    Uses `os.path.expandvars`, so supports `$VAR` and `${VAR}` forms.
    Modifies the config in-place.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                _expand_env_vars(v)
            elif isinstance(v, str):
                node[k] = os.path.expandvars(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, (dict, list)):
                _expand_env_vars(v)
            elif isinstance(v, str):
                node[i] = os.path.expandvars(v)
