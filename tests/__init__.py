"""Tests for radmatch package."""

import sys
from pathlib import Path

# Ensure src/ is in path for imports
_PROJECT_ROOT = Path(__file__).parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
