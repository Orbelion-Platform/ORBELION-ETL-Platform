import logging
import os
import re
import struct
import time
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL


AZURE_SQL_TRANSIENT_CODES = {
    "40197",  # Service error.
    "40501",  # Service busy/throttled.
    "40613",  # Database unavailable, including serverless resume.
    "49918",
    "49919",
    "49920",
}
TRANSIENT_CONNECTION_SQLSTATES = {"08001", "08S01", "HYT00", "HYT01"}
AUTHENTICATION_SQLSTATES = {"28000"}
AUTHENTICATION_NATIVE_CODES = {"18456"}
REPORTED_NATIVE_CODES = (
    AZURE_SQL_TRANSIENT_CODES
    | AUTHENTICATION_NATIVE_CODES
    | {"10053", "10054", "10060", "11001", "40615"}
)
SQLSTATE_EXACT_PATTERN = re.compile(r"^[A-Z0-9]{5}$")
SQLSTATE_BRACKET_PATTERN = re.compile(r"\[([A-Z0-9]{5})\]")
NATIVE_CODE_PATTERN = re.compile(r"\((-?\d{4,6})\)")
SQL_COPT_SS_ACCESS_TOKEN = 1256
logger = logging.getLogger(__name__)


def _sql_error_identifiers(exc):
    """Return value-free SQLSTATE and native-code identifiers from an exception."""
    original = getattr(exc, "orig", exc)
    args = tuple(str(arg) for arg in getattr(original, "args", (original,)))
    error_text = " ".join(args).upper()
    exact_values = [arg.strip().upper() for arg in args]
    sqlstates = set(SQLSTATE_BRACKET_PATTERN.findall(error_text))
    sqlstates.update(
        value for value in exact_values
        if SQLSTATE_EXACT_PATTERN.fullmatch(value) and value not in REPORTED_NATIVE_CODES
    )
    native_codes = set(NATIVE_CODE_PATTERN.findall(error_text)).intersection(
        REPORTED_NATIVE_CODES
    )
    native_codes.update(value for value in exact_values if value in REPORTED_NATIVE_CODES)
    return sorted(sqlstates), sorted(native_codes)


def _is_authentication_error(exc):
    sqlstates, native_codes = _sql_error_identifiers(exc)
    return bool(
        AUTHENTICATION_SQLSTATES.intersection(sqlstates)
        or AUTHENTICATION_NATIVE_CODES.intersection(native_codes)
    )


def _is_transient_azure_sql_error(exc):
    if _is_authentication_error(exc):
        return False
    sqlstates, native_codes = _sql_error_identifiers(exc)
    return bool(
        TRANSIENT_CONNECTION_SQLSTATES.intersection(sqlstates)
        or AZURE_SQL_TRANSIENT_CODES.intersection(native_codes)
    )


def _log_connection_failure(exc, attempt, attempts, retry_delay=None):
    sqlstates, native_codes = _sql_error_identifiers(exc)
    fields = {
        "attempt": attempt,
        "attempts": attempts,
        "sqlstate": ",".join(sqlstates) or "UNKNOWN",
        "native_code": ",".join(native_codes) or "UNKNOWN",
    }
    if retry_delay is None:
        logger.error(
            "Azure SQL connection failed attempt=%(attempt)s/%(attempts)s "
            "sqlstate=%(sqlstate)s native_code=%(native_code)s retry=false",
            fields,
        )
    else:
        fields["retry_delay"] = retry_delay
        logger.warning(
            "Azure SQL connection failed attempt=%(attempt)s/%(attempts)s "
            "sqlstate=%(sqlstate)s native_code=%(native_code)s "
            "retry=true retry_in_seconds=%(retry_delay)s",
            fields,
        )


def _connect_with_retry(dialect, connection_args, connection_params, attempts=8, backoff_seconds=10):
    """Open a DBAPI connection, retrying recognized transient Azure SQL errors."""
    for attempt in range(1, attempts + 1):
        try:
            return dialect.dbapi.connect(*connection_args, **connection_params)
        except Exception as exc:
            retryable = _is_transient_azure_sql_error(exc)
            if attempt == attempts or not retryable:
                _log_connection_failure(exc, attempt, attempts)
                raise
            retry_delay = backoff_seconds * attempt
            _log_connection_failure(exc, attempt, attempts, retry_delay=retry_delay)
            time.sleep(retry_delay)


AZURE_SQL_SCOPE = "https://database.windows.net/.default"


def _pack_access_token(token):
    encoded = token.encode("utf-16-le")
    return struct.pack(f"<I{len(encoded)}s", len(encoded), encoded)


def _default_azure_credential(managed_identity_client_id=None):
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ValueError(
            "Azure Active Directory SQL authentication requires azure-identity."
        ) from exc
    return DefaultAzureCredential(
        managed_identity_client_id=managed_identity_client_id
    )


def _register_connection_retry(engine, token_provider=None):
    def connect_with_retry(dialect, connection_record, connection_args, connection_params):
        params = dict(connection_params)
        if token_provider is not None:
            attrs_before = dict(params.get("attrs_before") or {})
            attrs_before[SQL_COPT_SS_ACCESS_TOKEN] = _pack_access_token(
                token_provider()
            )
            params["attrs_before"] = attrs_before
        return _connect_with_retry(dialect, connection_args, params)

    event.listen(engine, "do_connect", connect_with_retry)


def _azure_sql_token_struct(token):
    token_bytes = token.encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def get_engine(config):
    """Create a SQLAlchemy engine for SQL Server.

    Supports three authentication modes:
    - SQL username/password (legacy and local compatibility)
    - Windows integrated authentication for local DEV
    - Azure SQL access token for passwordless CI/CD workloads
    """

    server = config.get("server")
    database = config.get("database")
    if not server or not database:
        raise ValueError("SQL Server destination requires server and database.")

    user = config.get("user")
    password = config.get("password")
    authentication = (
        config.get("authentication")
        or os.getenv("SQL_AUTHENTICATION")
        or ""
    ).strip().lower()
    azure_ad = authentication == "azure_active_directory"

    driver = config.get("driver", "ODBC Driver 17 for SQL Server")
    application_intent = config.get("application_intent")
    application_name = config.get("application_name")

    optional_segments = ""
    if application_intent:
        optional_segments += f"ApplicationIntent={application_intent};"
    if application_name:
        optional_segments += f"APP={application_name};"

    connect_args = {}
    token_provider = None

    if authentication == "azure_access_token":
        token = (config.get("access_token") or os.getenv("AZURE_SQL_ACCESS_TOKEN") or "").strip()
        if not token:
            raise ValueError(
                "Azure SQL access-token authentication requires AZURE_SQL_ACCESS_TOKEN."
            )
        encrypt = "yes" if config.get("encrypt", True) else "no"
        trust_certificate = (
            "yes" if config.get("trust_server_certificate", False) else "no"
        )
    elif azure_ad:
        credential = _default_azure_credential(
            config.get("managed_identity_client_id")
        )
        token_provider = lambda: credential.get_token(AZURE_SQL_SCOPE).token
        encrypt = "yes" if config.get("encrypt", True) else "no"
        trust_certificate = (
            "yes" if config.get("trust_server_certificate", False) else "no"
        )

    if authentication in {"azure_access_token", "azure_active_directory"}:
        odbc_conn = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust_certificate};"
            f"{optional_segments}"
            "Connection Timeout=60;"
            "Login Timeout=60;"
            "ConnectRetryCount=3;"
            "ConnectRetryInterval=10;"
        )
        if authentication == "azure_access_token":
            connect_args = {
                "attrs_before": {
                    SQL_COPT_SS_ACCESS_TOKEN: _azure_sql_token_struct(token),
                }
            }
    elif user and password:
        encrypt = "yes" if config.get("encrypt", True) else "no"
        trust_certificate = (
            "yes" if config.get("trust_server_certificate", False) else "no"
        )
        odbc_conn = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust_certificate};"
            f"{optional_segments}"
            "Connection Timeout=60;"
            "Login Timeout=60;"
            "ConnectRetryCount=3;"
            "ConnectRetryInterval=10;"
        )
    else:
        encrypt = "yes" if config.get("encrypt", False) else "no"
        trust_certificate = (
            "yes" if config.get("trust_server_certificate", True) else "no"
        )
        odbc_conn = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust_certificate};"
            f"{optional_segments}"
            "Connection Timeout=60;"
            "Login Timeout=60;"
            "ConnectRetryCount=3;"
            "ConnectRetryInterval=10;"
        )

    conn = URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": quote_plus(odbc_conn)},
    )

    engine = create_engine(
        conn,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
        fast_executemany=True,
        connect_args=connect_args,
    )
    _register_connection_retry(engine, token_provider=token_provider)

    return engine
