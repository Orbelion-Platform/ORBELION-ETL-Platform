import os
import glob
from sqlalchemy import text


def _split_sql(sql_text):
	# Split on lines that contain only GO (case-insensitive)
	parts = []
	current = []
	for line in sql_text.splitlines():
		if line.strip().upper() == 'GO':
			if current:
				parts.append('\n'.join(current))
				current = []
		else:
			current.append(line)
	if current:
		parts.append('\n'.join(current))
	return parts


def run_sql_string(engine, sql_text):
	for stmt in _split_sql(sql_text):
		if not stmt.strip():
			continue
		with engine.begin() as conn:
			conn.exec_driver_sql(stmt)


def run_sql_file(engine, path):
	with open(path, 'r', encoding='utf-8') as f:
		sql = f.read()
	run_sql_string(engine, sql)


def apply_base_migrations(engine, ddl_base_dir):
	"""
	Execute SQL files from `ddl_base_dir` in lexical order. Intended for
	base objects such as dw schema and control tables.
	"""
	files = sorted(glob.glob(os.path.join(ddl_base_dir, '*.sql')))
	for f in files:
		run_sql_file(engine, f)


def create_client_schema(engine, schema_name):
	sql = f"""
	IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema_name}')
		EXEC('CREATE SCHEMA {schema_name}');
	GO
	"""
	run_sql_string(engine, sql)


def create_financial_model(engine, schema_name):
	"""Create the standard financial dimensions and facts for a client schema.
	The DDL is idempotent (checks OBJECT_ID before creating).
	"""

	create_client_schema(engine, schema_name)

	# Dimensions
	dim_fecha = f"""
	IF OBJECT_ID('{schema_name}.dim_fecha','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_fecha (
			fecha_id INT IDENTITY(1,1) PRIMARY KEY,
			fecha DATE NOT NULL,
			ano INT NOT NULL,
			mes INT NOT NULL,
			dia INT NOT NULL,
			trimestre INT NULL
		);
	END;
	GO
	"""

	dim_cliente = f"""
	IF OBJECT_ID('{schema_name}.dim_cliente','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_cliente (
			cliente_id INT IDENTITY(1,1) PRIMARY KEY,
			cliente_code NVARCHAR(100) NOT NULL,
			nombre NVARCHAR(255) NULL,
			activo BIT DEFAULT 1
		);
	END;
	GO
	"""

	dim_ubicacion = f"""
	IF OBJECT_ID('{schema_name}.dim_ubicacion','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_ubicacion (
			ubicacion_id INT IDENTITY(1,1) PRIMARY KEY,
			ubicacion_code NVARCHAR(100) NULL,
			ciudad NVARCHAR(100) NULL,
			pais NVARCHAR(100) NULL
		);
	END;
	GO
	"""

	dim_producto = f"""
	IF OBJECT_ID('{schema_name}.dim_producto_servicio','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_producto_servicio (
			producto_id INT IDENTITY(1,1) PRIMARY KEY,
			producto_code NVARCHAR(150) NULL,
			nombre NVARCHAR(255) NULL,
			categoria NVARCHAR(100) NULL
		);
	END;
	GO
	"""

	dim_metodo = f"""
	IF OBJECT_ID('{schema_name}.dim_metodo_pago','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_metodo_pago (
			metodo_id INT IDENTITY(1,1) PRIMARY KEY,
			metodo_code NVARCHAR(50) NULL,
			descripcion NVARCHAR(255) NULL
		);
	END;
	GO
	"""

	dim_gasto = f"""
	IF OBJECT_ID('{schema_name}.dim_gasto','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_gasto (
			gasto_id INT IDENTITY(1,1) PRIMARY KEY,
			categoria NVARCHAR(150) NULL,
			subcategoria NVARCHAR(150) NULL
		);
	END;
	GO
	"""

	dim_canal = f"""
	IF OBJECT_ID('{schema_name}.dim_canal','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_canal (
			canal_id INT IDENTITY(1,1) PRIMARY KEY,
			canal_code NVARCHAR(100) NULL,
			descripcion NVARCHAR(255) NULL
		);
	END;
	GO
	"""

	dim_proveedor = f"""
	IF OBJECT_ID('{schema_name}.dim_proveedor','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.dim_proveedor (
			proveedor_id INT IDENTITY(1,1) PRIMARY KEY,
			proveedor_code NVARCHAR(150) NULL,
			nombre NVARCHAR(255) NULL
		);
	END;
	GO
	"""

	# Facts
	fact_ventas = f"""
	IF OBJECT_ID('{schema_name}.fact_ventas','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.fact_ventas (
			venta_id BIGINT IDENTITY(1,1) PRIMARY KEY,
			fecha_id INT NULL,
			cliente_id INT NULL,
			producto_id INT NULL,
			canal_id INT NULL,
			metodo_id INT NULL,
			cantidad DECIMAL(18,4) NULL,
			importe_total DECIMAL(18,4) NULL
		);
	END;
	GO
	"""

	fact_gastos = f"""
	IF OBJECT_ID('{schema_name}.fact_gastos','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.fact_gastos (
			gasto_id BIGINT IDENTITY(1,1) PRIMARY KEY,
			fecha_id INT NULL,
			proveedor_id INT NULL,
			categoria NVARCHAR(150) NULL,
			importe DECIMAL(18,4) NULL
		);
	END;
	GO
	"""

	fact_compras = f"""
	IF OBJECT_ID('{schema_name}.fact_compras','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.fact_compras (
			compra_id BIGINT IDENTITY(1,1) PRIMARY KEY,
			fecha_id INT NULL,
			proveedor_id INT NULL,
			importe DECIMAL(18,4) NULL
		);
	END;
	GO
	"""

	fact_inventario = f"""
	IF OBJECT_ID('{schema_name}.fact_inventario','U') IS NULL
	BEGIN
		CREATE TABLE {schema_name}.fact_inventario (
			inventario_id BIGINT IDENTITY(1,1) PRIMARY KEY,
			fecha_id INT NULL,
			producto_id INT NULL,
			cantidad DECIMAL(18,4) NULL,
			valor DECIMAL(18,4) NULL
		);
	END;
	GO
	"""

	# Execute all statements
	for s in [
		dim_fecha,
		dim_cliente,
		dim_ubicacion,
		dim_producto,
		dim_metodo,
		dim_gasto,
		dim_canal,
		dim_proveedor,
		fact_ventas,
		fact_gastos,
		fact_compras,
		fact_inventario,
	]:
		run_sql_string(engine, s)


if __name__ == '__main__':
	print('This module provides DDL helpers for the ETL platform.')


