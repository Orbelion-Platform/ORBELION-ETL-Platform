import pandas as pd
import pytest

from etl_platform.pipelines import pipeline_audit, pipeline_runner, pipeline_steps
from etl_platform.pipelines.pipeline_context import PipelineContext
from etl_platform.pipelines.pipeline_errors import PipelineExecutionError
from etl_platform.pipelines.pipeline_runner import PipelineRunner


def make_context():
    return PipelineContext(
        config_path="config.yaml",
        config={
            "process_name": "test_process",
            "load_mode": "incremental",
            "incremental_column": "updated_at",
            "sources": [],
        },
        engine=object(),
        process_name="test_process",
        mode="incremental",
    )


def patch_audit(monkeypatch, events):
    def start(context):
        context.run_id = 10
        events.append("start_run")

    def success(context):
        events.append(("success", context.records_processed))

    def failure(context, error):
        events.append(("failure", context.current_step, str(error)))

    monkeypatch.setattr(pipeline_runner, "start_pipeline_run", start)
    monkeypatch.setattr(pipeline_runner, "finish_pipeline_success", success)
    monkeypatch.setattr(pipeline_runner, "finish_pipeline_failure", failure)


def patch_common_success_steps(monkeypatch, events):
    df = pd.DataFrame({"id": [1], "updated_at": ["2026-01-01"]})

    monkeypatch.setattr(pipeline_runner, "prepare_environment", lambda context: events.append("prepare"))
    monkeypatch.setattr(pipeline_runner, "prepare_data_model", lambda context: events.append("model"))

    def extract(context):
        context.current_step = "extraction"
        context.extracted_frames.append(df)
        context.watermark_updates.append({
            "process_name": "test_process",
            "source_name": "api",
            "entity_name": "orders",
            "endpoint": "/orders",
            "value": "2026-01-01",
        })
        events.append("extract")

    def transform(context):
        context.current_step = "transformation"
        context.transformed_df = df
        events.append("transform")

    monkeypatch.setattr(pipeline_runner, "extract_sources", extract)
    monkeypatch.setattr(pipeline_runner, "transform_data", transform)
    monkeypatch.setattr(pipeline_runner, "load_staging_step", lambda context: events.append("staging"))
    monkeypatch.setattr(pipeline_runner, "load_dimensions_step", lambda context: events.append("dimensions"))
    monkeypatch.setattr(pipeline_runner, "load_facts_step", lambda context: events.append("facts"))
    monkeypatch.setattr(pipeline_runner, "register_processed_files", lambda context: events.append("files"))
    monkeypatch.setattr(pipeline_runner, "update_watermarks", lambda context: events.append("watermarks"))


def test_pipeline_runner_successful_flow(monkeypatch):
    events = []
    context = make_context()
    patch_audit(monkeypatch, events)
    patch_common_success_steps(monkeypatch, events)

    PipelineRunner(context).run()

    assert events == [
        "prepare",
        "start_run",
        "model",
        "extract",
        "transform",
        "staging",
        "dimensions",
        "facts",
        "files",
        "watermarks",
        ("success", 1),
    ]


def test_pipeline_runner_closes_run_on_extraction_failure(monkeypatch):
    events = []
    context = make_context()
    patch_audit(monkeypatch, events)
    monkeypatch.setattr(pipeline_runner, "prepare_environment", lambda context: None)
    monkeypatch.setattr(pipeline_runner, "prepare_data_model", lambda context: None)

    def fail_extract(context):
        context.current_step = "extraction"
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(pipeline_runner, "extract_sources", fail_extract)

    with pytest.raises(PipelineExecutionError, match="extraction"):
        PipelineRunner(context).run()

    assert events == ["start_run", ("failure", "extraction", "source unavailable")]


def test_pipeline_runner_audits_data_model_failure(monkeypatch):
    events = []
    context = make_context()
    patch_audit(monkeypatch, events)
    monkeypatch.setattr(pipeline_runner, "prepare_environment", lambda context: None)

    def fail_model(context):
        context.current_step = "prepare_data_model"
        raise RuntimeError("DDL failed password=hidden")

    monkeypatch.setattr(pipeline_runner, "prepare_data_model", fail_model)
    with pytest.raises(PipelineExecutionError, match="prepare_data_model"):
        PipelineRunner(context).run()
    assert events[0] == "start_run"
    assert events[1][0:2] == ("failure", "prepare_data_model")


def test_pipeline_runner_closes_run_on_transformation_failure(monkeypatch):
    events = []
    context = make_context()
    patch_audit(monkeypatch, events)
    monkeypatch.setattr(pipeline_runner, "prepare_environment", lambda context: None)
    monkeypatch.setattr(pipeline_runner, "prepare_data_model", lambda context: None)
    monkeypatch.setattr(
        pipeline_runner,
        "extract_sources",
        lambda context: context.extracted_frames.append(pd.DataFrame({"id": [1]})),
    )

    def fail_transform(context):
        context.current_step = "transformation"
        raise ValueError("invalid mapping")

    monkeypatch.setattr(pipeline_runner, "transform_data", fail_transform)

    with pytest.raises(PipelineExecutionError, match="transformation"):
        PipelineRunner(context).run()

    assert events == ["start_run", ("failure", "transformation", "invalid mapping")]


def test_pipeline_runner_closes_run_on_load_failure(monkeypatch):
    events = []
    context = make_context()
    patch_audit(monkeypatch, events)
    patch_common_success_steps(monkeypatch, events)

    def fail_load(context):
        context.current_step = "staging_load"
        raise RuntimeError("staging unavailable")

    monkeypatch.setattr(pipeline_runner, "load_staging_step", fail_load)

    with pytest.raises(PipelineExecutionError, match="staging_load"):
        PipelineRunner(context).run()

    assert ("failure", "staging_load", "staging unavailable") in events
    assert "files" not in events
    assert "watermarks" not in events


def test_pipeline_audit_updates_etl_runs_with_error_message(monkeypatch):
    calls = []
    context = make_context()
    context.run_id = 7

    def fake_end_run(engine, run_id, status, records_processed, error_message=None):
        calls.append({
            "run_id": run_id,
            "status": status,
            "records_processed": records_processed,
            "error_message": error_message,
        })

    monkeypatch.setattr(pipeline_audit, "end_run", fake_end_run)

    pipeline_audit.finish_pipeline_failure(context, RuntimeError("boom"))

    assert calls == [{
        "run_id": 7,
        "status": "FAILED",
        "records_processed": 0,
        "error_message": "boom",
    }]


def test_pipeline_audit_redacts_secrets(monkeypatch):
    calls = []
    context = make_context()
    context.run_id = 8
    monkeypatch.setattr(
        pipeline_audit,
        "end_run",
        lambda *args, **kwargs: calls.append(kwargs.get("error_message")),
    )
    pipeline_audit.finish_pipeline_failure(context, RuntimeError("password=supersecret token:abc"))
    assert calls == ["password=[REDACTED] token:[REDACTED]"]


def test_pipeline_steps_updates_watermarks(monkeypatch):
    calls = []
    context = make_context()
    context.watermark_updates = [
        {
            "process_name": "test_process",
            "source_name": "orders",
            "entity_name": "sale.order",
            "endpoint": "/orders",
            "value": "2026-01-01",
        }
    ]

    monkeypatch.setattr(
        pipeline_steps,
        "update_watermark",
        lambda engine, **kwargs: calls.append(kwargs),
    )

    pipeline_steps.update_watermarks(context)

    assert calls == [context.watermark_updates[0]]


def test_file_selection_respects_processed_files_by_mode():
    files = ["a.csv", "b.csv", "c.csv"]
    processed = {"b.csv"}

    assert pipeline_steps.select_files_for_mode(files, processed, "files") == ["a.csv", "c.csv"]
    assert pipeline_steps.select_files_for_mode(files, processed, "hybrid") == ["a.csv", "c.csv"]
    assert pipeline_steps.select_files_for_mode(files, processed, "incremental") == files
