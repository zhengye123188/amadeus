"""Offline regression lab: a synthetic mechanism fixture, not a reproduced paper."""

import argparse
import csv
import json
import random
from pathlib import Path


def fit_polynomial(rows, degree):
    width = degree + 1
    matrix = [
        [sum(x ** (i + j) for x, _ in rows) for j in range(width)]
        + [sum(y * x**i for x, y in rows)]
        for i in range(width)
    ]
    for column in range(width):
        pivot = max(range(column, width), key=lambda index: abs(matrix[index][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        if abs(divisor) < 1e-12:
            raise ValueError("Singular training matrix")
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(width):
            if row != column:
                multiplier = matrix[row][column]
                matrix[row] = [
                    left - multiplier * right for left, right in zip(matrix[row], matrix[column])
                ]
    return [row[-1] for row in matrix]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["baseline", "quadratic", "negative"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    with Path("data.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    train = [(float(row["x"]), float(row["y"])) for row in rows if row["split"] == "train"]
    test = [(float(row["x"]), float(row["y"])) for row in rows if row["split"] == "test"]
    selected = random.Random(args.seed).sample(train, 40)
    if args.variant == "negative":
        coefficients = [0.0]
    else:
        coefficients = fit_polynomial(selected, 1 if args.variant == "baseline" else 2)
    predictions = [
        sum(value * x**power for power, value in enumerate(coefficients)) for x, _ in test
    ]
    errors = [prediction - row[1] for prediction, row in zip(predictions, test)]
    metrics = {
        "mse": sum(error**2 for error in errors) / len(errors),
        "mae": sum(abs(error) for error in errors) / len(errors),
    }
    Path("metrics.json").write_text(json.dumps(metrics))
    Path("predictions.json").write_text(
        json.dumps(
            {
                "coefficients": coefficients,
                "predictions": predictions,
                "seed": args.seed,
                "variant": args.variant,
            }
        )
    )
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
