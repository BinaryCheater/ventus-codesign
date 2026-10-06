"""Query the frozen table without RTL generation or synthesis."""

import argparse
import json
from pathlib import Path

from .model import evaluate_cost


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hardware", type=Path, help="Hardware field overrides JSON")
    args = parser.parse_args()
    overrides = json.loads(args.hardware.read_text()) if args.hardware else {}
    print(json.dumps(evaluate_cost(overrides), indent=2))


if __name__ == "__main__":
    main()
