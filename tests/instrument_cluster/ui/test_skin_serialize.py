"""Skin serializer round-trips (the editor's save path).

``emit_skin_module(scale=None)`` must reproduce a skin *verbatim* — a save
that silently rounded or snapped hand-tuned values would corrupt design
work. The scaled path is exercised by the seed generator's own usage.
"""

import importlib.util
import sys

import pytest

from instrument_cluster.ui.skins import (
    SKIN_800,
    SKIN_1024,
    SKIN_1280,
    set_skin_override,
)
from instrument_cluster.ui.skins.serialize import emit_skin_module


@pytest.mark.parametrize(
    "skin", [SKIN_1280, SKIN_1024, SKIN_800], ids=lambda s: s.name
)
def test_verbatim_round_trip(skin, tmp_path):
    text = emit_skin_module(skin, docstring="round-trip test emission")
    module_path = tmp_path / f"skin_rt_{skin.width}.py"
    module_path.write_text(text)

    # The emitted module does `from .schema import ...`; import it as if it
    # lived inside the skins package.
    spec = importlib.util.spec_from_file_location(
        f"instrument_cluster.ui.skins.skin_rt_{skin.width}", module_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        rebuilt = getattr(module, f"SKIN_{skin.width}")
    finally:
        del sys.modules[spec.name]

    assert rebuilt == skin


def test_strings_emit_with_double_quotes():
    # Family names must be written "..." like the hand-written skin files —
    # repr()'s single quotes would churn every family line on the first
    # editor save of an otherwise-untouched skin.
    text = emit_skin_module(SKIN_800)
    assert 'gear_family="D_DIN_EXP_BOLD",' in text
    assert 'name="800x480",' in text
    body = text.split("SKIN_", 1)[1]
    assert "'" not in body, "single-quoted string leaked into the emission"


def test_skin_override_hook(force_profile):
    from dataclasses import replace

    from instrument_cluster.ui.skins import active_skin, reset_skin_overrides

    edited = replace(SKIN_800, name="800x480-edited")
    try:
        set_skin_override(edited)
        with force_profile("waveshare_5"):
            assert active_skin() is edited
    finally:
        reset_skin_overrides()
    with force_profile("waveshare_5"):
        assert active_skin() == SKIN_800
