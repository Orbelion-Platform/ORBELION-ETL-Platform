-- ORBELION source-agnostic standard analytical fact contract 2.0.
-- Preserves the former header/snapshot facts as *_legacy and introduces
-- line/movement-grain facts with consistent dimension *_key columns.

-- Canonical staging tables. Adapters from any provider load these columns.
IF OBJECT_ID('dw.stg_ventas', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_ventas (
        venta_linea_id NVARCHAR(100) NULL,
        venta_id NVARCHAR(100) NULL,
        cliente_id NVARCHAR(100) NULL,
        nombre NVARCHAR(255) NULL,
        fecha DATE NULL,
        producto_code NVARCHAR(150) NULL,
        producto_nombre NVARCHAR(255) NULL,
        categoria NVARCHAR(100) NULL,
        canal_code NVARCHAR(100) NULL,
        canal_descripcion NVARCHAR(255) NULL,
        metodo_pago_code NVARCHAR(100) NULL,
        metodo_pago_descripcion NVARCHAR(255) NULL,
        cantidad DECIMAL(18,4) NULL,
        precio_unitario DECIMAL(18,4) NULL,
        subtotal DECIMAL(18,4) NULL,
        descuento_pct DECIMAL(9,4) NULL,
        costo_unitario DECIMAL(18,4) NULL,
        total DECIMAL(18,4) NULL,
        estado NVARCHAR(50) NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_compras', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_compras (
        compra_linea_id NVARCHAR(100) NULL,
        compra_id NVARCHAR(100) NULL,
        proveedor_code NVARCHAR(150) NULL,
        nombre NVARCHAR(255) NULL,
        fecha DATE NULL,
        producto_code NVARCHAR(150) NULL,
        producto_nombre NVARCHAR(255) NULL,
        categoria NVARCHAR(100) NULL,
        cantidad DECIMAL(18,4) NULL,
        costo_unitario DECIMAL(18,4) NULL,
        importe DECIMAL(18,4) NULL,
        state NVARCHAR(50) NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_gastos', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_gastos (
        gasto_id NVARCHAR(100) NULL,
        proveedor_code NVARCHAR(150) NULL,
        nombre NVARCHAR(255) NULL,
        fecha DATE NULL,
        categoria NVARCHAR(150) NULL,
        subcategoria NVARCHAR(150) NULL,
        tipo_cuenta NVARCHAR(50) NULL,
        metodo_pago_code NVARCHAR(100) NULL,
        metodo_pago_descripcion NVARCHAR(255) NULL,
        clasificacion_financiera NVARCHAR(50) NULL,
        estado_pago NVARCHAR(50) NULL,
        importe DECIMAL(18,4) NULL,
        parent_state NVARCHAR(50) NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

IF OBJECT_ID('dw.stg_inventario', 'U') IS NULL
BEGIN
    CREATE TABLE dw.stg_inventario (
        inventario_movimiento_id NVARCHAR(100) NULL,
        inventario_id NVARCHAR(100) NULL,
        producto_code NVARCHAR(150) NULL,
        nombre NVARCHAR(255) NULL,
        categoria NVARCHAR(100) NULL,
        fecha DATE NULL,
        tipo_movimiento NVARCHAR(50) NULL,
        cantidad DECIMAL(18,4) NULL,
        costo_unitario DECIMAL(18,4) NULL,
        valor DECIMAL(18,4) NULL,
        write_date DATETIME2 NULL,
        __source NVARCHAR(100) NULL
    );
END;
GO

-- Canonical conformed dimensions shared by every source adapter.
IF OBJECT_ID('dw.dim_cliente', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_cliente (
        cliente_key INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_cliente PRIMARY KEY,
        cliente_id NVARCHAR(100) NOT NULL,
        nombre NVARCHAR(255) NULL,
        CONSTRAINT uq_dim_cliente_cliente_id UNIQUE (cliente_id)
    );
END;
GO

IF OBJECT_ID('dw.dim_producto_servicio', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_producto_servicio (
        producto_key INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_producto_servicio PRIMARY KEY,
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
        proveedor_key INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_proveedor PRIMARY KEY,
        proveedor_code NVARCHAR(150) NOT NULL,
        nombre NVARCHAR(255) NULL,
        CONSTRAINT uq_dim_proveedor_code UNIQUE (proveedor_code)
    );
END;
GO

IF OBJECT_ID('dw.dim_gasto', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_gasto (
        gasto_key INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_gasto PRIMARY KEY,
        categoria NVARCHAR(150) NOT NULL,
        subcategoria NVARCHAR(150) NULL,
        CONSTRAINT uq_dim_gasto_categoria UNIQUE (categoria)
    );
END;
GO

IF COL_LENGTH('dw.dim_fecha', 'fecha_key') IS NULL
    ALTER TABLE dw.dim_fecha ADD fecha_key AS
        CONVERT(INT, CONVERT(CHAR(8), fecha, 112)) PERSISTED;
GO

IF COL_LENGTH('dw.dim_producto_servicio', 'producto_key') IS NULL
   AND COL_LENGTH('dw.dim_producto_servicio', 'producto_id') IS NOT NULL
    ALTER TABLE dw.dim_producto_servicio ADD producto_key AS producto_id PERSISTED;
GO

IF COL_LENGTH('dw.dim_proveedor', 'proveedor_key') IS NULL
   AND COL_LENGTH('dw.dim_proveedor', 'proveedor_id') IS NOT NULL
    ALTER TABLE dw.dim_proveedor ADD proveedor_key AS proveedor_id PERSISTED;
GO

IF COL_LENGTH('dw.dim_gasto', 'gasto_key') IS NULL
   AND COL_LENGTH('dw.dim_gasto', 'gasto_id') IS NOT NULL
    ALTER TABLE dw.dim_gasto ADD gasto_key AS gasto_id PERSISTED;
GO

IF OBJECT_ID('dw.dim_canal', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_canal (
        canal_key INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_dim_canal PRIMARY KEY,
        canal_code NVARCHAR(100) NOT NULL,
        descripcion NVARCHAR(255) NULL,
        CONSTRAINT uq_dim_canal_code UNIQUE (canal_code)
    );
END
ELSE IF COL_LENGTH('dw.dim_canal', 'canal_key') IS NULL
        AND COL_LENGTH('dw.dim_canal', 'canal_id') IS NOT NULL
    ALTER TABLE dw.dim_canal ADD canal_key AS canal_id PERSISTED;
GO

IF OBJECT_ID('dw.dim_metodo_pago', 'U') IS NULL
BEGIN
    CREATE TABLE dw.dim_metodo_pago (
        metodo_pago_key INT IDENTITY(1,1) NOT NULL
            CONSTRAINT pk_dim_metodo_pago PRIMARY KEY,
        metodo_code NVARCHAR(100) NOT NULL,
        descripcion NVARCHAR(255) NULL,
        CONSTRAINT uq_dim_metodo_pago_code UNIQUE (metodo_code)
    );
END
ELSE IF COL_LENGTH('dw.dim_metodo_pago', 'metodo_pago_key') IS NULL
        AND COL_LENGTH('dw.dim_metodo_pago', 'metodo_id') IS NOT NULL
    ALTER TABLE dw.dim_metodo_pago ADD metodo_pago_key AS metodo_id PERSISTED;
GO

-- Staging is extended in place. Legacy columns remain available during rollout.
-- The former business keys are relaxed because v2 loads line/movement identifiers.
IF COL_LENGTH('dw.stg_compras', 'compra_key') IS NOT NULL
    ALTER TABLE dw.stg_compras ALTER COLUMN compra_key NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_gastos', 'gasto_key') IS NOT NULL
    ALTER TABLE dw.stg_gastos ALTER COLUMN gasto_key NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_inventario', 'inventario_key') IS NOT NULL
    ALTER TABLE dw.stg_inventario ALTER COLUMN inventario_key NVARCHAR(100) NULL;
GO

IF COL_LENGTH('dw.stg_ventas', 'venta_linea_id') IS NULL
    ALTER TABLE dw.stg_ventas ADD venta_linea_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_ventas', 'producto_code') IS NULL
    ALTER TABLE dw.stg_ventas ADD producto_code NVARCHAR(150) NULL;
IF COL_LENGTH('dw.stg_ventas', 'producto_nombre') IS NULL
    ALTER TABLE dw.stg_ventas ADD producto_nombre NVARCHAR(255) NULL;
IF COL_LENGTH('dw.stg_ventas', 'categoria') IS NULL
    ALTER TABLE dw.stg_ventas ADD categoria NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_ventas', 'canal_code') IS NULL
    ALTER TABLE dw.stg_ventas ADD canal_code NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_ventas', 'canal_descripcion') IS NULL
    ALTER TABLE dw.stg_ventas ADD canal_descripcion NVARCHAR(255) NULL;
IF COL_LENGTH('dw.stg_ventas', 'metodo_pago_code') IS NULL
    ALTER TABLE dw.stg_ventas ADD metodo_pago_code NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_ventas', 'metodo_pago_descripcion') IS NULL
    ALTER TABLE dw.stg_ventas ADD metodo_pago_descripcion NVARCHAR(255) NULL;
IF COL_LENGTH('dw.stg_ventas', 'cantidad') IS NULL
    ALTER TABLE dw.stg_ventas ADD cantidad DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_ventas', 'precio_unitario') IS NULL
    ALTER TABLE dw.stg_ventas ADD precio_unitario DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_ventas', 'subtotal') IS NULL
    ALTER TABLE dw.stg_ventas ADD subtotal DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_ventas', 'descuento_pct') IS NULL
    ALTER TABLE dw.stg_ventas ADD descuento_pct DECIMAL(9,4) NULL;
IF COL_LENGTH('dw.stg_ventas', 'costo_unitario') IS NULL
    ALTER TABLE dw.stg_ventas ADD costo_unitario DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_ventas', 'estado') IS NULL
    ALTER TABLE dw.stg_ventas ADD estado NVARCHAR(50) NULL;
GO

IF COL_LENGTH('dw.stg_compras', 'compra_linea_id') IS NULL
    ALTER TABLE dw.stg_compras ADD compra_linea_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_compras', 'compra_id') IS NULL
    ALTER TABLE dw.stg_compras ADD compra_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_compras', 'producto_code') IS NULL
    ALTER TABLE dw.stg_compras ADD producto_code NVARCHAR(150) NULL;
IF COL_LENGTH('dw.stg_compras', 'producto_nombre') IS NULL
    ALTER TABLE dw.stg_compras ADD producto_nombre NVARCHAR(255) NULL;
IF COL_LENGTH('dw.stg_compras', 'categoria') IS NULL
    ALTER TABLE dw.stg_compras ADD categoria NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_compras', 'cantidad') IS NULL
    ALTER TABLE dw.stg_compras ADD cantidad DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_compras', 'costo_unitario') IS NULL
    ALTER TABLE dw.stg_compras ADD costo_unitario DECIMAL(18,4) NULL;
GO

IF COL_LENGTH('dw.stg_gastos', 'gasto_id') IS NULL
    ALTER TABLE dw.stg_gastos ADD gasto_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_gastos', 'metodo_pago_code') IS NULL
    ALTER TABLE dw.stg_gastos ADD metodo_pago_code NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_gastos', 'metodo_pago_descripcion') IS NULL
    ALTER TABLE dw.stg_gastos ADD metodo_pago_descripcion NVARCHAR(255) NULL;
IF COL_LENGTH('dw.stg_gastos', 'tipo_cuenta') IS NULL
    ALTER TABLE dw.stg_gastos ADD tipo_cuenta NVARCHAR(50) NULL;
IF COL_LENGTH('dw.stg_gastos', 'clasificacion_financiera') IS NULL
    ALTER TABLE dw.stg_gastos ADD clasificacion_financiera NVARCHAR(50) NULL;
IF COL_LENGTH('dw.stg_gastos', 'estado_pago') IS NULL
    ALTER TABLE dw.stg_gastos ADD estado_pago NVARCHAR(50) NULL;
GO

IF COL_LENGTH('dw.stg_inventario', 'inventario_movimiento_id') IS NULL
    ALTER TABLE dw.stg_inventario ADD inventario_movimiento_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_inventario', 'inventario_id') IS NULL
    ALTER TABLE dw.stg_inventario ADD inventario_id NVARCHAR(100) NULL;
IF COL_LENGTH('dw.stg_inventario', 'fecha') IS NULL
    ALTER TABLE dw.stg_inventario ADD fecha DATE NULL;
IF COL_LENGTH('dw.stg_inventario', 'costo_unitario') IS NULL
    ALTER TABLE dw.stg_inventario ADD costo_unitario DECIMAL(18,4) NULL;
IF COL_LENGTH('dw.stg_inventario', 'tipo_movimiento') IS NULL
    ALTER TABLE dw.stg_inventario ADD tipo_movimiento NVARCHAR(50) NULL;
GO

-- Preserve the previous facts because their grains are incompatible with v2.
IF OBJECT_ID('dw.fact_ventas_legacy', 'U') IS NULL
   AND OBJECT_ID('dw.fact_ventas', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_ventas', 'venta_linea_id') IS NULL
    EXEC sp_rename 'dw.fact_ventas', 'fact_ventas_legacy';
GO
IF OBJECT_ID('dw.fact_compras_legacy', 'U') IS NULL
   AND OBJECT_ID('dw.fact_compras', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_compras', 'compra_linea_id') IS NULL
    EXEC sp_rename 'dw.fact_compras', 'fact_compras_legacy';
GO
IF OBJECT_ID('dw.fact_gastos_legacy', 'U') IS NULL
   AND OBJECT_ID('dw.fact_gastos', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_gastos', 'fecha_key') IS NULL
    EXEC sp_rename 'dw.fact_gastos', 'fact_gastos_legacy';
GO
IF OBJECT_ID('dw.fact_inventario_legacy', 'U') IS NULL
   AND OBJECT_ID('dw.fact_inventario', 'U') IS NOT NULL
   AND COL_LENGTH('dw.fact_inventario', 'inventario_movimiento_id') IS NULL
    EXEC sp_rename 'dw.fact_inventario', 'fact_inventario_legacy';
GO

IF OBJECT_ID('dw.fact_ventas', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_ventas (
        fact_venta_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_fact_ventas PRIMARY KEY,
        venta_linea_id NVARCHAR(100) NOT NULL,
        venta_id NVARCHAR(100) NULL,
        fecha_key INT NULL,
        cliente_key INT NULL,
        producto_key INT NULL,
        canal_key INT NULL,
        metodo_pago_key INT NULL,
        cantidad DECIMAL(18,4) NULL,
        precio_unitario DECIMAL(18,4) NULL,
        subtotal DECIMAL(18,4) NULL,
        descuento DECIMAL(18,4) NULL,
        costo DECIMAL(18,4) NULL,
        total DECIMAL(18,4) NULL,
        estado NVARCHAR(50) NULL,
        CONSTRAINT uq_fact_ventas_linea UNIQUE (venta_linea_id)
    );
END;
GO

IF OBJECT_ID('dw.fact_compras', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_compras (
        fact_compra_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_fact_compras PRIMARY KEY,
        compra_linea_id NVARCHAR(100) NOT NULL,
        compra_id NVARCHAR(100) NULL,
        fecha_key INT NULL,
        proveedor_key INT NULL,
        producto_key INT NULL,
        cantidad DECIMAL(18,4) NULL,
        costo_unitario DECIMAL(18,4) NULL,
        importe DECIMAL(18,4) NULL,
        estado NVARCHAR(50) NULL,
        CONSTRAINT uq_fact_compras_linea UNIQUE (compra_linea_id)
    );
END;
GO

IF OBJECT_ID('dw.fact_gastos', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_gastos (
        fact_gasto_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_fact_gastos PRIMARY KEY,
        gasto_id NVARCHAR(100) NOT NULL,
        fecha_key INT NULL,
        proveedor_key INT NULL,
        gasto_key INT NULL,
        metodo_pago_key INT NULL,
        importe DECIMAL(18,4) NULL,
        clasificacion_financiera NVARCHAR(50) NULL,
        estado_pago NVARCHAR(50) NULL,
        CONSTRAINT uq_fact_gastos_id UNIQUE (gasto_id)
    );
END;
GO

IF OBJECT_ID('dw.fact_inventario', 'U') IS NULL
BEGIN
    CREATE TABLE dw.fact_inventario (
        fact_inventario_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_fact_inventario PRIMARY KEY,
        inventario_movimiento_id NVARCHAR(100) NOT NULL,
        inventario_id NVARCHAR(100) NULL,
        fecha_key INT NULL,
        producto_key INT NULL,
        tipo_movimiento NVARCHAR(50) NOT NULL,
        cantidad DECIMAL(18,4) NULL,
        costo_unitario DECIMAL(18,4) NULL,
        valor DECIMAL(18,4) NULL,
        CONSTRAINT uq_fact_inventario_movimiento UNIQUE (inventario_movimiento_id)
    );
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dw.fact_ventas') AND name = 'ix_fact_ventas_fecha_producto')
    CREATE INDEX ix_fact_ventas_fecha_producto ON dw.fact_ventas(fecha_key, producto_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dw.fact_compras') AND name = 'ix_fact_compras_fecha_producto')
    CREATE INDEX ix_fact_compras_fecha_producto ON dw.fact_compras(fecha_key, producto_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dw.fact_gastos') AND name = 'ix_fact_gastos_fecha')
    CREATE INDEX ix_fact_gastos_fecha ON dw.fact_gastos(fecha_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dw.fact_inventario') AND name = 'ix_fact_inventario_fecha_producto')
    CREATE INDEX ix_fact_inventario_fecha_producto ON dw.fact_inventario(fecha_key, producto_key);
GO
