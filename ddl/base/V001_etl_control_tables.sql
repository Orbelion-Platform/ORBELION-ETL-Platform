-- =========================
-- ETL CONTROL TABLES
-- SINGLE DATABASE PER CLIENT
-- =========================

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dw')
    EXEC('CREATE SCHEMA dw');
GO

IF OBJECT_ID('dw.etl_files_processed', 'U') IS NULL
BEGIN
    CREATE TABLE dw.etl_files_processed (
        file_name NVARCHAR(255) NOT NULL,
        processed_date DATETIME2 NOT NULL
            CONSTRAINT df_etl_files_processed_date
            DEFAULT SYSDATETIME(),

        CONSTRAINT pk_etl_files_processed
            PRIMARY KEY (file_name)
    );
END;
GO

IF OBJECT_ID('dw.etl_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dw.etl_runs (
        run_id BIGINT IDENTITY(1,1) PRIMARY KEY,

        process_name NVARCHAR(100) NOT NULL,

        start_time DATETIME2 NOT NULL,
        end_time DATETIME2 NULL,

        status NVARCHAR(20) NOT NULL, -- RUNNING / SUCCESS / FAILED

        records_processed INT NULL,

        error_message NVARCHAR(MAX) NULL
    );
END;
GO

IF OBJECT_ID('dw.etl_watermark', 'U') IS NULL
BEGIN
    CREATE TABLE dw.etl_watermark (
        process_name NVARCHAR(100) NOT NULL,
        source_name NVARCHAR(100) NOT NULL
            CONSTRAINT df_etl_watermark_source
            DEFAULT '__default__',
        entity_name NVARCHAR(150) NOT NULL
            CONSTRAINT df_etl_watermark_entity
            DEFAULT '__default__',
        endpoint NVARCHAR(500) NOT NULL
            CONSTRAINT df_etl_watermark_endpoint
            DEFAULT '__default__',

        last_value NVARCHAR(255) NULL,
        updated_at DATETIME2 NOT NULL
            CONSTRAINT df_etl_watermark_updated_at
            DEFAULT SYSDATETIME(),

        CONSTRAINT pk_etl_watermark
            PRIMARY KEY (process_name, source_name, entity_name, endpoint)
    );
END;
GO

IF OBJECT_ID('dw.etl_watermark', 'U') IS NOT NULL
BEGIN
    IF COL_LENGTH('dw.etl_watermark', 'source_name') IS NULL
        ALTER TABLE dw.etl_watermark ADD source_name NVARCHAR(100) NOT NULL
            CONSTRAINT df_etl_watermark_source_existing DEFAULT '__default__';

    IF COL_LENGTH('dw.etl_watermark', 'entity_name') IS NULL
        ALTER TABLE dw.etl_watermark ADD entity_name NVARCHAR(150) NOT NULL
            CONSTRAINT df_etl_watermark_entity_existing DEFAULT '__default__';

    IF COL_LENGTH('dw.etl_watermark', 'endpoint') IS NULL
        ALTER TABLE dw.etl_watermark ADD endpoint NVARCHAR(500) NOT NULL
            CONSTRAINT df_etl_watermark_endpoint_existing DEFAULT '__default__';

    IF COL_LENGTH('dw.etl_watermark', 'updated_at') IS NULL
        ALTER TABLE dw.etl_watermark ADD updated_at DATETIME2 NOT NULL
            CONSTRAINT df_etl_watermark_updated_at_existing DEFAULT SYSDATETIME();

    IF EXISTS (
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dw'
          AND TABLE_NAME = 'etl_watermark'
          AND COLUMN_NAME = 'last_value'
          AND DATA_TYPE <> 'nvarchar'
    )
        ALTER TABLE dw.etl_watermark ALTER COLUMN last_value NVARCHAR(255) NULL;
END;
GO

-- =========================
-- INDEXES
-- =========================

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_etl_runs_process' AND object_id = OBJECT_ID('dw.etl_runs'))
    CREATE INDEX ix_etl_runs_process
    ON dw.etl_runs(process_name);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_etl_runs_status' AND object_id = OBJECT_ID('dw.etl_runs'))
    CREATE INDEX ix_etl_runs_status
    ON dw.etl_runs(status);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_etl_runs_start_time' AND object_id = OBJECT_ID('dw.etl_runs'))
    CREATE INDEX ix_etl_runs_start_time
    ON dw.etl_runs(start_time);
GO
