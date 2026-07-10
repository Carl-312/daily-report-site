from __future__ import annotations

import pytest

from sources.syft import SyftSource


def test_missing_syft_configuration_is_not_normal_empty_result() -> None:
    with pytest.raises(ValueError, match="requires web_app_url and secret_key"):
        SyftSource().fetch()
