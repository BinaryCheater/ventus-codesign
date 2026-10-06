"""Replay old LayerNorm with its frozen v6 package and current shared imports."""

import runpy
import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[3]
analysis = repository / "analysis/ventus_flow_20261006"
sys.path.insert(0, str(analysis / "performance-v6/model-final"))
import codesign  # noqa: E402

codesign.__path__.append(str(repository / "codesign"))
sys.path.insert(0, str(analysis / "layernorm_rtl_20261006"))
sys.argv = ["check.py", "--verify"]
runpy.run_path(str(analysis / "layernorm_rtl_20261006/check.py"), run_name="__main__")
