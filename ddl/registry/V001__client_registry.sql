SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF SCHEMA_ID('control') IS NULL
    EXEC('CREATE SCHEMA control AUTHORIZATION dbo');

IF OBJECT_ID('control.client_registry', 'U') IS NULL
BEGIN
    CREATE TABLE control.client_registry (
        client_id VARCHAR(50) NOT NULL,
        enabled BIT NOT NULL CONSTRAINT df_client_registry_enabled DEFAULT (1),
        etl_enabled BIT NOT NULL CONSTRAINT df_client_registry_etl_enabled DEFAULT (0),
        source_type VARCHAR(30) NOT NULL,
        server_name NVARCHAR(253) NOT NULL,
        database_name SYSNAME NOT NULL,
        auth_mode VARCHAR(30) NOT NULL,
        credential_reference VARCHAR(100) NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT df_client_registry_created_at DEFAULT (SYSUTCDATETIME()),
        updated_at DATETIME2(0) NOT NULL CONSTRAINT df_client_registry_updated_at DEFAULT (SYSUTCDATETIME()),
        registry_version ROWVERSION NOT NULL,
        CONSTRAINT pk_client_registry PRIMARY KEY (client_id),
        CONSTRAINT ck_client_registry_client_id CHECK (
            client_id = LOWER(client_id)
            AND client_id NOT LIKE '%[^a-z0-9_]%'
            AND client_id LIKE '[a-z]%'
            AND LEN(client_id) BETWEEN 3 AND 50
        ),
        CONSTRAINT ck_client_registry_source_type CHECK (source_type IN ('azure_sql')),
        CONSTRAINT ck_client_registry_auth_mode CHECK (
            (auth_mode = 'managed_identity' AND credential_reference IS NULL)
            OR
            (auth_mode = 'key_vault_secret' AND credential_reference IS NOT NULL)
        ),
        CONSTRAINT ck_client_registry_credential_reference CHECK (
            credential_reference IS NULL
            OR (
                credential_reference = LOWER(credential_reference)
                AND credential_reference NOT LIKE '%[^a-z0-9-]%'
                AND LEN(credential_reference) BETWEEN 3 AND 100
            )
        )
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID('control.client_registry')
      AND name = 'ix_client_registry_enabled_etl'
)
BEGIN
    CREATE INDEX ix_client_registry_enabled_etl
        ON control.client_registry (enabled, etl_enabled, client_id)
        INCLUDE (source_type, auth_mode);
END;

COMMIT TRANSACTION;
