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
SETUP_FIELDS = ("fixture_commit", "browser", "guest_os", "resolution", "timing_boundary")


def observation_plan(trials):
    return {
        "setup": dict.fromkeys(SETUP_FIELDS, ""),
        "runs": [
            {"trial": trial, "method": method, "layout": layout, "elapsed_seconds": None,
             "vision_tokens": None, "outcome": None, "evidence": ""}
            for trial in trials for layout in LAYOUTS for method in METHODS
        ],
    }


def summarize(document):
    setup = document["setup"]
    for key in SETUP_FIELDS:
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
        outcome_times = {outcome: [run["elapsed_seconds"] for run in runs if run["outcome"] == outcome]
                         for outcome in OUTCOMES}
        comparison.append({
            "method": method,
            "layout": layout,
            "runs": len(runs),
            "median_seconds": median(run["elapsed_seconds"] for run in runs),
            "median_seconds_by_outcome": {
                outcome: median(times) for outcome, times in outcome_times.items() if times
            },
            "median_vision_tokens": median(token_counts) if len(token_counts) == len(runs) else None,
            "vision_token_samples": len(token_counts),
            "outcomes": dict(Counter(run["outcome"] for run in runs)),
        })
    return {"setup": setup, "comparison": comparison}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("observations", type=Path, nargs="?")
    inputs.add_argument("--plan", metavar="TRIAL", nargs="+",
                        help="Print a blank matched observation sheet for these trial IDs.")
    parser.add_argument("--check-evidence", action="store_true",
                        help="Require each evidence path to point to a nonempty local file.")
    args = parser.parse_args()
    if args.plan is not None:
        if args.check_evidence or any(not trial.strip() for trial in args.plan) or len(set(args.plan)) != len(args.plan):
            parser.error("--plan requires distinct nonempty trial IDs and cannot be used with --check-evidence.")
        print(json.dumps(observation_plan(args.plan), indent=2, ensure_ascii=False))
        return
    try:
        document = json.loads(args.observations.read_text(encoding="utf-8-sig"))
        summary = summarize(document)
        if args.check_evidence:
            for run in document["runs"]:
                report = args.observations.parent / run["evidence"]
                if not report.is_file() or report.stat().st_size == 0:
                    raise ValueError(f"Missing or empty evidence for {run['trial']}/{run['method']}/{run['layout']}: {report}")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
