"""Query the frozen table without RTL generation or synthesis."""

import argparse
import json
from pathlib import Path

from .model import evaluate_cost
from .structural import evaluate_structural_cost, factorized_cost_coefficients, structural_target
from .unified import LEGACY_POLICY, POLICY, evaluate_unified_area


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hardware", type=Path, help="Hardware field overrides JSON")
    parser.add_argument(
        "--model",
        choices=["v1", "structural-v2", "structural-v2.1", "unified-v1", "unified-v2"],
        default="v1",
    )
    parser.add_argument("--precisions", nargs="+", default=["fp32"])
    parser.add_argument(
        "--coefficients", action="store_true", help="module-level structural MIP coefficients"
    )
    args = parser.parse_args()
    overrides = json.loads(args.hardware.read_text()) if args.hardware else {}
    if args.model.startswith("unified-"):
        if args.coefficients or args.precisions != ["fp32"]:
            parser.error(
                "unified-v1 fixes precision capabilities; use add_unified_area_constraints for MIP"
            )
        result = evaluate_unified_area(
            overrides, policy_path=LEGACY_POLICY if args.model == "unified-v1" else POLICY
        )
    elif args.model == "v1":
        if args.coefficients or args.precisions != ["fp32"]:
            parser.error("precision capabilities and factorized coefficients require structural-v2")
        result = evaluate_cost(overrides)
    else:
        target = structural_target(
            args.precisions,
            version="ventus-" + args.model.replace("structural-", "structural-cost-"),
        )
        result = (
            factorized_cost_coefficients(target)
            if args.coefficients
            else evaluate_structural_cost(overrides, target)
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
