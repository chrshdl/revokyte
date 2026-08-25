"""build() must depend on the image, and nothing else.

This is what makes /run/instrument-cluster/unhealthy meaningful. The OTA
health check withholds `rauc status mark-good` while that marker is non-empty,
so a view that fails to build costs the device three boot attempts and a
rollback. That is the right cure for a defect baked into the image — and
exactly the wrong one for a corrupt config or an unreadable licence file,
which live on /data and survive the rollback untouched. Roll back for those
and you lose the update *and* keep the fault.

So the rule is structural, not a matter of care: construction reads fonts,
skins, icons, `is_raspberry_pi()`, which feeds exist and which extensions are
installed — all image-resident. Every mutable value is bound by reset().
"""

import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.ui.views.registry import ViewRegistry, core_views


@pytest.fixture
def unusable_data(tmp_path, monkeypatch):
    """Make every /data-backed source raise.

    Deliberately harsher than a corrupt config.json, which ConfigManager
    already absorbs by falling back to defaults — that would let this test
    pass without proving anything. Raising is what a genuinely unreadable
    licence file or an exotic pydantic failure looks like, and no view may
    be taking that risk at build time.
    """
    def _unreadable(*a, **kw):
        raise RuntimeError("/data is unreadable")

    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(_unreadable))

    # get_ip_prefill() reads the live network interface; a device on a bench
    # with no link must not make a screen unbuildable either.
    import instrument_cluster.ui.views.enter_ip_view as enter_ip

    monkeypatch.setattr(enter_ip, "get_ip_prefill", _unreadable)
    yield
    ConfigManager.reset()


@pytest.mark.parametrize("cls", core_views(), ids=lambda c: c.__name__)
def test_a_view_builds_with_data_unusable(cls, unusable_data):
    view = cls()
    view.build()


def test_the_registry_reports_no_fault_when_only_data_is_broken(
    unusable_data, tmp_path, monkeypatch
):
    """The whole point: broken /data must not look like a broken image."""
    from instrument_cluster.core.system import unhealthy

    marker = str(tmp_path / "unhealthy")
    monkeypatch.setattr(unhealthy, "MARKER", marker)

    registry = ViewRegistry()
    registry.preload(core_views())

    assert registry.failed == ()
    assert unhealthy.reasons(marker) == [], (
        "a corrupt config triggered an OTA rollback that cannot fix it"
    )


def test_an_extension_callable_is_not_run_while_building(tmp_path, monkeypatch):
    """button_text may be a callable that reaches /data — Pro's licence row
    reads its tier that way. Building must not evaluate it."""
    from instrument_cluster.extensions import SetupEntry
    from instrument_cluster.extensions import runtime as extensions
    from instrument_cluster.ui.views.setup_view import SetupView

    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()

    def explode():
        raise RuntimeError("licence file unreadable")

    entry = SetupEntry(
        icon="",
        label="Licence",
        button_text=explode,
        make_state=lambda sm: None,
    )
    extensions.setup_entries.append(entry)
    try:
        SetupView().build()          # must not raise
    finally:
        extensions.setup_entries.remove(entry)
