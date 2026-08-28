-- Repair valuation for native analytical-v2 inventory movements.
--
-- stock.valuation.layer is not exposed by every Odoo edition. Where the
-- source fell back to stock.move, price_unit can be zero. This one-time,
-- idempotent migration derives a weighted product reference cost from the
-- preserved legacy stock.quant snapshot and writes it into the canonical v2
-- fact. The legacy table is not queried by runtime ETL after this migration.
-- Existing business keys, fact surrogate keys, dates and relationships are
-- preserved. Legacy snapshot rows are deliberately not modified.

SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID('dw.fact_inventario_legacy', 'U') IS NOT NULL
       AND OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'producto_id') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'cantidad') IS NOT NULL
       AND COL_LENGTH('dw.fact_inventario_legacy', 'valor') IS NOT NULL
    BEGIN
        DECLARE @product_cost TABLE (
            producto_key INT NOT NULL PRIMARY KEY,
            costo_unitario DECIMAL(38,10) NOT NULL
        );
        DECLARE @repairs TABLE (
            fact_id_before BIGINT NOT NULL,
            fact_id_after BIGINT NOT NULL,
            valor_before DECIMAL(18,4) NULL,
            valor_after DECIMAL(18,4) NULL
        );
        DECLARE
            @before_count BIGINT,
            @before_sum DECIMAL(38,4),
            @expected_repairs BIGINT,
            @repaired_count BIGINT,
            @repair_delta DECIMAL(38,4),
            @after_count BIGINT,
            @after_sum DECIMAL(38,4),
            @unresolved_native BIGINT;

        INSERT INTO @product_cost (producto_key, costo_unitario)
        SELECT
            legacy.producto_id,
            SUM(CONVERT(DECIMAL(38,10), ABS(legacy.valor)))
                / NULLIF(SUM(CONVERT(DECIMAL(38,10), ABS(legacy.cantidad))), 0)
        FROM dw.fact_inventario_legacy AS legacy
        WHERE legacy.producto_id IS NOT NULL
          AND NULLIF(ABS(legacy.cantidad), 0) IS NOT NULL
          AND NULLIF(ABS(legacy.valor), 0) IS NOT NULL
        GROUP BY legacy.producto_id;

        SELECT
            @before_count = COUNT_BIG(*),
            @before_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM dw.fact_inventario;

        SELECT @expected_repairs = COUNT_BIG(*)
        FROM dw.fact_inventario AS target
        INNER JOIN @product_cost AS reference
          ON reference.producto_key = target.producto_key
        WHERE target.inventario_movimiento_id NOT LIKE 'legacy_quant:%'
          AND target.inventario_movimiento_id NOT LIKE 'legacy_quant_sha256:%'
          AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
          AND (
              COALESCE(target.costo_unitario, 0) = 0
              OR COALESCE(target.valor, 0) = 0
          );

        UPDATE target
        SET
            costo_unitario = COALESCE(
                NULLIF(ABS(target.costo_unitario), 0),
                reference.costo_unitario
            ),
            valor = CASE
                WHEN COALESCE(target.valor, 0) = 0
                    THEN ABS(target.cantidad) * COALESCE(
                        NULLIF(ABS(target.costo_unitario), 0),
                        reference.costo_unitario
                    )
                ELSE target.valor
            END
        OUTPUT
            deleted.fact_inventario_id,
            inserted.fact_inventario_id,
            deleted.valor,
            inserted.valor
        INTO @repairs (
            fact_id_before,
            fact_id_after,
            valor_before,
            valor_after
        )
        FROM dw.fact_inventario AS target
        INNER JOIN @product_cost AS reference
          ON reference.producto_key = target.producto_key
        WHERE target.inventario_movimiento_id NOT LIKE 'legacy_quant:%'
          AND target.inventario_movimiento_id NOT LIKE 'legacy_quant_sha256:%'
          AND NULLIF(ABS(target.cantidad), 0) IS NOT NULL
          AND (
              COALESCE(target.costo_unitario, 0) = 0
              OR COALESCE(target.valor, 0) = 0
          );

        SELECT
            @repaired_count = COUNT_BIG(*),
            @repair_delta = COALESCE(SUM(
                CONVERT(DECIMAL(38,4), COALESCE(valor_after, 0))
                - CONVERT(DECIMAL(38,4), COALESCE(valor_before, 0))
            ), 0)
        FROM @repairs;

        SELECT
            @after_count = COUNT_BIG(*),
            @after_sum = COALESCE(SUM(CONVERT(DECIMAL(38,4), valor)), 0)
        FROM dw.fact_inventario;

        SELECT @unresolved_native = COUNT_BIG(*)
        FROM dw.fact_inventario
        WHERE inventario_movimiento_id NOT LIKE 'legacy_quant:%'
          AND inventario_movimiento_id NOT LIKE 'legacy_quant_sha256:%'
          AND NULLIF(ABS(cantidad), 0) IS NOT NULL
          AND (COALESCE(costo_unitario, 0) = 0 OR COALESCE(valor, 0) = 0);

        IF @repaired_count <> @expected_repairs
            THROW 51021, 'Inventory valuation repair count does not reconcile.', 1;
        IF @after_count <> @before_count
            THROW 51022, 'Inventory valuation repair changed the fact row count.', 1;
        IF @after_sum <> @before_sum + @repair_delta
            THROW 51023, 'Inventory valuation repair amount does not reconcile.', 1;
        IF EXISTS (SELECT 1 FROM @repairs WHERE fact_id_before <> fact_id_after)
            THROW 51024, 'Inventory valuation repair changed surrogate keys.', 1;

        PRINT CONCAT(
            'INVENTORY_VALUATION_REPAIR before_count=', @before_count,
            ' before_sum=', @before_sum,
            ' repaired_count=', @repaired_count,
            ' repair_delta=', @repair_delta,
            ' after_count=', @after_count,
            ' after_sum=', @after_sum,
            ' unresolved_native_rows=', @unresolved_native
        );
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
