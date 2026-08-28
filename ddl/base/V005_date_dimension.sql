-- Standard calendar dimension shared by every ORBELION client warehouse.
-- Additive and idempotent: existing dates are preserved and missing dates are inserted.

IF OBJECT_ID('dw.dim_fecha', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_fecha (
        fecha_id INT IDENTITY(1,1) NOT NULL
            CONSTRAINT pk_dim_fecha PRIMARY KEY,
        fecha DATE NOT NULL,
        ano INT NOT NULL,
        mes INT NOT NULL,
        dia INT NOT NULL,
        trimestre INT NOT NULL
    );
END;
GO

IF EXISTS (
    SELECT fecha
    FROM dw.dim_fecha
    GROUP BY fecha
    HAVING COUNT_BIG(*) > 1
)
BEGIN
    ;THROW 51000, 'dw.dim_fecha contains duplicate dates; repair them before migration.', 1;
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID('dw.dim_fecha')
      AND name = 'ux_dim_fecha_fecha'
)
    CREATE UNIQUE INDEX ux_dim_fecha_fecha ON dw.dim_fecha(fecha);
GO

DECLARE @start_date DATE = '20100101';
DECLARE @end_date DATE = DATEFROMPARTS(YEAR(SYSUTCDATETIME()) + 5, 12, 31);

WITH date_offsets AS (
    SELECT TOP (DATEDIFF(DAY, @start_date, @end_date) + 1)
        CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS INT) AS day_offset
    FROM sys.all_objects AS a
    CROSS JOIN sys.all_objects AS b
),
calendar AS (
    SELECT DATEADD(DAY, day_offset, @start_date) AS fecha
    FROM date_offsets
)
MERGE dw.dim_fecha WITH (HOLDLOCK) AS target
USING (
    SELECT
        fecha,
        YEAR(fecha) AS ano,
        MONTH(fecha) AS mes,
        DAY(fecha) AS dia,
        DATEPART(QUARTER, fecha) AS trimestre
    FROM calendar
) AS source
ON target.fecha = source.fecha
WHEN MATCHED AND (
    target.ano <> source.ano
    OR target.mes <> source.mes
    OR target.dia <> source.dia
    OR target.trimestre <> source.trimestre
) THEN UPDATE SET
    ano = source.ano,
    mes = source.mes,
    dia = source.dia,
    trimestre = source.trimestre
WHEN NOT MATCHED THEN INSERT (fecha, ano, mes, dia, trimestre)
    VALUES (source.fecha, source.ano, source.mes, source.dia, source.trimestre);
GO
