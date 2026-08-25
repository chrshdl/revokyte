"""The view set is bounded, and changes to it should be deliberate.

Preallocation swaps per-transition churn for a permanent reservation — the
right trade at the measured cost, but only while the set stays small on
purpose. This file gates the *set*, not its size: a byte budget would have to
be re-measured for every skin (1280x720, 1024x600, 800x480, and whatever comes
next) and every variant, so it would rot into a number nobody trusts.

What a screen actually costs is a measurement, not an invariant. It depends on
the panel, so it belongs in docs/VIEW_REGISTRY_REFACTOR.md next to the panel it
was taken on, regenerated when someone needs it — not re-derived by CI on a
machine with no panel at all.

The load-bearing test here is the last one: every view must construct with no
arguments and survive reset(None). That is what makes a view poolable, and it
is the check that catches a screen arriving with constructor arguments.
"""

import pytest

from instrument_cluster.ui.views.base import View
from instrument_cluster.ui.views.registry import core_views

# The community screen set. Not derived from core_views() — that is the thing
# under test. Adding a screen means editing this too, which is the point: a
# permanent reservation should be a visible act, not a quiet one.
EXPECTED_VIEWS = {
    "DashboardView",
    "SetupView",
    "SoftwareView",
    "EnterIPView",
    "WifiSetupView",
    "InstallView",
    "AgentSetupView",
    "ListenerSetupView",
}


def test_the_shipped_view_set_is_the_declared_one():
    """A ninth view is a permanent reservation. Declaring it here in the same
    commit that adds it is what puts the decision in front of a reviewer."""
    assert {cls.__name__ for cls in core_views()} == EXPECTED_VIEWS


def test_every_core_view_really_is_a_view():
    for cls in core_views():
        assert issubclass(cls, View), f"{cls.__name__} is not a View"


def test_core_views_have_no_duplicates():
    classes = core_views()
    assert len(set(classes)) == len(classes)


@pytest.mark.parametrize("cls", core_views(), ids=lambda c: c.__name__)
def test_a_core_view_constructs_and_resets_without_arguments(cls):
    """The registry calls cls() then build(), and every entry calls
    reset(ctx) — a view that needs constructor arguments cannot be pooled."""
    view = cls()
    view.build()
    view.reset(None)
