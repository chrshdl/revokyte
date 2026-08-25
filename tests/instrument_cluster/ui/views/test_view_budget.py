"""The view set is a budget, and it should change only on purpose.

Preallocation swaps per-transition churn for a permanent reservation. That is
the right trade — 10.73 MB measured on a Pi 4 against 34.8 MB of churn over 20
switches — but it only stays right if a new screen is a visible decision rather
than a quiet addition. See §4 and §10 of docs/VIEW_REGISTRY_REFACTOR.md.
"""

import pytest

from instrument_cluster.ui.views.base import View
from instrument_cluster.ui.views.registry import core_views

# Measured with ViewRegistry.preload() on a Pi 4 at 1024x600, v0.2.40, RSS
# sampled after a forced collection between each view.
MEASURED_MB = {
    "SetupView": 2.83,
    "EnterIPView": 1.77,
    "SoftwareView": 0.71,
    "InstallView": 0.56,
    "DashboardView": 0.45,
    "AgentSetupView": 0.45,
    "ListenerSetupView": 0.35,
    "WifiSetupView": 0.19,
}

# Headroom for roughly a dozen more average views, while still catching a
# screen that costs what SetupView does.
CEILING_MB = 24.0


def test_the_shipped_view_set_is_the_one_that_was_measured():
    """A ninth view is a budget change. Update MEASURED_MB (re-measure on
    device) in the same commit that adds it, so the cost lands in review."""
    assert {cls.__name__ for cls in core_views()} == set(MEASURED_MB)


def test_the_community_budget_is_under_the_ceiling():
    total = sum(MEASURED_MB.values())
    assert total < CEILING_MB, f"{total:.2f} MB exceeds the {CEILING_MB} MB ceiling"


def test_no_single_view_dominates_the_budget():
    """SetupView is 26% of the total. Much past that and the eager preload
    stops being the obvious choice for that view."""
    total = sum(MEASURED_MB.values())
    worst = max(MEASURED_MB.values())
    assert worst / total < 0.40


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
