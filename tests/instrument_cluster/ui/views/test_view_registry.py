"""ViewRegistry: one instance per class, for the life of the process.

The point of the registry is that screen transitions allocate nothing, so the
tests that matter are the ones about *identity* (the same object comes back)
and about failing open (one unbuildable view must not take the app down).
"""

import pytest

from instrument_cluster.ui.views.base import View
from instrument_cluster.ui.views.registry import ViewRegistry, core_views
from instrument_cluster.ui.views.setup_view import SetupView


class _FakeView(View):
    instances = 0

    def __init__(self):
        type(self).instances += 1
        self.background_color = (0, 0, 0)
        self.built = 0
        self.resets = []

    def build(self):
        self.built += 1

    def reset(self, ctx=None):
        self.resets.append(ctx)

    def draw(self, surface, background):
        return []

    def full_paint(self, surface, background):
        pass


class _Borrower:
    """Stand-in for a State — the registry holds borrowers weakly."""


class _BrokenView(_FakeView):
    def build(self):
        raise RuntimeError("no display, no widgets, no view")


@pytest.fixture
def registry():
    _FakeView.instances = 0
    return ViewRegistry()


def test_acquire_builds_once_and_returns_the_same_instance(registry):
    first = registry.acquire(_FakeView)
    second = registry.acquire(_FakeView)

    assert first is second
    assert _FakeView.instances == 1
    assert first.built == 1


def test_preload_builds_up_front_so_acquire_allocates_nothing(registry):
    registry.preload([_FakeView])
    assert _FakeView.instances == 1

    registry.acquire(_FakeView)
    assert _FakeView.instances == 1, "acquire() must never construct"


def test_a_view_that_cannot_build_fails_open(registry):
    # The dashboard must still come up; the owning state degrades instead.
    assert registry.acquire(_BrokenView) is None
    assert _BrokenView in registry.failed


def test_a_failed_view_is_not_retried_on_every_visit(registry):
    _BrokenView.instances = 0
    registry.acquire(_BrokenView)
    registry.acquire(_BrokenView)
    assert _BrokenView.instances == 1


def test_a_state_with_no_view_class_gets_none(registry):
    assert registry.acquire(None) is None


def test_reacquiring_after_release_is_not_a_double_borrow(registry, caplog):
    first, second = _Borrower(), _Borrower()

    registry.acquire(_FakeView, borrower=first)
    registry.release(_FakeView, borrower=first)
    with caplog.at_level("ERROR"):
        registry.acquire(_FakeView, borrower=second)

    assert "still borrowed" not in caplog.text


def test_two_live_borrowers_of_one_view_are_reported(registry, caplog):
    # Two states sharing one view instance would corrupt each other's
    # screen. Logged, not raised: StateManager swallows exceptions from
    # state callbacks, so a raise would blank the screen instead.
    first, second = _Borrower(), _Borrower()

    registry.acquire(_FakeView, borrower=first)
    with caplog.at_level("ERROR"):
        registry.acquire(_FakeView, borrower=second)

    assert "still borrowed" in caplog.text


def test_clear_drops_everything(registry):
    registry.acquire(_FakeView)
    registry.acquire(_BrokenView)
    registry.clear()

    assert registry.built == ()
    assert registry.failed == ()


def test_every_core_view_builds_and_resets():
    # The budget this refactor spends: eight views held for the process.
    # A new screen shows up here as a reviewable change, not a surprise.
    registry = ViewRegistry()
    classes = core_views()
    assert len(classes) == 8
    assert SetupView in classes

    registry.preload(classes)
    assert registry.failed == (), "every shipped view must build headless"
    assert len(registry.built) == 8

    for cls in classes:
        registry.acquire(cls).reset(None)


# --------------------------------------------------------------------------
# The OTA health-check link (§6)
# --------------------------------------------------------------------------
def test_a_failed_view_is_published_for_the_health_check(registry, tmp_path, monkeypatch):
    """Fail-open keeps the dashboard up, which on its own would let a broken
    update be marked good and never roll back. The marker is what stops
    that: the health check withholds mark-good while it is non-empty."""
    from instrument_cluster.core.system import unhealthy

    marker = str(tmp_path / "unhealthy")
    monkeypatch.setattr(unhealthy, "MARKER", marker)

    registry.acquire(_BrokenView)

    assert unhealthy.reasons(marker) == ["view _BrokenView failed to build"]


def test_a_healthy_build_publishes_nothing(registry, tmp_path, monkeypatch):
    from instrument_cluster.core.system import unhealthy

    marker = str(tmp_path / "unhealthy")
    monkeypatch.setattr(unhealthy, "MARKER", marker)

    registry.preload([_FakeView])

    assert unhealthy.reasons(marker) == []
