"""`radmatch-dashboard` — start Streamlit on the packaged RadMatch Evaluation Dashboard.

Streamlit runs a *script path*, not a module, so the console script resolves
`Home.py` inside the installed package and hands it to `streamlit run`. Multipage
navigation then discovers `pages/` next to it, which works from site-packages as well
as from a source checkout.

Any extra arguments are forwarded to Streamlit, e.g.

    radmatch-dashboard --server.port 8600
"""

from __future__ import annotations

import sys
from pathlib import Path

HOME_SCRIPT = Path(__file__).resolve().parent / "Home.py"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError:
        print(
            "The dashboard needs Streamlit. Install the extra:\n\n    pip install 'radmatch[dashboard]'\n",
            file=sys.stderr,
        )
        return 1

    sys.argv = ["streamlit", "run", str(HOME_SCRIPT), *args]
    return streamlit_cli.main()


if __name__ == "__main__":
    sys.exit(main())
