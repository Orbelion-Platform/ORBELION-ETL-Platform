-- Read-only reconciliation for the analytical contract v2 backfill.
-- Run this script before and after V003__backfill_legacy_facts_v2.sql and
-- retain both result sets with the deployment evidence.

SET NOCOUNT ON;

CREATE TABLE #fact_metrics (
    fact_name NVARCHAR(100) NOT NULL,
    data_set NVARCHAR(50) NOT NULL,
    row_count BIGINT NOT NULL,
    amount_name NVARCHAR(50) NOT NULL,
    amount_sum DECIMAL(38,4) NOT NULL
);

CREATE TABLE #coverage_metrics (
    fact_name NVARCHAR(100) NOT NULL,
    metric_name NVARCHAR(100) NOT NULL,
    metric_value DECIMAL(38,4) NOT NULL
);

CREATE TABLE #movement_metrics (
    tipo_movimiento NVARCHAR(50) NOT NULL,
    row_count BIGINT NOT NULL,
    valor_sum DECIMAL(38,4) NOT NULL
);

IF OBJECT_ID('dw.fact_gastos_legacy', 'U') IS NOT NULL
BEGIN
    INSERT INTO #fact_metrics
    SELECT
        'fact_gastos',
        'legacy',
        COUNT_BIG(*),
        'importe',
        COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
    FROM dw.fact_gastos_legacy;
END;

IF OBJECT_ID('dw.fact_gastos', 'U') IS NOT NULL
BEGIN
    INSERT INTO #fact_metrics
    SELECT
        'fact_gastos',
        'v2',
        COUNT_BIG(*),
        'importe',
        COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
    FROM dw.fact_gastos;
END;

IF OBJECT_ID('dw.fact_gastos_legacy', 'U') IS NOT NULL
   AND OBJECT_ID('dw.fact_gastos', 'U') IS NOT NULL
BEGIN
    INSERT INTO #coverage_metrics
    SELECT
        'fact_gastos',
        'legacy_keys_present_in_v2',
        COUNT_BIG(*)
    FROM dw.fact_gastos_legacy AS legacy
    INNER JOIN dw.fact_gastos AS target
      ON target.gasto_id = CONVERT(NVARCHAR(100), legacy.gasto_key);

    INSERT INTO #coverage_metrics
    SELECT
        'fact_gastos',
        'legacy_orphan_proveedor_keys',
        COUNT_BIG(*)
    FROM dw.fact_gastos_legacy AS legacy
    LEFT JOIN dw.dim_proveedor AS dimension
      ON dimension.proveedor_key = legacy.proveedor_id
    WHERE legacy.proveedor_id IS NOT NULL
      AND dimension.proveedor_key IS NULL;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_gastos',
        'legacy_categories_missing_in_dim_gasto',
        COUNT_BIG(*)
    FROM dw.fact_gastos_legacy AS legacy
    LEFT JOIN dw.dim_gasto AS dimension
      ON dimension.categoria = legacy.categoria
    WHERE legacy.categoria IS NOT NULL
      AND dimension.gasto_key IS NULL;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_gastos',
        'legacy_keys_missing_in_v2',
        COUNT_BIG(*)
    FROM dw.fact_gastos_legacy AS legacy
    LEFT JOIN dw.fact_gastos AS target
      ON target.gasto_id = CONVERT(NVARCHAR(100), legacy.gasto_key)
    WHERE target.gasto_id IS NULL;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_gastos',
        'overlap_importe_delta_v2_minus_legacy',
        COALESCE(SUM(
            CONVERT(DECIMAL(38,4), COALESCE(target.importe, 0))
            - CONVERT(DECIMAL(38,4), COALESCE(legacy.importe, 0))
        ), 0)
    FROM dw.fact_gastos_legacy AS legacy
    INNER JOIN dw.fact_gastos AS target
      ON target.gasto_id = CONVERT(NVARCHAR(100), legacy.gasto_key);
END;

IF OBJECT_ID('dw.fact_inventario_legacy', 'U') IS NOT NULL
BEGIN
    INSERT INTO #fact_metrics
    SELECT
        'fact_inventario',
        'legacy',
        COUNT_BIG(*),
        'valor',
        COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
    FROM dw.fact_inventario_legacy;
END;

IF OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
BEGIN
    INSERT INTO #fact_metrics
    SELECT
        'fact_inventario',
        'v2',
        COUNT_BIG(*),
        'valor',
        COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
    FROM dw.fact_inventario;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'rows_with_quantity_without_valuation',
        COUNT_BIG(*)
    FROM dw.fact_inventario
    WHERE NULLIF(ABS(cantidad), 0) IS NOT NULL
      AND (COALESCE(costo_unitario, 0) = 0 OR COALESCE(valor, 0) = 0);

    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'native_rows_with_quantity_without_valuation',
        COUNT_BIG(*)
    FROM dw.fact_inventario
    WHERE inventario_movimiento_id NOT LIKE 'legacy_quant:%'
      AND inventario_movimiento_id NOT LIKE 'legacy_quant_sha256:%'
      AND NULLIF(ABS(cantidad), 0) IS NOT NULL
      AND (COALESCE(costo_unitario, 0) = 0 OR COALESCE(valor, 0) = 0);

    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'native_inventory_value_sum',
        COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
    FROM dw.fact_inventario
    WHERE inventario_movimiento_id NOT LIKE 'legacy_quant:%'
      AND inventario_movimiento_id NOT LIKE 'legacy_quant_sha256:%';

    INSERT INTO #movement_metrics
    SELECT
        tipo_movimiento,
        COUNT_BIG(*),
        COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
    FROM dw.fact_inventario
    GROUP BY tipo_movimiento;
END;

IF OBJECT_ID('dw.fact_inventario_legacy', 'U') IS NOT NULL
   AND OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
BEGIN
    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'legacy_orphan_producto_keys',
        COUNT_BIG(*)
    FROM dw.fact_inventario_legacy AS legacy
    LEFT JOIN dw.dim_producto_servicio AS dimension
      ON dimension.producto_key = legacy.producto_id
    WHERE legacy.producto_id IS NOT NULL
      AND dimension.producto_key IS NULL;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'legacy_snapshots_present_in_v2',
        COUNT_BIG(*)
    FROM dw.fact_inventario_legacy AS legacy
    INNER JOIN dw.fact_inventario AS target
      ON target.inventario_movimiento_id = CASE
          WHEN LEN(CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))) <= 100
              THEN CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))
          ELSE CONCAT(
              'legacy_quant_sha256:',
              LOWER(CONVERT(VARCHAR(64), HASHBYTES(
                  'SHA2_256',
                  CONVERT(VARBINARY(MAX), CONVERT(NVARCHAR(100), legacy.inventario_key))
              ), 2))
          )
      END;

    INSERT INTO #coverage_metrics
    SELECT
        'fact_inventario',
        'legacy_snapshots_missing_in_v2',
        COUNT_BIG(*)
    FROM dw.fact_inventario_legacy AS legacy
    LEFT JOIN dw.fact_inventario AS target
      ON target.inventario_movimiento_id = CASE
          WHEN LEN(CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))) <= 100
              THEN CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))
          ELSE CONCAT(
              'legacy_quant_sha256:',
              LOWER(CONVERT(VARCHAR(64), HASHBYTES(
                  'SHA2_256',
                  CONVERT(VARBINARY(MAX), CONVERT(NVARCHAR(100), legacy.inventario_key))
              ), 2))
          )
      END
    WHERE target.inventario_movimiento_id IS NULL;
END;

SELECT fact_name, data_set, row_count, amount_name, amount_sum
FROM #fact_metrics
ORDER BY fact_name, data_set;

SELECT fact_name, metric_name, metric_value
FROM #coverage_metrics
ORDER BY fact_name, metric_name;

SELECT tipo_movimiento, row_count, valor_sum
FROM #movement_metrics
ORDER BY tipo_movimiento;
