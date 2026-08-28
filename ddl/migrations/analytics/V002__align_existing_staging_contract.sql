-- ORBELION analytical contract 2.0 hotfix.
-- Aligns warehouses upgraded from the 1.x Odoo model with the canonical
-- source-agnostic staging contract. V001 added the new columns, but existing
-- columns retained their legacy widths and nullability.

IF OBJECT_ID('dw.stg_ventas', 'U') IS NOT NULL
BEGIN
    IF COL_LENGTH('dw.stg_ventas', 'venta_id') IS NOT NULL
        ALTER TABLE dw.stg_ventas ALTER COLUMN venta_id NVARCHAR(100) NULL;
    IF COL_LENGTH('dw.stg_ventas', 'cliente_id') IS NOT NULL
        ALTER TABLE dw.stg_ventas ALTER COLUMN cliente_id NVARCHAR(100) NULL;
    IF COL_LENGTH('dw.stg_ventas', 'nombre') IS NOT NULL
        ALTER TABLE dw.stg_ventas ALTER COLUMN nombre NVARCHAR(255) NULL;
    IF COL_LENGTH('dw.stg_ventas', 'total') IS NOT NULL
        ALTER TABLE dw.stg_ventas ALTER COLUMN total DECIMAL(18,4) NULL;
    IF COL_LENGTH('dw.stg_ventas', 'fecha') IS NOT NULL
        ALTER TABLE dw.stg_ventas ALTER COLUMN fecha DATE NULL;
END;
GO

IF OBJECT_ID('dw.stg_inventario', 'U') IS NOT NULL
BEGIN
    IF COL_LENGTH('dw.stg_inventario', 'inventario_key') IS NOT NULL
        ALTER TABLE dw.stg_inventario ALTER COLUMN inventario_key NVARCHAR(100) NULL;
    IF COL_LENGTH('dw.stg_inventario', 'producto_code') IS NOT NULL
        ALTER TABLE dw.stg_inventario ALTER COLUMN producto_code NVARCHAR(150) NULL;
END;
GO

IF OBJECT_ID('dw.stg_compras', 'U') IS NOT NULL
   AND COL_LENGTH('dw.stg_compras', 'compra_key') IS NOT NULL
    ALTER TABLE dw.stg_compras ALTER COLUMN compra_key NVARCHAR(100) NULL;
GO

IF OBJECT_ID('dw.stg_gastos', 'U') IS NOT NULL
   AND COL_LENGTH('dw.stg_gastos', 'gasto_key') IS NOT NULL
    ALTER TABLE dw.stg_gastos ALTER COLUMN gasto_key NVARCHAR(100) NULL;
GO

-- dim_cliente also retained the smaller 1.x widths. Rebuild the known unique
-- constraint around the safe widening of its natural key.
IF OBJECT_ID('dw.dim_cliente', 'U') IS NOT NULL
BEGIN
    IF COL_LENGTH('dw.dim_cliente', 'cliente_id') IS NOT NULL
       AND COL_LENGTH('dw.dim_cliente', 'cliente_id') < 200
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id = OBJECT_ID('dw.dim_cliente')
              AND name = 'uq_dim_cliente_cliente_id'
        )
            ALTER TABLE dw.dim_cliente
                DROP CONSTRAINT uq_dim_cliente_cliente_id;

        IF EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id = OBJECT_ID('dw.dim_cliente')
              AND name = 'uq_dim_cliente'
        )
            ALTER TABLE dw.dim_cliente DROP CONSTRAINT uq_dim_cliente;

        ALTER TABLE dw.dim_cliente
            ALTER COLUMN cliente_id NVARCHAR(100) NOT NULL;

        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id = OBJECT_ID('dw.dim_cliente')
              AND name = 'uq_dim_cliente_cliente_id'
        )
            ALTER TABLE dw.dim_cliente
                ADD CONSTRAINT uq_dim_cliente_cliente_id UNIQUE (cliente_id);
    END;

    IF COL_LENGTH('dw.dim_cliente', 'nombre') IS NOT NULL
        ALTER TABLE dw.dim_cliente ALTER COLUMN nombre NVARCHAR(255) NULL;
END;
GO
