import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_cli.experiments import Experiments, ExperimentSpec, verify_experiment
from research_cli.jobs import Jobs, Run

LAB = Path(__file__).resolve().parents[1] / "examples" / "experiment_lab"


@pytest.fixture
def lab(tmp_path):
    target = tmp_path / "lab"
    shutil.copytree(LAB, target)
    return target


def lab_spec(variant="baseline", seed=7):
    spec = json.loads((LAB / "spec.json").read_text())
    spec.update(variant=variant, seed=seed)
    spec["parameters"]["degree"] = {"baseline": 1, "quadratic": 2, "negative": 0}[variant]
    return spec


async def measured_run(jobs, variant="baseline", seed=7, spec=None, script=None):
    args = {
        "argv": [sys.executable, "run.py", "--variant", variant, "--seed", str(seed)],
        "cwd": "lab",
        "timeout_seconds": 5,
        "spec": spec or lab_spec(variant, seed),
    }
    if script is not None:
        args["argv"] = [sys.executable, "-c", script]
    result = await jobs.start(args)
    await jobs.tasks[result["job_id"]]
    return await jobs.status(result)


async def test_real_offline_baseline_improvement_and_negative_comparisons(registry, lab):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    experiments = Experiments(registry)
    try:
        baseline = [await measured_run(jobs, seed=seed) for seed in (7, 19)]
        improved = [await measured_run(jobs, "quadratic", seed) for seed in (7, 19)]
        negative = [await measured_run(jobs, "negative", seed) for seed in (7, 19)]
        for job in [*baseline, *improved, *negative]:
            results = verify_experiment(registry.store, job)
            assert results["status"] == "verified"
            assert results["metrics_file"]["sha256"]
            assert results["artifacts"][0]["path"] == "predictions.json"
            assert job["environment"]["python_host_version"]
        args = {
            "baseline_job_ids": [job["job_id"] for job in baseline],
            "candidate_job_ids": [job["job_id"] for job in improved],
        }
        result = await experiments.compare(args)
        assert result["comparable"]
        assert result["metrics"]["mse"]["observed_direction"] == "improved"
        assert result["metrics"]["mse"]["candidate"]["mean"] < 0.001
        assert result["metrics"]["mse"]["baseline"]["mean"] > 1
        assert result["metrics"]["mse"]["baseline"]["stdev"] is not None
        assert len(result["metrics"]["mse"]["paired_deltas"]) == 2
        assert "no significance" in result["interpretation"]
        result = await experiments.compare(
            {
                **args,
                "candidate_job_ids": [job["job_id"] for job in negative],
            }
        )
        assert result["metrics"]["mse"]["observed_direction"] == "worse"
        assert not (lab / "metrics.json").exists()
        assert (await experiments.listing({"group": "offline-quadratic-regression"}))["total"] == 6
        assert (await experiments.listing({"group": "other"}))["total"] == 0
        report = await experiments.export({**args, "format": "markdown"})
        assert report["comparable"] and "Provenance" in report["content"]
        assert registry.store.read_artifact(report["artifact_id"])["text"].startswith("#")
        report = await experiments.export({**args, "format": "json"})
        assert json.loads(report["content"])["comparable"]
    finally:
        await jobs.close()


@pytest.mark.parametrize(
    "change",
    ["split", "protocol", "dataset", "definition", "direction", "unit", "primary", "group"],
)
async def test_compare_rejects_nonmatching_conditions(registry, lab, change):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    baseline = await measured_run(jobs)
    spec = lab_spec("quadratic")
    if change in {"split", "protocol"}:
        spec["dataset"][change] = "different evaluation condition"
    elif change == "dataset":
        (lab / "data.csv").write_text(
            (lab / "data.csv").read_text().replace("1.389", "1.399", 1) + "\n"
        )
    elif change in {"definition", "direction", "unit"}:
        spec["metrics"]["mse"][change] = "maximize" if change == "direction" else "different metric"
    elif change == "primary":
        spec["primary_metric"] = "mae"
    else:
        spec["group"] = "another-study"
    candidate = await measured_run(jobs, "quadratic", spec=spec)
    result = await Experiments(registry).compare(
        {
            "baseline_job_ids": [baseline["job_id"]],
            "candidate_job_ids": [candidate["job_id"]],
        }
    )
    assert result["comparable"] is False and "differ" in result["reason"]


@pytest.mark.parametrize("file", ["metrics.json", "predictions.json", "data.csv"])
async def test_capture_verifier_rejects_tampered_files(registry, lab, file):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    job = await measured_run(jobs)
    work = registry.store.root / "jobs" / job["job_id"] / "work"
    (work / file).write_bytes((work / file).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed|no longer matches"):
        verify_experiment(registry.store, job)


@pytest.mark.parametrize(
    "content",
    ['{"mse":true,"mae":0}', '{"mse":NaN,"mae":0}', '{"mae":0}', '{"mse":0,"mse":1,"mae":0}', "[]"],
)
async def test_completed_process_without_valid_metrics_is_not_measured_evidence(
    registry, lab, content
):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    script = f"import pathlib; pathlib.Path('metrics.json').write_text({content!r}); pathlib.Path('predictions.json').write_text('{{}}')"
    job = await measured_run(jobs, script=script)
    assert job["status"] == "completed"
    assert job["experimental_results"]["status"] == "invalid"
    with pytest.raises(ValueError, match="no verified"):
        verify_experiment(registry.store, job)


async def test_failed_process_with_real_metrics_is_not_accepted(registry, lab):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    job = await measured_run(
        jobs,
        script="import pathlib; pathlib.Path('metrics.json').write_text('{\"mse\":0,\"mae\":0}'); raise SystemExit(1)",
    )
    assert job["status"] == "failed"
    assert job["experimental_results"]["status"] == "invalid"


async def test_metrics_output_must_be_new_and_stay_inside_snapshot(registry, lab):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    (lab / "metrics.json").write_text('{"mse":0,"mae":0}')
    with pytest.raises(ValueError, match="already exists"):
        await measured_run(jobs)
    assert not registry.store.records("jobs")
    assert not list((registry.store.root / "jobs").iterdir())
    (lab / "metrics.json").unlink()
    job = await measured_run(
        jobs, script="import pathlib; pathlib.Path('metrics.json').symlink_to('/etc/passwd')"
    )
    assert job["experimental_results"]["status"] == "invalid"
    assert "symlink" in job["experimental_results"]["detail"]


async def test_single_and_unmatched_seeds_are_descriptive_and_flagged(registry, lab):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    baseline = await measured_run(jobs, seed=7)
    candidate = await measured_run(jobs, "quadratic", seed=19)
    args = {"baseline_job_ids": [baseline["job_id"]], "candidate_job_ids": [candidate["job_id"]]}
    result = await Experiments(registry).compare(args)
    assert result["comparable"] and len(result["warnings"]) == 2
    assert result["metrics"]["mse"]["paired_deltas"] == {}
    duplicate_seed = await measured_run(jobs, "quadratic", seed=19)
    result = await Experiments(registry).compare(
        {
            **args,
            "candidate_job_ids": [candidate["job_id"], duplicate_seed["job_id"]],
        }
    )
    assert not result["comparable"] and "Duplicate seeds" in result["reason"]
    with pytest.raises(ValidationError, match="only once"):
        await Experiments(registry).compare(
            {
                **args,
                "candidate_job_ids": [baseline["job_id"]],
            }
        )


async def test_request_id_includes_normalized_experiment_spec(registry, lab):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    args = Run(
        argv=[sys.executable, "run.py", "--variant", "baseline", "--seed", "7"],
        cwd="lab",
        timeout_seconds=5,
        request_id="measured-run",
        spec=lab_spec(),
    ).model_dump()
    original = await jobs.start(args)
    await jobs.tasks[original["job_id"]]
    assert (await jobs.start(args))["deduplicated"]
    changed = copy.deepcopy(args)
    changed["spec"]["seed"] = 9
    with pytest.raises(ValueError, match="different experiment arguments"):
        await jobs.start(changed)


@pytest.mark.parametrize(
    "path", ["../metrics.json", "/metrics.json", "out/../metrics.json", ".env", "out/private.key"]
)
def test_spec_rejects_private_or_traversing_output_paths(path):
    spec = lab_spec()
    spec["metrics_file"] = path
    with pytest.raises(ValidationError, match="relative file path"):
        ExperimentSpec.model_validate(spec)


def test_spec_requires_metric_definition_and_disjoint_paths():
    spec = lab_spec()
    spec["primary_metric"] = "unknown"
    with pytest.raises(ValidationError, match="declared metric"):
        ExperimentSpec.model_validate(spec)
    spec = lab_spec()
    spec["metrics_file"] = "data.csv"
    with pytest.raises(ValidationError, match="distinct"):
        ExperimentSpec.model_validate(spec)


def test_register_exposes_comparison_and_export_effects(registry):
    Jobs(registry).register()
    assert registry.tools["compare_experiments"].effect == "read"
    assert registry.tools["list_experiments"].effect == "read"
    assert registry.tools["report_export"].effect == "write"
    assert "spec" in registry.tools["run_experiment"].schema["properties"]
