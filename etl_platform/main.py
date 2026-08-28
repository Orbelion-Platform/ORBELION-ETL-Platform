import sys
import argparse
from etl_platform.core.config import ConfigValidationError
from etl_platform.core.db.staging import StagingContractError
from etl_platform.pipelines.pipeline_dw import run_pipeline
from etl_platform.pipelines.pipeline_errors import PipelineExecutionError
from etl_platform.validators import validate_config_full, ValidationError


def _safe_error_detail(error):
    if isinstance(error, StagingContractError):
        return str(error)

    # SQLAlchemy DBAPI errors expose the underlying driver exception as `.orig`.
    # Logging only that message avoids dumping SQL parameters or secrets.
    driver_error = getattr(error, "orig", None)
    if driver_error is not None:
        return str(driver_error)

    return str(error)


def main(argv=None):
    p = argparse.ArgumentParser(description='Run ETL pipeline with pre-validation')
    p.add_argument('config', help='Path to YAML config file')
    p.add_argument('--no-db', dest='check_db', action='store_false', help='Skip DB connectivity checks during validation')
    args = p.parse_args(argv)

    try:
        validate_config_full(args.config, check_db=args.check_db)
    except (ValidationError, ConfigValidationError) as e:
        print('CONFIG VALIDATION FAILED:', e)
        return 2

    try:
        run_pipeline(args.config)
    except PipelineExecutionError as exc:
        detail = _safe_error_detail(exc.original_error)
        print(
            f"PIPELINE FAILED: step={exc.step} "
            f"error={type(exc.original_error).__name__} detail={detail}",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
