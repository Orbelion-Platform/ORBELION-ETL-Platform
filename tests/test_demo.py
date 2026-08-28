from pathlib import Path

from demo.run_demo import run_demo


def test_synthetic_demo_extracts_transforms_and_writes_output(tmp_path):
    output = tmp_path / "orders_transformed.csv"
    transformed, destination = run_demo(output)

    assert destination == output
    assert output.exists()
    assert len(transformed) == 4
    assert transformed["total"].sum() == 408.5
    assert transformed["order_line_key"].is_unique
    assert transformed["order_line_key"].tolist()[0] == "SO-1001_1"

