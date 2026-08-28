-- Orbelion standard Odoo analytical model 1.1.0.
-- Additive and idempotent: existing tables and data are never dropped or truncated.

IF OBJECT_ID('dw.stg_ventas', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_ventas (
        venta_id NVARCHAR(100) NOT NULL,
        cliente_id NVARCHAR(50) NOT NULL,
        nombre NVARCHAR(100) NULL,
        total DECIMAL(18,4) NOT NULL,
        fecha DATE NOT NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_inventario', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_inventario (
        inventario_key NVARCHAR(100) NOT NULL,
        producto_code NVARCHAR(150) NOT NULL,
        nombre NVARCHAR(255) NULL,
        categoria NVARCHAR(100) NULL,
        cantidad DECIMAL(18,4) NULL,
        valor DECIMAL(18,4) NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_compras', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_compras (
        compra_key NVARCHAR(100) NOT NULL,
        proveedor_code NVARCHAR(150) NULL,
        nombre NVARCHAR(255) NULL,
        fecha DATE NULL,
        importe DECIMAL(18,4) NULL,
        write_date DATETIME2 NULL,
        state NVARCHAR(50) NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_gastos', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_gastos (
        gasto_key NVARCHAR(100) NOT NULL,
        proveedor_code NVARCHAR(150) NULL,
        nombre NVARCHAR(255) NULL,
        fecha DATE NULL,
        categoria NVARCHAR(150) NULL,
        subcategoria NVARCHAR(150) NULL,
        importe DECIMAL(18,4) NULL,
        write_date DATETIME2 NULL,
        parent_state NVARCHAR(50) NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.dim_cliente', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_cliente (
        cliente_key INT IDENTITY(1,1) PRIMARY KEY,
        cliente_id NVARCHAR(50) NOT NULL,
        nombre NVARCHAR(100) NULL,
        CONSTRAINT uq_dim_cliente_cliente_id UNIQUE (cliente_id)
    );
END;
GO

IF OBJECT_ID('dw.dim_producto_servicio', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_producto_servicio (
        producto_id INT IDENTITY(1,1) PRIMARY KEY,
        producto_code NVARCHAR(150) NOT NULL,
        nombre NVARCHAR(255) NULL,
        categoria NVARCHAR(100) NULL,
        CONSTRAINT uq_dim_producto_code UNIQUE (producto_code)
    );
END;
GO

IF OBJECT_ID('dw.dim_proveedor', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_proveedor (
        proveedor_id INT IDENTITY(1,1) PRIMARY KEY,
        proveedor_code NVARCHAR(150) NOT NULL,
        nombre NVARCHAR(255) NULL,
        CONSTRAINT uq_dim_proveedor_code UNIQUE (proveedor_code)
    );
END;
GO

IF OBJECT_ID('dw.dim_gasto', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_gasto (
        gasto_id INT IDENTITY(1,1) PRIMARY KEY,
        categoria NVARCHAR(150) NOT NULL,
        subcategoria NVARCHAR(150) NULL,
        CONSTRAINT uq_dim_gasto_categoria UNIQUE (categoria)
    );
END;
GO

IF OBJECT_ID('dw.fact_ventas', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_ventas (
        fact_venta_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        venta_id NVARCHAR(100) NOT NULL,
        cliente_key INT NULL,
        total DECIMAL(18,4) NULL,
        fecha DATE NULL,
        CONSTRAINT uq_fact_ventas_venta_id UNIQUE (venta_id)
    );
END;
GO

IF OBJECT_ID('dw.fact_inventario', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_inventario (
        fact_inventario_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        inventario_key NVARCHAR(100) NOT NULL,
        producto_id INT NULL,
        cantidad DECIMAL(18,4) NULL,
        valor DECIMAL(18,4) NULL,
        CONSTRAINT uq_fact_inventario_key UNIQUE (inventario_key)
    );
END;
GO

IF OBJECT_ID('dw.fact_compras', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_compras (
        fact_compra_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        compra_key NVARCHAR(100) NOT NULL,
        proveedor_id INT NULL,
        importe DECIMAL(18,4) NULL,
        CONSTRAINT uq_fact_compras_key UNIQUE (compra_key)
    );
END;
GO

IF OBJECT_ID('dw.fact_gastos', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_gastos (
        fact_gasto_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        gasto_key NVARCHAR(100) NOT NULL,
        proveedor_id INT NULL,
        categoria NVARCHAR(150) NULL,
        importe DECIMAL(18,4) NULL,
        CONSTRAINT uq_fact_gastos_key UNIQUE (gasto_key)
    );
END;
GO

-- Safe upgrades for models created by earlier framework versions.
IF OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_inventario', 'inventario_movimiento_id') IS NULL
   AND COL_LENGTH('dw.fact_inventario', 'inventario_key') IS NULL
    ALTER TABLE dw.fact_inventario ADD inventario_key NVARCHAR(100) NULL;
GO
IF OBJECT_ID('dw.fact_compras', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_compras', 'compra_linea_id') IS NULL
   AND COL_LENGTH('dw.fact_compras', 'compra_key') IS NULL
    ALTER TABLE dw.fact_compras ADD compra_key NVARCHAR(100) NULL;
GO
IF OBJECT_ID('dw.fact_gastos', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_gastos', 'fecha_key') IS NULL
   AND COL_LENGTH('dw.fact_gastos', 'gasto_key') IS NULL
    ALTER TABLE dw.fact_gastos ADD gasto_key NVARCHAR(100) NULL;
GO
