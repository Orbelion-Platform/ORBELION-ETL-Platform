class PipelineExecutionError(RuntimeError):
    def __init__(self, step, original_error):
        self.step = step
        self.original_error = original_error
        super().__init__(f"Pipeline failed during {step}: {original_error}")
