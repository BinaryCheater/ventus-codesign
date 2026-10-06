"""Time the frozen pre-optimization v7 frontend without profiling overhead."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent
repository = root.parents[2]
sys.path.insert(0, str(root / "model-before-optimization"))
import codesign  # noqa: E402

codesign.__path__.append(str(repository / "codesign"))
from codesign.ventus.transformer_cli import run  # noqa: E402

run(root / "small-s16-before-optimization", budget=90)
