-- ORBELION analytical contract 2.0 historical backfill.
--
-- The v2 migration intentionally preserved the previous facts as *_legacy
-- because their grains differ. This migration copies the compatible history
-- into the canonical v2 facts without deleting or retaining a runtime
-- dependency on the legacy tables.
--
-- Idempotency rules:
--   * gastos use the original source business key as gasto_id;
--   * inventory snapshots use a namespaced deterministic business key so a
--     stock.quant id cannot collide with a stock.move/valuation-layer id;
--   * existing v2 rows and their surrogate fact ids are never overwritten.

SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID('dw.fact_gastos_legacy', 'U') IS NOT NULL
       AND OBJECT_ID('dw.fact_gastos', 'U') IS NOT NULL
       AND COL_LENGTH('dw.fact_gastos_legacy', 'gasto_key') IS NOT NULL
       AND COL_LENGTH('dw.fact_gastos_legacy', 'proveedor_id') IS NOT NULL
       AND COL_LENGTH('dw.fact_gastos_legacy', 'categoria') IS NOT NULL
       AND COL_LENGTH('dw.fact_gastos_legacy', 'importe') IS NOT NULL
    BEGIN
        DECLARE @gastos_source TABLE (
            gasto_id NVARCHAR(100) NOT NULL PRIMARY KEY,
            proveedor_key INT NULL,
            gasto_key INT NULL,
            importe DECIMAL(18,4) NULL
        );
        DECLARE @gastos_inserted TABLE (
            gasto_id NVARCHAR(100) NOT NULL PRIMARY KEY,
            importe DECIMAL(18,4) NULL
        );
        DECLARE
            @gastos_legacy_count BIGINT,
            @gastos_legacy_sum DECIMAL(38,4),
            @gastos_v2_before_count BIGINT,
            @gastos_v2_before_sum DECIMAL(38,4),
            @gastos_expected_count BIGINT,
            @gastos_expected_sum DECIMAL(38,4),
            @gastos_inserted_count BIGINT,
            @gastos_inserted_sum DECIMAL(38,4),
            @gastos_v2_after_count BIGINT,
            @gastos_v2_after_sum DECIMAL(38,4),
            @gastos_coverage_count BIGINT;

        IF EXISTS (
            SELECT CONVERT(NVARCHAR(100), gasto_key)
            FROM dw.fact_gastos_legacy
            GROUP BY CONVERT(NVARCHAR(100), gasto_key)
            HAVING COUNT_BIG(*) > 1
        )
            THROW 51001, 'Legacy gastos contains duplicate business keys.', 1;

        IF EXISTS (
            SELECT 1
            FROM dw.fact_gastos_legacy AS legacy
            LEFT JOIN dw.dim_proveedor AS dimension
              ON dimension.proveedor_key = legacy.proveedor_id
            WHERE legacy.proveedor_id IS NOT NULL
              AND dimension.proveedor_key IS NULL
        )
            THROW 51007, 'Legacy gastos contains orphan proveedor surrogate keys.', 1;

        IF EXISTS (
            SELECT 1
            FROM dw.fact_gastos_legacy AS legacy
            LEFT JOIN dw.dim_gasto AS dimension
              ON dimension.categoria = legacy.categoria
            WHERE legacy.categoria IS NOT NULL
              AND dimension.gasto_key IS NULL
        )
            THROW 51008, 'Legacy gastos contains categories missing from dim_gasto.', 1;

        INSERT INTO @gastos_source (gasto_id, proveedor_key, gasto_key, importe)
        SELECT
            CONVERT(NVARCHAR(100), legacy.gasto_key),
            legacy.proveedor_id,
            dimension.gasto_key,
            legacy.importe
        FROM dw.fact_gastos_legacy AS legacy
        LEFT JOIN dw.dim_gasto AS dimension
          ON dimension.categoria = legacy.categoria;

        SELECT
            @gastos_legacy_count = COUNT_BIG(*),
            @gastos_legacy_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
        FROM @gastos_source;

        SELECT
            @gastos_v2_before_count = COUNT_BIG(*),
            @gastos_v2_before_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
        FROM dw.fact_gastos;

        SELECT
            @gastos_expected_count = COUNT_BIG(*),
            @gastos_expected_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), source.importe)), 0)
        FROM @gastos_source AS source
        LEFT JOIN dw.fact_gastos AS target
          ON target.gasto_id = source.gasto_id
        WHERE target.gasto_id IS NULL;

        MERGE dw.fact_gastos WITH (HOLDLOCK) AS target
        USING @gastos_source AS source
          ON target.gasto_id = source.gasto_id
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (
                gasto_id,
                fecha_key,
                proveedor_key,
                gasto_key,
                metodo_pago_key,
                importe,
                clasificacion_financiera,
                estado_pago
            )
            VALUES (
                source.gasto_id,
                NULL,
                source.proveedor_key,
                source.gasto_key,
                NULL,
                source.importe,
                'LEGACY_NO_CLASIFICADO',
                'LEGACY_NO_DEFINIDO'
            )
        OUTPUT inserted.gasto_id, inserted.importe
          INTO @gastos_inserted (gasto_id, importe);

        SELECT
            @gastos_inserted_count = COUNT_BIG(*),
            @gastos_inserted_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
        FROM @gastos_inserted;

        SELECT
            @gastos_v2_after_count = COUNT_BIG(*),
            @gastos_v2_after_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), importe)), 0)
        FROM dw.fact_gastos;

        SELECT @gastos_coverage_count = COUNT_BIG(*)
        FROM @gastos_source AS source
        INNER JOIN dw.fact_gastos AS target
          ON target.gasto_id = source.gasto_id;

        IF @gastos_inserted_count <> @gastos_expected_count
            THROW 51002, 'Gastos backfill inserted count does not reconcile.', 1;
        IF @gastos_inserted_sum <> @gastos_expected_sum
            THROW 51003, 'Gastos backfill inserted amount does not reconcile.', 1;
        IF @gastos_v2_after_count <> @gastos_v2_before_count + @gastos_inserted_count
            THROW 51004, 'Gastos target count does not reconcile.', 1;
        IF @gastos_v2_after_sum <> @gastos_v2_before_sum + @gastos_inserted_sum
            THROW 51005, 'Gastos target amount does not reconcile.', 1;
        IF @gastos_coverage_count <> @gastos_legacy_count
            THROW 51006, 'Gastos legacy business-key coverage is incomplete.', 1;

        PRINT CONCAT(
            'GASTOS_RECONCILIATION legacy_count=', @gastos_legacy_count,
            ' legacy_sum=', @gastos_legacy_sum,
            ' v2_before_count=', @gastos_v2_before_count,
            ' v2_before_sum=', @gastos_v2_before_sum,
            ' inserted_count=', @gastos_inserted_count,
            ' inserted_sum=', @gastos_inserted_sum,
            ' v2_after_count=', @gastos_v2_after_count,
            ' v2_after_sum=', @gastos_v2_after_sum
        );
    END;

    IF OBJECT_ID('dw.fact_inventario_legacy', 'U') IS NOT NULL
       AND OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'inventario_key') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'producto_id') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'cantidad') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'valor') IS NOT NULL
    BEGIN
        DECLARE @inventario_source TABLE (
            inventario_movimiento_id NVARCHAR(100) NOT NULL PRIMARY KEY,
            inventario_id NVARCHAR(100) NULL,
            producto_key INT NULL,
            tipo_movimiento NVARCHAR(50) NOT NULL,
            cantidad DECIMAL(18,4) NULL,
            costo_unitario DECIMAL(18,4) NULL,
            valor DECIMAL(18,4) NULL
        );
        DECLARE @inventario_inserted TABLE (
            inventario_movimiento_id NVARCHAR(100) NOT NULL PRIMARY KEY,
            valor DECIMAL(18,4) NULL
        );
        DECLARE @inventario_repairs TABLE (
            valor_anterior DECIMAL(18,4) NULL,
            valor_nuevo DECIMAL(18,4) NULL
        );
        DECLARE
            @inventario_legacy_count BIGINT,
            @inventario_legacy_sum DECIMAL(38,4),
            @inventario_v2_before_count BIGINT,
            @inventario_v2_before_sum DECIMAL(38,4),
            @inventario_expected_count BIGINT,
            @inventario_expected_sum DECIMAL(38,4),
            @inventario_inserted_count BIGINT,
            @inventario_inserted_sum DECIMAL(38,4),
            @inventario_repaired_count BIGINT,
            @inventario_repair_delta DECIMAL(38,4),
            @inventario_v2_after_count BIGINT,
            @inventario_v2_after_sum DECIMAL(38,4),
            @inventario_coverage_count BIGINT,
            @inventario_unvalued_after BIGINT;

        IF EXISTS (
            SELECT 1
            FROM dw.fact_inventario_legacy AS legacy
            LEFT JOIN dw.dim_producto_servicio AS dimension
              ON dimension.producto_key = legacy.producto_id
            WHERE legacy.producto_id IS NOT NULL
              AND dimension.producto_key IS NULL
        )
            THROW 51016, 'Legacy inventory contains orphan producto surrogate keys.', 1;

        INSERT INTO @inventario_source (
            inventario_movimiento_id,
            inventario_id,
            producto_key,
            tipo_movimiento,
            cantidad,
            costo_unitario,
            valor
        )
        SELECT
            CASE
                WHEN LEN(CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))) <= 100
                    THEN CONCAT('legacy_quant:', CONVERT(NVARCHAR(100), legacy.inventario_key))
                ELSE CONCAT(
                    'legacy_quant_sha256:',
                    LOWER(CONVERT(VARCHAR(64), HASHBYTES(
                        'SHA2_256',
                        CONVERT(VARBINARY(MAX), CONVERT(NVARCHAR(100), legacy.inventario_key))
                    ), 2))
                )
            END,
            CONVERT(NVARCHAR(100), legacy.inventario_key),
            legacy.producto_id,
            CASE
                WHEN COALESCE(legacy.cantidad, 0) = 0 THEN 'AJUSTE_VALOR_LEGACY'
                WHEN legacy.cantidad < 0 THEN 'SALDO_INICIAL_NEGATIVO_LEGACY'
                ELSE 'SALDO_INICIAL_LEGACY'
            END,
            ABS(legacy.cantidad),
            CASE
                WHEN NULLIF(ABS(legacy.cantidad), 0) IS NOT NULL
                     AND NULLIF(ABS(legacy.valor), 0) IS NOT NULL
                    THEN ABS(legacy.valor) / ABS(legacy.cantidad)
                ELSE NULL
            END,
            legacy.valor
        FROM dw.fact_inventario_legacy AS legacy;

        SELECT
            @inventario_legacy_count = COUNT_BIG(*),
            @inventario_legacy_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM @inventario_source;

        SELECT
            @inventario_v2_before_count = COUNT_BIG(*),
            @inventario_v2_before_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM dw.fact_inventario;

        SELECT
            @inventario_expected_count = COUNT_BIG(*),
            @inventario_expected_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), source.valor)), 0)
        FROM @inventario_source AS source
        LEFT JOIN dw.fact_inventario AS target
          ON target.inventario_movimiento_id = source.inventario_movimiento_id
        WHERE target.inventario_movimiento_id IS NULL;

        MERGE dw.fact_inventario WITH (HOLDLOCK) AS target
        USING @inventario_source AS source
          ON target.inventario_movimiento_id = source.inventario_movimiento_id
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (
                inventario_movimiento_id,
                inventario_id,
                fecha_key,
                producto_key,
                tipo_movimiento,
                cantidad,
                costo_unitario,
                valor
            )
            VALUES (
                source.inventario_movimiento_id,
                source.inventario_id,
                NULL,
                source.producto_key,
                source.tipo_movimiento,
                source.cantidad,
                source.costo_unitario,
                source.valor
            )
        OUTPUT inserted.inventario_movimiento_id, inserted.valor
          INTO @inventario_inserted (inventario_movimiento_id, valor);

        -- Repair only values that are mathematically recoverable from the same
        -- movement. Rows with neither value nor cost remain NULL/zero and are
        -- reported for source-side remediation rather than guessed.
        UPDATE target
        SET
            costo_unitario = CASE
                WHEN COALESCE(target.costo_unitario, 0) = 0
                     AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
                     AND NULLIF(ABS(target.valor), 0) IS NOT NULL
                    THEN ABS(target.valor) / ABS(target.cantidad)
                ELSE target.costo_unitario
            END,
            valor = CASE
                WHEN COALESCE(target.valor, 0) = 0
                     AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
                     AND NULLIF(ABS(target.costo_unitario), 0) IS NOT NULL
                    THEN ABS(target.cantidad) * ABS(target.costo_unitario)
                ELSE target.valor
            END
        OUTPUT deleted.valor, inserted.valor
          INTO @inventario_repairs (valor_anterior, valor_nuevo)
        FROM dw.fact_inventario AS target
        WHERE (
            COALESCE(target.costo_unitario, 0) = 0
            AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
            AND NULLIF(ABS(target.valor), 0) IS NOT NULL
        ) OR (
            COALESCE(target.valor, 0) = 0
            AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
            AND NULLIF(ABS(target.costo_unitario), 0) IS NOT NULL
        );

        SELECT
            @inventario_inserted_count = COUNT_BIG(*),
            @inventario_inserted_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM @inventario_inserted;

        SELECT
            @inventario_repaired_count = COUNT_BIG(*),
            @inventario_repair_delta = COALESCE(SUM(
                CONVERT(DECIMAL(38,4), COALESCE(valor_nuevo, 0))
                - CONVERT(DECIMAL(38,4), COALESCE(valor_anterior, 0))
            ), 0)
        FROM @inventario_repairs;

        SELECT
            @inventario_v2_after_count = COUNT_BIG(*),
            @inventario_v2_after_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM dw.fact_inventario;

        SELECT @inventario_coverage_count = COUNT_BIG(*)
        FROM @inventario_source AS source
        INNER JOIN dw.fact_inventario AS target
          ON target.inventario_movimiento_id = source.inventario_movimiento_id;

        SELECT @inventario_unvalued_after = COUNT_BIG(*)
        FROM dw.fact_inventario
        WHERE NULLIF(ABS(cantidad), 0) IS NOT NULL
          AND (COALESCE(costo_unitario, 0) = 0 OR COALESCE(valor, 0) = 0);

        IF @inventario_inserted_count <> @inventario_expected_count
            THROW 51011, 'Inventory backfill inserted count does not reconcile.', 1;
        IF @inventario_inserted_sum <> @inventario_expected_sum
            THROW 51012, 'Inventory backfill inserted value does not reconcile.', 1;
        IF @inventario_v2_after_count <> @inventario_v2_before_count + @inventario_inserted_count
            THROW 51013, 'Inventory target count does not reconcile.', 1;
        IF @inventario_v2_after_sum <> @inventario_v2_before_sum + @inventario_inserted_sum + @inventario_repair_delta
            THROW 51014, 'Inventory target value does not reconcile.', 1;
        IF @inventario_coverage_count <> @inventario_legacy_count
            THROW 51015, 'Inventory legacy business-key coverage is incomplete.', 1;

        PRINT CONCAT(
            'INVENTORY_RECONCILIATION legacy_count=', @inventario_legacy_count,
            ' legacy_sum=', @inventario_legacy_sum,
            ' v2_before_count=', @inventario_v2_before_count,
            ' v2_before_sum=', @inventario_v2_before_sum,
            ' inserted_count=', @inventario_inserted_count,
            ' inserted_sum=', @inventario_inserted_sum,
            ' repaired_count=', @inventario_repaired_count,
            ' repair_delta=', @inventario_repair_delta,
            ' v2_after_count=', @inventario_v2_after_count,
            ' v2_after_sum=', @inventario_v2_after_sum,
            ' unresolved_valuation_rows=', @inventario_unvalued_after
        );

    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
