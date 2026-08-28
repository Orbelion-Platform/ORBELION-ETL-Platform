from etl_platform.pipelines.pipeline_audit import (
    finish_pipeline_failure,
    finish_pipeline_success,
    start_pipeline_run,
)
from etl_platform.pipelines.pipeline_context import PipelineContext
from etl_platform.pipelines.pipeline_errors import PipelineExecutionError
from etl_platform.pipelines.pipeline_steps import (
    extract_sources,
    load_dimensions_step,
    load_facts_step,
    load_staging_step,
    prepare_data_model,
    prepare_environment,
    register_processed_files,
    transform_data,
    update_watermarks,
)


class PipelineRunner:
    def __init__(self, context):
        self.context = context

    @classmethod
    def from_config_path(cls, config_path):
        return cls(PipelineContext.from_config_path(config_path))

    def run(self):
        try:
            prepare_environment(self.context)
            start_pipeline_run(self.context)
            prepare_data_model(self.context)

            extract_sources(self.context)

            if not self.context.has_data:
                register_processed_files(self.context)
                finish_pipeline_success(self.context)
                return

            transform_data(self.context)
            load_staging_step(self.context)
            load_dimensions_step(self.context)
            load_facts_step(self.context)
            register_processed_files(self.context)
            update_watermarks(self.context)
            finish_pipeline_success(self.context)

        except Exception as exc:
            finish_pipeline_failure(self.context, exc)
            raise PipelineExecutionError(self.context.current_step, exc) from exc


def run_pipeline(config_path):
    return PipelineRunner.from_config_path(config_path).run()
