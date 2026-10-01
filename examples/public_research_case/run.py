"""Actual CPU-only LIBSVM author-code case; downloads require explicit --download."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import shutil
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

PROVENANCE = json.loads(Path(__file__).with_name("provenance.json").read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def prepare(directory, download=False):
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in PROVENANCE["files"].items():
        path = directory / name
        if path.is_file() and digest(path.read_bytes()) == expected:
            continue
        if not download:
            raise ValueError(f"Missing or altered pinned file {name}; use --download explicitly")
        url = "https://raw.githubusercontent.com/cjlin1/libsvm/" + PROVENANCE["commit"] + "/" + name
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000 or digest(data) != expected:
            raise ValueError(f"Pinned SHA-256 verification failed: {name}")
        path.write_bytes(data)
    compiler = shutil.which("c++")
    if not compiler:
        raise ValueError("A C++ compiler is required for this developer example")
    build_commands = []
    for tool in ["svm-train", "svm-predict"]:
        argv = [
            compiler,
            "-O2",
            "-x",
            "c++",
            str(directory / (tool + ".c")),
            str(directory / "svm.cpp"),
            "-o",
            str(directory / tool),
        ]
        subprocess.run(argv, check=True, capture_output=True, timeout=120)
        build_commands.append(argv)
    return {"compiler": compiler, "commands": build_commands}


def split_indices(lines, seed):
    """Stratified 70/15/15 split; tune only on validation, never on test labels."""
    groups = {}
    for index, line in enumerate(lines):
        groups.setdefault(line.split()[0], []).append(index)
    result = {"train": [], "validation": [], "test": []}
    rng = random.Random(seed)
    for label in sorted(groups):
        values = list(groups[label])
        rng.shuffle(values)
        train_end = int(len(values) * 0.7)
        validation_end = train_end + int(len(values) * 0.15)
        result["train"].extend(values[:train_end])
        result["validation"].extend(values[train_end:validation_end])
        result["test"].extend(values[validation_end:])
    return {key: sorted(values) for key, values in result.items()}


def classification_metrics(labels, predictions):
    if not labels or len(labels) != len(predictions):
        raise ValueError("Prediction count must match a nonempty evaluation split")
    accuracy = sum(left == right for left, right in zip(labels, predictions)) / len(labels)
    recalls = []
    for label in sorted(set(labels)):
        indexes = [index for index, value in enumerate(labels) if value == label]
        recalls.append(sum(predictions[index] == label for index in indexes) / len(indexes))
    return {"accuracy": accuracy, "balanced_accuracy": statistics.mean(recalls)}


def evaluate(directory, sources, lines, splits, cost, gamma, name):
    model = directory / (name + ".model")
    train = [
        str(sources / "svm-train"),
        "-q",
        "-s",
        "0",
        "-t",
        "2",
        "-c",
        str(cost),
        "-g",
        str(gamma),
        str(directory / "train.svm"),
        str(model),
    ]
    subprocess.run(train, check=True, capture_output=True, timeout=30)
    results, commands = {}, [train]
    for split in ["validation", "test"]:
        predictions_file = directory / (name + "-" + split + ".predictions")
        predict = [
            str(sources / "svm-predict"),
            str(directory / (split + ".svm")),
            str(model),
            str(predictions_file),
        ]
        process = subprocess.run(predict, check=True, capture_output=True, text=True, timeout=30)
        predictions = [float(value) for value in predictions_file.read_text().splitlines()]
        labels = [float(lines[index].split()[0]) for index in splits[split]]
        results[split] = {
            **classification_metrics(labels, predictions),
            "predictions_sha256": digest(predictions_file.read_bytes()),
            "stdout": process.stdout.strip(),
        }
        commands.append(predict)
    return results, commands


def run_variant(output, sources, variant, seed):
    directory = output / f"{variant}-{seed}"
    directory.mkdir(parents=True, exist_ok=True)
    data = (sources / "heart_scale").read_bytes()
    lines = data.decode().splitlines()
    if len(lines) != PROVENANCE["dataset"]["rows"]:
        raise ValueError("Unexpected public dataset row count")
    splits = split_indices(lines, seed)
    for name, indexes in splits.items():
        (directory / (name + ".svm")).write_text(
            "\n".join(lines[index] for index in indexes) + "\n"
        )
    write_json(directory / "split.json", splits)
    selected = (1.0, 1 / 13)
    validation_grid, commands = [], []
    if variant == "tuned":
        # Each candidate's test output is deliberately not computed during selection.
        for cost in [0.1, 1.0, 10.0, 100.0]:
            for gamma in [0.01, 1 / 13, 0.1, 1.0]:
                model = directory / "grid.model"
                train = [
                    str(sources / "svm-train"),
                    "-q",
                    "-s",
                    "0",
                    "-t",
                    "2",
                    "-c",
                    str(cost),
                    "-g",
                    str(gamma),
                    str(directory / "train.svm"),
                    str(model),
                ]
                predict = [
                    str(sources / "svm-predict"),
                    str(directory / "validation.svm"),
                    str(model),
                    str(directory / "grid.predictions"),
                ]
                subprocess.run(train, check=True, capture_output=True, timeout=30)
                subprocess.run(predict, check=True, capture_output=True, timeout=30)
                labels = [float(lines[index].split()[0]) for index in splits["validation"]]
                predictions = [
                    float(value)
                    for value in (directory / "grid.predictions").read_text().splitlines()
                ]
                score = classification_metrics(labels, predictions)["accuracy"]
                validation_grid.append({"C": cost, "gamma": gamma, "validation_accuracy": score})
                commands.extend([train, predict])
        chosen = max(validation_grid, key=lambda row: row["validation_accuracy"])
        selected = chosen["C"], chosen["gamma"]
    elif variant == "negative":
        selected = 0.001, 10.0
    results, final_commands = evaluate(directory, sources, lines, splits, *selected, "final")
    commands.extend(final_commands)
    record = {
        "variant": variant,
        "seed": seed,
        "parameters": {"C": selected[0], "gamma": selected[1], "kernel": "rbf"},
        "metrics": {key: results["test"][key] for key in ["accuracy", "balanced_accuracy"]},
        "validation": results["validation"],
        "validation_grid": validation_grid,
        "test": results["test"],
        "model_sha256": digest((directory / "final.model").read_bytes()),
        "dataset_sha256": digest(data),
        "split_sha256": digest((directory / "split.json").read_bytes()),
        "split_counts": {name: len(values) for name, values in splits.items()},
        "commands": commands,
    }
    write_json(directory / "result.json", record)
    write_json(directory / "metrics.json", record["metrics"])
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument(
        "--sources", type=Path, help="Existing pinned author files; verified before compiling"
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--variant", choices=["all", "baseline", "tuned", "negative"], default="all"
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    args = parser.parse_args()
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        parser.error("Choose distinct seeds")
    output = args.workdir.resolve()
    sources = (args.sources or output / "sources").resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    build = prepare(sources, args.download)
    variants = ["baseline", "tuned", "negative"] if args.variant == "all" else [args.variant]
    runs = [
        run_variant(output, sources, variant, seed) for variant in variants for seed in args.seeds
    ]
    summary = {}
    for variant in variants:
        scores = [run["metrics"]["accuracy"] for run in runs if run["variant"] == variant]
        summary[variant] = {
            "n": len(scores),
            "accuracy_mean": statistics.mean(scores),
            "accuracy_stdev": statistics.stdev(scores) if len(scores) > 1 else None,
        }
    result = {
        "kind": "actual-public-author-code-cpu-case",
        "provenance": PROVENANCE,
        "runs": runs,
        "summary": summary,
        "build": build,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "elapsed_seconds": time.monotonic() - started,
        "model_api_calls": 0,
        "interpretation": "Descriptive differences over small stratified splits; no significance, novelty or full-paper reproduction claim.",
    }
    write_json(output / "public-case-results.json", result)
    print(json.dumps({"results": str(output / "public-case-results.json"), "summary": summary}))


if __name__ == "__main__":
    main()
