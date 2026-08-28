import logging
import struct
from urllib.parse import unquote_plus
from types import SimpleNamespace

from etl_platform.core.config import load_config
from etl_platform.core.db import connection


def _write_config(tmp_path):
    config = tmp_path / "prod.yaml"
    config.write_text(
        """
environment: prod
process_name: test_azure
server: ${TEST_SQL_SERVER}
database: ${TEST_SQL_DATABASE}
user: ${TEST_SQL_USER}
password: ${TEST_SQL_PASSWORD}
driver: ODBC Driver 18 for SQL Server
sources:
  - name: source
    type: odoo
    connection: {}
""",
        encoding="utf-8",
    )
    return config


def test_azure_sql_credentials_are_read_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_SQL_SERVER", "server.database.windows.net")
    monkeypatch.setenv("TEST_SQL_DATABASE", "warehouse")
    monkeypatch.setenv("TEST_SQL_USER", "etl-user")
    monkeypatch.setenv("TEST_SQL_PASSWORD", "special;password")

    config = load_config(_write_config(tmp_path))

    assert config["server"] == "server.database.windows.net"
    assert config["database"] == "warehouse"
    assert config["user"] == "etl-user"
    assert config["password"] == "special;password"
    assert config["encrypt"] is True
    assert config["trust_server_certificate"] is False


def test_engine_build_isolated_from_sql(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return object()

    monkeypatch.setattr(connection, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        connection.event,
        "listen",
        lambda engine, event_name, listener: captured.update(event_name=event_name),
    )
    result = connection.get_engine(
        {
            "server": "server.database.windows.net",
            "database": "warehouse",
            "user": "etl-user",
            "password": "secret",
            "driver": "ODBC Driver 18 for SQL Server",
            "encrypt": True,
            "trust_server_certificate": False,
        }
    )

    odbc = unquote_plus(captured["url"].query["odbc_connect"])
    assert result is not None
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in odbc
    assert "Encrypt=yes" in odbc
    assert "TrustServerCertificate=no" in odbc
    assert "Connection Timeout=60" in odbc
    assert "Login Timeout=60" in odbc
    assert "ConnectRetryCount=3" in odbc
    assert "ConnectRetryInterval=10" in odbc
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["event_name"] == "do_connect"


def test_engine_supports_azure_sql_access_token(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return object()

    monkeypatch.setenv("SQL_AUTHENTICATION", "azure_access_token")
    monkeypatch.setenv("AZURE_SQL_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(connection, "create_engine", fake_create_engine)
    monkeypatch.setattr(connection.event, "listen", lambda *args, **kwargs: None)

    connection.get_engine(
        {
            "server": "server.database.windows.net",
            "database": "warehouse",
            "user": "legacy-user-is-ignored",
            "password": "legacy-password-is-ignored",
            "driver": "ODBC Driver 18 for SQL Server",
        }
    )

    odbc = unquote_plus(captured["url"].query["odbc_connect"])
    attrs_before = captured["kwargs"]["connect_args"]["attrs_before"]

    assert "UID=" not in odbc
    assert "PWD=" not in odbc
    assert "Trusted_Connection" not in odbc
    assert "Encrypt=yes" in odbc
    assert "TrustServerCertificate=no" in odbc
    assert connection.SQL_COPT_SS_ACCESS_TOKEN in attrs_before


def test_engine_requires_token_for_azure_sql_auth(monkeypatch):
    monkeypatch.setenv("SQL_AUTHENTICATION", "azure_access_token")
    monkeypatch.delenv("AZURE_SQL_ACCESS_TOKEN", raising=False)

    try:
        connection.get_engine(
            {
                "server": "server.database.windows.net",
                "database": "warehouse",
            }
        )
    except ValueError as exc:
        assert "AZURE_SQL_ACCESS_TOKEN" in str(exc)
    else:
        raise AssertionError("missing Azure SQL token should fail closed")


def test_engine_supports_passwordless_azure_sql_with_fresh_access_tokens(monkeypatch):
    captured = {}

    class FakeCredential:
        def get_token(self, scope):
            captured["scope"] = scope
            return SimpleNamespace(token="access-token")

    class FakeDbApi:
        def connect(self, *args, **kwargs):
            captured["connection_params"] = kwargs
            return "connected"

    monkeypatch.setattr(connection, "create_engine", lambda url, **kwargs: captured.setdefault("engine", object()))
    monkeypatch.setattr(
        connection,
        "_default_azure_credential",
        lambda client_id=None: captured.update(client_id=client_id) or FakeCredential(),
    )
    monkeypatch.setattr(
        connection.event,
        "listen",
        lambda engine, event_name, listener: captured.update(listener=listener),
    )

    connection.get_engine({
        "server": "server.database.windows.net",
        "database": "warehouse",
        "driver": "ODBC Driver 18 for SQL Server",
        "authentication": "azure_active_directory",
        "managed_identity_client_id": "managed-identity-client-id",
        "encrypt": True,
        "trust_server_certificate": False,
    })
    result = captured["listener"](
        SimpleNamespace(dbapi=FakeDbApi()), None, (), {}
    )

    expected = "access-token".encode("utf-16-le")
    packed = captured["connection_params"]["attrs_before"][
        connection.SQL_COPT_SS_ACCESS_TOKEN
    ]
    assert result == "connected"
    assert captured["client_id"] == "managed-identity-client-id"
    assert captured["scope"] == connection.AZURE_SQL_SCOPE
    assert packed == struct.pack(f"<I{len(expected)}s", len(expected), expected)


class _FakeDbApi:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    def connect(self, *args, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "connected"


class _FakeDialect:
    def __init__(self, failures):
        self.dbapi = _FakeDbApi(failures)


def test_connection_retries_serverless_database_resume(monkeypatch):
    dialect = _FakeDialect([RuntimeError("40613"), RuntimeError("40613")])
    sleeps = []
    monkeypatch.setattr(connection.time, "sleep", sleeps.append)

    result = connection._connect_with_retry(
        dialect,
        connection_args=(),
        connection_params={},
        attempts=3,
        backoff_seconds=2,
    )

    assert result == "connected"
    assert dialect.dbapi.calls == 3
    assert sleeps == [2, 4]


def test_connection_does_not_retry_authentication_failure(monkeypatch):
    dialect = _FakeDialect([RuntimeError("18456")])
    monkeypatch.setattr(
        connection.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    try:
        connection._connect_with_retry(dialect, (), {}, attempts=5)
    except RuntimeError as exc:
        assert str(exc) == "18456"
    else:
        raise AssertionError("authentication failure should propagate")

    assert dialect.dbapi.calls == 1


def test_connection_retries_timeout_sqlstates_without_logging_values(monkeypatch, caplog):
    secret_marker = "must-not-appear"
    dialect = _FakeDialect([
        RuntimeError(
            "HYT00",
            f"connection timeout server={secret_marker} password={secret_marker} (10060)",
        )
    ])
    monkeypatch.setattr(connection.time, "sleep", lambda seconds: None)

    with caplog.at_level(logging.WARNING, logger=connection.__name__):
        result = connection._connect_with_retry(
            dialect,
            connection_args=(),
            connection_params={},
            attempts=2,
            backoff_seconds=1,
        )

    assert result == "connected"
    assert "sqlstate=HYT00" in caplog.text
    assert "native_code=10060" in caplog.text
    assert "retry=true" in caplog.text
    assert secret_marker not in caplog.text


def test_connection_does_not_retry_authentication_sqlstate(monkeypatch, caplog):
    secret_marker = "must-not-appear"
    dialect = _FakeDialect([
        RuntimeError("28000", f"login failed user={secret_marker} (18456)")
    ])
    monkeypatch.setattr(
        connection.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    with caplog.at_level(logging.ERROR, logger=connection.__name__):
        try:
            connection._connect_with_retry(dialect, (), {}, attempts=5)
        except RuntimeError:
            pass
        else:
            raise AssertionError("authentication failure should propagate")

    assert dialect.dbapi.calls == 1
    assert "sqlstate=28000" in caplog.text
    assert "native_code=18456" in caplog.text
    assert "retry=false" in caplog.text
    assert secret_marker not in caplog.text


def test_connection_reports_firewall_code_without_retrying(monkeypatch, caplog):
    secret_marker = "must-not-appear"
    dialect = _FakeDialect([
        RuntimeError(
            "42000",
            f"client IP address {secret_marker} is not allowed to access server (40615)",
        )
    ])
    monkeypatch.setattr(
        connection.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    with caplog.at_level(logging.ERROR, logger=connection.__name__):
        try:
            connection._connect_with_retry(dialect, (), {}, attempts=5)
        except RuntimeError:
            pass
        else:
            raise AssertionError("firewall failure should propagate")

    assert dialect.dbapi.calls == 1
    assert "sqlstate=42000" in caplog.text
    assert "native_code=40615" in caplog.text
    assert "retry=false" in caplog.text
    assert secret_marker not in caplog.text
