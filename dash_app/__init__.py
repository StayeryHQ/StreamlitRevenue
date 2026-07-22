# Put the src/ layout package on the path so `revenueblindspots` imports work
# whether the app is launched via `python -m dash_app.app` or gunicorn.
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
