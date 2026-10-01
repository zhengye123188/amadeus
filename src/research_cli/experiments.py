"""Measured experiment records and descriptive, provenance-checked comparisons."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import shutil
import statistics
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from research_cli.storage import encode
from research_cli.tools import Args

VALIDATION_SCOPE = (
    "Generated output, finite metrics and recorded provenance were verified. "
    "This does not establish scientific validity or confirm a hypothesis."
)


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} or part.startswith(".") for part in value.split("/"))
        or any(part in {"research.toml", "id_rsa", "id_ed25519"} for part in path.parts)
        or value.endswith((".pem", ".key"))
    ):
        raise ValueError("Expected a non-private relative file path without traversal")
    return value


class MetricSpec(Args):
    direction: Literal["maximize", "minimize"]
    unit: str = Field(default="score", min_length=1, max_length=80)
    definition: str = Field(min_length=3, max_length=1000)


class DatasetSpec(Args):
    dataset_id: str = Field(min_length=1, max_length=200)
    files: list[str] = Field(min_length=1, max_length=50)
    split: str = Field(min_length=1, max_length=200)
    protocol: str = Field(min_length=3, max_length=2000)

    @field_validator("files")
    @classmethod
    def check_files(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Dataset files must be unique")
        return [relative_path(value) for value in values]


class ExperimentSpec(Args):
    group: str = Field(min_length=1, max_length=200)
    variant: str = Field(min_length=1, max_length=200)
    dataset: DatasetSpec
    seed: int = Field(ge=0, le=2**32 - 1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=100)
    metrics: dict[str, MetricSpec] = Field(min_length=1, max_length=50)
    primary_metric: str = Field(min_length=1, max_length=100)
    metrics_file: str = "metrics.json"
    artifacts: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("metrics_file")
    @classmethod
    def check_metrics_file(cls, value):
        return relative_path(value)

    @field_validator("artifacts")
    @classmethod
    def check_artifacts(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Artifacts must be unique")
        return [relative_path(value) for value in values]

    @model_validator(mode="after")
    def check_spec(self):
        if self.primary_metric not in self.metrics:
            raise ValueError("primary_metric must be a declared metric")
        if any(not key or len(key) > 100 for key in self.metrics):
            raise ValueError("Metric names must contain 1–100 characters")
        if len(encode(self.parameters)) > 16000:
            raise ValueError("Experiment parameters exceed 16000 characters")
        outputs = [self.metrics_file, *self.artifacts]
        if len(set(outputs)) != len(outputs) or set(outputs) & set(self.dataset.files):
            raise ValueError("Dataset and generated output paths must be distinct")
        return self


class CompareExperiments(Args):
    baseline_job_ids: list[str] = Field(min_length=1, max_length=30)
    candidate_job_ids: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def distinct_runs(self):
        values = [*self.baseline_job_ids, *self.candidate_job_ids]
        if len(set(values)) != len(values):
            raise ValueError("A job may occur only once in a comparison")
        return self


class ReportExport(CompareExperiments):
    format: Literal["markdown", "json"] = "markdown"
    title: str = Field(default="Experiment comparison", min_length=1, max_length=200)


class ListExperiments(Args):
    group: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=30, ge=1, le=100)


def bounded_file(work: Path, relative: str, limit=20_000_000) -> Path:
    """Reject symlinks and special/hard-linked files, including intermediate symlinks."""
    relative_path(relative)
    if not work.is_dir() or any(
        directory.is_symlink()
        for directory in (work, work.parent, work.parent.parent, work.parent.parent.parent)
    ):
        raise ValueError("Experiment storage directories may not be symlinks")
    current = work
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Experiment file is a symlink: {relative}")
    if (
        not current.is_file()
        or not current.resolve().is_relative_to(work.resolve())
        or current.stat().st_nlink != 1
        or current.stat().st_size > limit
    ):
        raise ValueError(f"Expected a bounded regular experiment file: {relative}")
    return current


def fingerprint(work: Path, relative: str, limit=20_000_000) -> dict:
    data = bounded_file(work, relative, limit).read_bytes()
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def dataset_record(work: Path, spec: dict) -> dict:
    files = {path: fingerprint(work, path)["sha256"] for path in sorted(spec["dataset"]["files"])}
    digest = hashlib.sha256(encode(files).encode()).hexdigest()
    return {**spec["dataset"], "files": files, "sha256": digest}


def prepare_experiment(work: Path, spec: dict) -> dict:
    spec = ExperimentSpec.model_validate(spec).model_dump()
    # A copied metrics file is not evidence of a new run. Require fresh output paths.
    for relative in [spec["metrics_file"], *spec["artifacts"]]:
        candidate = work / relative
        if candidate.exists() or candidate.is_symlink():
            raise ValueError(f"Declared output already exists in snapshot: {relative}")
    return dataset_record(work, spec)


def runtime_environment(argv: list[str], backend: str, image=None) -> dict:
    """Record bounded runtime facts without copying environment variables or credentials."""
    return {
        "backend": backend,
        "platform": platform.system(),
        "machine": platform.machine(),
        "python_host_version": platform.python_version(),
        "python_host_executable": sys.executable,
        "launcher": shutil.which(argv[0]) or argv[0],
        "docker_image": image,
        "scope": "Host and configured launcher; target dependencies/hardware need separate review.",
    }


def parse_metrics(work: Path, spec: dict) -> dict[str, float]:
    path = bounded_file(work, spec["metrics_file"], 2_000_000)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON metric key: {key}")
            result[key] = value
        return result

    try:
        content = json.loads(path.read_text(), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("metrics_file must be a UTF-8 JSON object") from exc
    if not isinstance(content, dict):
        raise ValueError("metrics_file must be a JSON object of numeric metrics")
    metrics = {}
    for key in spec["metrics"]:
        value = content.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Declared metric is missing or non-numeric: {key}")
        try:
            measured = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"Declared metric is not finite: {key}") from exc
        if not math.isfinite(measured):
            raise ValueError(f"Declared metric is not finite: {key}")
        metrics[key] = measured
    return metrics


def capture_experiment(store, job: dict) -> dict:
    if job["status"] != "completed" or job.get("exit_code") != 0:
        raise ValueError("Measured results require a completed run with exit code zero")
    spec = ExperimentSpec.model_validate(job.get("spec")).model_dump()
    work = store.root / "jobs" / job["job_id"] / "work"
    dataset = dataset_record(work, spec)
    if dataset != job.get("dataset"):
        raise ValueError("Dataset inputs changed during the run")
    return {
        "status": "verified",
        "metrics": parse_metrics(work, spec),
        "metrics_file": fingerprint(work, spec["metrics_file"], 2_000_000),
        "artifacts": [fingerprint(work, path) for path in spec["artifacts"]],
        "dataset": dataset,
        "verified_at": time.time(),
        "validation_scope": VALIDATION_SCOPE,
    }


def verify_experiment(store, job: dict) -> dict:
    """Recheck completed outputs before citing metrics, reviewing claims or comparing runs."""
    recorded = job.get("experimental_results", {})
    if recorded.get("status") != "verified":
        raise ValueError("Job has no verified generated experiment metrics")
    actual = capture_experiment(store, job)
    for field in ("metrics", "metrics_file", "artifacts", "dataset"):
        if actual[field] != recorded.get(field):
            raise ValueError(f"Experiment {field} no longer matches the captured output")
    return recorded


def comparison_key(job: dict) -> dict:
    spec = job["spec"]
    return {
        "group": spec["group"],
        "dataset": job["dataset"],
        "metrics": spec["metrics"],
        "primary_metric": spec["primary_metric"],
    }


def run_summary(job: dict) -> dict:
    return {
        "job_id": job["job_id"],
        "variant": job["spec"]["variant"],
        "seed": job["spec"]["seed"],
        "parameters": job["spec"]["parameters"],
        "metrics": job["experimental_results"]["metrics"],
        "metrics_file": job["experimental_results"]["metrics_file"],
        "artifacts": job["experimental_results"]["artifacts"],
        "snapshot_sha256": job["snapshot_sha256"],
        "environment": job.get("environment"),
    }


class Experiments:
    def __init__(self, registry):
        self.registry, self.store = registry, registry.store

    async def compare(self, args):
        args = CompareExperiments.model_validate(args).model_dump()
        groups = [
            [self.store.get("jobs", jid) for jid in args[key]]
            for key in ("baseline_job_ids", "candidate_job_ids")
        ]
        jobs = [job for group in groups for job in group]
        for job in jobs:
            verify_experiment(self.store, job)
        reference = comparison_key(jobs[0])
        mismatches = [job["job_id"] for job in jobs if comparison_key(job) != reference]
        if mismatches:
            return {
                "comparable": False,
                "reason": "Dataset identity/hash/files/split/protocol, group or metric configuration differ",
                "mismatched_job_ids": mismatches,
                "conditions": {job["job_id"]: comparison_key(job) for job in jobs},
                "validation_scope": VALIDATION_SCOPE,
            }
        if any(len({j["spec"]["seed"] for j in group}) != len(group) for group in groups):
            return {
                "comparable": False,
                "reason": "Duplicate seeds within a variant would double-count a replicate",
                "validation_scope": VALIDATION_SCOPE,
            }
        if any(len({j["spec"]["variant"] for j in group}) != 1 for group in groups):
            return {"comparable": False, "reason": "Each comparison side must contain one variant"}
        if any(len({encode(j["spec"]["parameters"]) for j in group}) != 1 for group in groups):
            return {
                "comparable": False,
                "reason": "Parameters must remain fixed across replicates within each variant",
            }
        seeds = [{j["spec"]["seed"] for j in group} for group in groups]
        warnings = []
        if min(map(len, groups)) < 2:
            warnings.append(
                "At least one variant has a single run; variability cannot be estimated"
            )
        if seeds[0] != seeds[1]:
            warnings.append(
                "Seed sets differ; use matched repeated seeds for a stronger comparison"
            )
        environments = {encode(job.get("environment")) for job in jobs}
        if len(environments) > 1:
            warnings.append(
                "Recorded environments differ; review comparability of dependencies/hardware"
            )
        metrics = {}
        for name, definition in reference["metrics"].items():
            values = [[j["experimental_results"]["metrics"][name] for j in g] for g in groups]
            baseline_mean, candidate_mean = map(statistics.mean, values)
            delta = candidate_mean - baseline_mean
            directional_delta = delta if definition["direction"] == "maximize" else -delta
            by_seed = [
                {j["spec"]["seed"]: j["experimental_results"]["metrics"][name] for j in g}
                for g in groups
            ]
            metrics[name] = {
                **definition,
                "baseline": {
                    "count": len(values[0]),
                    "mean": baseline_mean,
                    "stdev": statistics.stdev(values[0]) if len(values[0]) > 1 else None,
                    "values": values[0],
                },
                "candidate": {
                    "count": len(values[1]),
                    "mean": candidate_mean,
                    "stdev": statistics.stdev(values[1]) if len(values[1]) > 1 else None,
                    "values": values[1],
                },
                "delta": delta,
                "directional_delta": directional_delta,
                "observed_direction": (
                    "improved"
                    if directional_delta > 0
                    else "worse"
                    if directional_delta < 0
                    else "equal"
                ),
                "paired_deltas": {
                    str(seed): by_seed[1][seed] - by_seed[0][seed]
                    for seed in sorted(seeds[0] & seeds[1])
                },
            }
            summaries = metrics[name]
            numeric = [baseline_mean, candidate_mean, delta, directional_delta]
            numeric += [
                side["stdev"]
                for side in (summaries["baseline"], summaries["candidate"])
                if side["stdev"] is not None
            ]
            numeric += list(summaries["paired_deltas"].values())
            if not all(math.isfinite(value) for value in numeric):
                raise ValueError("Metric comparison exceeds the finite numeric range")
        return {
            "comparable": True,
            "conditions": reference,
            "baseline": [run_summary(j) for j in groups[0]],
            "candidate": [run_summary(j) for j in groups[1]],
            "metrics": metrics,
            "warnings": warnings,
            "interpretation": "Descriptive observed differences; no significance or causal claim is inferred.",
            "validation_scope": VALIDATION_SCOPE,
        }

    async def listing(self, args):
        args = ListExperiments.model_validate(args).model_dump()
        jobs = [j for j in self.store.records("jobs") if j.get("spec")]
        jobs = [j for j in jobs if args["group"] is None or j["spec"]["group"] == args["group"]]
        jobs.sort(key=lambda j: j.get("created", 0), reverse=True)
        return {"experiments": jobs[: args["limit"]], "total": len(jobs)}

    async def export(self, args):
        options = ReportExport.model_validate(args).model_dump()
        result = await self.compare({key: options[key] for key in CompareExperiments.model_fields})
        if options["format"] == "json":
            content = json.dumps(
                {"title": options["title"], **result}, ensure_ascii=False, indent=2
            )
        else:
            content = self.markdown(options["title"], result)
        return {
            **self.store.artifact(content),
            "format": options["format"],
            "comparable": result["comparable"],
            "content": content[:20000],
            "truncated": len(content) > 20000,
        }

    @staticmethod
    def markdown(title, result):
        title = title.replace("\n", " ").replace("\r", " ")
        lines = [f"# {title}", "", VALIDATION_SCOPE, ""]
        if not result["comparable"]:
            lines.extend(
                ["Comparison rejected: " + result["reason"], "", "```json", encode(result), "```"]
            )
            return "\n".join(lines) + "\n"
        lines.extend(
            [
                "| Metric | Baseline mean (n) | Candidate mean (n) | Delta | Observed direction |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for name, metric in result["metrics"].items():
            label = name.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {label} | {metric['baseline']['mean']:.6g} ({metric['baseline']['count']}) "
                f"| {metric['candidate']['mean']:.6g} ({metric['candidate']['count']}) "
                f"| {metric['delta']:.6g} | {metric['observed_direction']} |"
            )
        lines.extend(["", result["interpretation"], ""])
        lines.extend("- " + warning for warning in result["warnings"])
        lines.extend(
            [
                "",
                "## Provenance",
                "",
                "```json",
                json.dumps(result, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
        return "\n".join(lines)

    def register(self):
        self.registry.add(
            "compare_experiments",
            "Verify completed generated metrics and compare matching datasets/protocols/metric definitions. Descriptive differences only; incompatible runs are flagged.",
            CompareExperiments,
            self.compare,
        )
        self.registry.add(
            "list_experiments",
            "List structured experiments, measured output status and provenance, optionally by group.",
            ListExperiments,
            self.listing,
        )
        self.registry.add(
            "report_export",
            "Export a provenance-checked experiment comparison as a Markdown or JSON project artifact. Does not confirm a scientific claim.",
            ReportExport,
            self.export,
            "write",
        )
