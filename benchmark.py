"""Summarize matched ERP benchmark runs from an operator's QA log."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from statistics import median


METHODS = ("screen_cua", "fixed_rpa", "vamp_replay")
LAYOUTS = ("v1", "v2")
OUTCOMES = ("verified", "blocked_before_input", "failed")


def summarize(document):
    setup = document["setup"]
    for key in ("fixture_commit", "browser", "guest_os", "resolution", "timing_boundary"):
        if not setup.get(key):
            raise ValueError(f"Missing shared setup field: {key}.")
    groups = {(method, layout): {} for method in METHODS for layout in LAYOUTS}
    for run in document["runs"]:
        group = groups.get((run["method"], run["layout"]))
        trial = run["trial"]
        elapsed = run["elapsed_seconds"]
        tokens = run["vision_tokens"]
        if (
            group is None
            or not isinstance(trial, str) or not trial.strip() or trial in group
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0
            or (tokens is not None and (type(tokens) is not int or tokens < 0))
            or run["outcome"] not in OUTCOMES
            or not isinstance(run["evidence"], str) or not run["evidence"].strip()
        ):
            raise ValueError("Invalid or duplicate benchmark observation.")
        group[trial] = run
    rounds = set(groups[(METHODS[0], LAYOUTS[0])])
    if not rounds or any(set(group) != rounds for group in groups.values()):
        raise ValueError("Record each method and layout for the same set of trial IDs.")

    comparison = []
    for (method, layout), group in groups.items():
        runs = list(group.values())
        token_counts = [run["vision_tokens"] for run in runs if run["vision_tokens"] is not None]
        comparison.append({
            "method": method,
            "layout": layout,
            "runs": len(runs),
            "median_seconds": median(run["elapsed_seconds"] for run in runs),
            "median_vision_tokens": median(token_counts) if len(token_counts) == len(runs) else None,
            "vision_token_samples": len(token_counts),
            "outcomes": dict(Counter(run["outcome"] for run in runs)),
        })
    return {"setup": setup, "comparison": comparison}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.observations.read_text(encoding="utf-8-sig"))
        summary = summarize(document)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
