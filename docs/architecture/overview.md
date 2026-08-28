# Architecture overview

ORBELION uses a metadata-driven pipeline so connector behavior, transformations, warehouse contracts, and client configuration remain separate.

## Runtime components

1. `pipeline_runner.py` coordinates the ordered lifecycle and audit outcome.
2. `pipeline_steps.py` prepares the model, extracts each source, applies transformations, loads SQL objects, and persists control state.
3. `core/extract/connectors/` contains the CSV, Excel, REST, SQL, and Odoo adapters.
4. `core/metadata/` loads generic metadata and overlays `example_client` definitions.
5. `core/db/` owns Azure SQL connection, staging, dimensions, facts, file control, DDL, and watermarks.

## Trust boundaries

- Source credentials enter through environment variables or Azure Key Vault.
- GitHub Actions obtains Azure access through OIDC; no Azure client secret is required in repository configuration.
- Azure SQL is the durable boundary for analytical data and ETL control state.

## Warehouse contract

The included SQL defines ETL control tables, the shared `dw.dim_fecha`, analytical fact tables, Odoo staging/analytics objects, and reconciliation scripts. Business keys support idempotent fact loading; surrogate keys remain warehouse-managed.

## Public-edition boundary

This repository contains a synthetic example, not a deployable copy of any customer environment. Resource creation, tenant registration, role assignment, production schedules, and customer-specific operational procedures are intentionally excluded.
