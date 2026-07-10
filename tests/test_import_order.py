from __future__ import annotations

import subprocess
import sys


def test_sources_and_utils_import_without_circular_dependency() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from sources.base import Article; "
                "from sources import Article as RegisteredArticle; "
                "from utils.run_contracts import RunDeadlineExceeded; "
                "assert Article is RegisteredArticle"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
