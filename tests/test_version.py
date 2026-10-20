import re
from pathlib import Path

import libraryan


def test_version_matches_pyproject():
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert re.search(r'^version = "(.+)"$', text, re.M).group(1) == libraryan.__version__ == "0.3.1"
