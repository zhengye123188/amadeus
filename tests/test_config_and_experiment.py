import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_cli.config import Settings


def test_cost_requires_explicit_prices(tmp_path, monkeypatch):
    for name in ["RESEARCH_MODEL", "RESEARCH_API", "OPENAI_BASE_URL"]:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "settings.toml"
    path.write_text('model = "fixture"\nmax_turn_cost = 0.1\n')
    with pytest.raises(ValueError, match="requires both token prices"):
        Settings.load(path)
    path.write_text(
        'model = "fixture"\nmax_turn_cost = 0.1\ninput_price_per_million = 1\noutput_price_per_million = 2\n'
    )
    assert Settings.load(path).max_turn_cost == 0.1


def test_configuration_is_only_loaded_explicitly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RESEARCH_API", raising=False)
    (tmp_path / "research.toml").write_text('execution = "local"\n')
    assert Settings.load().execution == "disabled"
    assert Settings.load(tmp_path / "research.toml").execution == "local"


def test_example_metrics_are_real_reproducible_and_provenanced(tmp_path):
    root = Path(__file__).parents[1]
    script = root / "examples/retrieval_lab/run.py"
    outputs = []
    for n in range(2):
        path = tmp_path / f"metrics{n}.json"
        completed = subprocess.run(
            [sys.executable, str(script), "--output", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(json.loads(path.read_text()))
    assert (
        outputs[0]["dataset_sha256"]
        == hashlib.sha256(script.with_name("dataset.json").read_bytes()).hexdigest()
    )
    assert outputs[0]["code_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()
    for first, second in zip(outputs[0]["results"], outputs[1]["results"]):
        assert first["cases"] == second["cases"]
        assert first["queries"] == 8
        assert 0 <= first["recall_at_3"] <= 1
        assert (
            first["mrr_at_10"]
            == sum(c["reciprocal_rank_at_10"] for c in first["cases"]) / first["queries"]
        )
