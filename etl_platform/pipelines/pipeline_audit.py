from etl_platform.core.db.control import end_run, start_run
import re


SECRET_PATTERN = re.compile(
    r"(?i)(password|pwd|token|api[_-]?key|secret)(\s*[=:]\s*)([^;\s,]+)"
)


def sanitize_error(error):
    message = SECRET_PATTERN.sub(r"\1\2[REDACTED]", str(error))
    return message[:2000]


def start_pipeline_run(context):
    context.current_step = "audit.start_run"
    context.run_id = start_run(context.engine, context.process_name)
    return context.run_id


def finish_pipeline_success(context):
    context.current_step = "audit.end_success"
    end_run(context.engine, context.run_id, "SUCCESS", context.records_processed)


def finish_pipeline_failure(context, error):
    if context.run_id is None:
        return

    message = sanitize_error(error)
    end_run(context.engine, context.run_id, "FAILED", 0, error_message=message)
