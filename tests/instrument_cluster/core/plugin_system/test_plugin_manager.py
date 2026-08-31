"""PluginManager: dual-directory discovery, the pluggable feature gate,
reload semantics, and gauge rect parity with the pre-plugin dashboard
layout."""

import os
from dataclasses import dataclass, field

import pytest
from pygame.sprite import LayeredDirty

import instrument_cluster.plugins as packaged_plugins
from instrument_cluster.core.plugin_system import plugin_manager as pm_mod
from instrument_cluster.core.plugin_system.plugin_layout import LayoutContext
from instrument_cluster.core.plugin_system.plugin_manager import PluginManager

PACKAGED_DIR = os.path.dirname(packaged_plugins.__file__)


@dataclass
class MockVehicleBus:
    frame: object = None
    signals: dict = field(default_factory=dict)
    app_state: dict = field(default_factory=dict)


PLUGIN_TEMPLATE = """
from instrument_cluster.core.plugin_system.sdk import GenericPlugin


class {cls}(GenericPlugin):
    plugin_id = "{pid}"
    version = "{version}"

    def setup(self):
        self.did_setup = True

    def update(self, dt):
        self.updates = getattr(self, "updates", 0) + 1

    # test-specific overrides come last so they win
{extra}
"""


WIDGET_PLUGIN_TEMPLATE = """
from instrument_cluster.core.plugin_system.sdk import WidgetPlugin


class {cls}(WidgetPlugin):
    plugin_id = "{pid}"
    version = "{version}"

    def build_widgets(self):
        return []

    # test-specific overrides come last so they win
{extra}
"""


def write_plugin(path, pid, cls="ExternalTestPlugin", version="1.0.0", extra=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_lines = (
        "\n".join(f"    {line}" for line in extra.splitlines()) if extra else "    pass"
    )
    # `pass` after the attrs is harmless; keep the template simple.
    body = PLUGIN_TEMPLATE.format(cls=cls, pid=pid, version=version, extra=extra_lines)
    path.write_text(body)


def write_widget_plugin(path, pid, cls="ExternalWidgetPlugin", extra=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_lines = (
        "\n".join(f"    {line}" for line in extra.splitlines()) if extra else "    pass"
    )
    body = WIDGET_PLUGIN_TEMPLATE.format(
        cls=cls, pid=pid, version="1.0.0", extra=extra_lines
    )
    path.write_text(body)


@pytest.fixture
def granted_features(monkeypatch):
    """Steer the manager's feature gate with a plain set of feature keys
    (standing in for a provider an extension would install)."""
    features: set[str] = set()

    class FakeFeatureProvider:
        invalidate_count = 0

        def has_feature(self, key):
            return key in features

        @classmethod
        def invalidate(cls):
            cls.invalidate_count += 1

    monkeypatch.setattr(pm_mod, "NullFeatureProvider", FakeFeatureProvider)
    return features


@pytest.fixture(autouse=True)
def fixed_layout(monkeypatch):
    """Deterministic layout regardless of the developer's config.json."""
    monkeypatch.setattr(
        pm_mod.LayoutContext,
        "from_config",
        classmethod(lambda cls: cls(status_lights=False)),
    )


def make_manager(tmp_path, packaged_dir=None, external=None):
    packaged = packaged_dir if packaged_dir is not None else str(tmp_path / "pkg")
    external_dir = external if external is not None else tmp_path / "ext"
    return PluginManager(packaged, MockVehicleBus(), external_dir=external_dir)


def plugin_ids(manager):
    return {p.plugin_id for p in manager.plugins}


def by_id(manager, pid):
    return next(p for p in manager.plugins if p.plugin_id == pid)


class TestExternalDiscovery:
    def test_loads_loose_file_and_slug_subdir(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_plugin(ext / "loose.py", "loose")
        write_plugin(ext / "boxed" / "boxed.py", "boxed")

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert plugin_ids(m) == {"loose", "boxed"}
        assert by_id(m, "loose").did_setup is True

    def test_broken_plugin_is_skipped_not_fatal(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_plugin(ext / "good.py", "good")
        (ext / "broken.py").write_text("raise RuntimeError('boom at import')\n")

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert plugin_ids(m) == {"good"}

    def test_external_shadows_packaged_by_plugin_id(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_plugin(ext / "gear.py", "gear", version="9.9.9")

        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=ext)
        m.load_plugins()

        gears = [p for p in m.plugins if p.plugin_id == "gear"]
        assert len(gears) == 1
        assert gears[0].version == "9.9.9"


class TestFeatureGate:
    def test_required_feature_blocks_ungranted(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_plugin(
            ext / "gated.py", "gated-thing", extra='required_feature = "gated_thing"'
        )

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        assert plugin_ids(m) == set()

        granted_features.add("gated_thing")
        m.reload_plugins()
        assert plugin_ids(m) == {"gated-thing"}

    def test_default_build_gets_every_standard_gauge(self, tmp_path, granted_features):
        """Fuel pair and shift lights are free — no feature key required. The
        default layout no longer carries a current-lap plugin (the block
        remains available in the custom dashboard builder)."""
        m = make_manager(
            tmp_path, packaged_dir=PACKAGED_DIR, external=tmp_path / "empty"
        )
        m.load_plugins()

        ids = plugin_ids(m)
        assert "fuel-strategy" in ids
        assert "shift-lights" in ids
        assert "current-lap" not in ids

        # The fuel pair fills exactly the slot the current-lap widget used
        # to occupy (same bounding box).
        fuel = by_id(m, "fuel-strategy")
        left, right = fuel.widgets
        from instrument_cluster.ui.utils import srect
        from instrument_cluster.ui.widgets.current_lap_time_widget import (
            CurrentLapTimeWidget,
        )

        slot = CurrentLapTimeWidget(rect=srect(186, 258, 352, 94)).rect
        assert left.rect.left == slot.left
        assert right.rect.right == slot.right

    def test_excluded_plugin_keeps_slot_until_provider_loads(
        self, tmp_path, granted_features
    ):
        """excluded_by_feature yields the slot only when some eligible
        plugin actually provides that feature — an ungranted provider
        must not leave an empty slot."""
        ext = tmp_path / "ext"
        write_plugin(
            ext / "free.py",
            "free-widget",
            cls="FreeSlotPlugin",
            extra='excluded_by_feature = "gated_thing"',
        )
        write_plugin(
            ext / "gated.py",
            "gated-thing",
            cls="GatedSlotPlugin",
            extra='required_feature = "gated_thing"',
        )

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        assert plugin_ids(m) == {"free-widget"}

        granted_features.add("gated_thing")
        m.reload_plugins()
        assert plugin_ids(m) == {"gated-thing"}


class TestReload:
    def test_reload_bumps_generation_and_replaces_instances(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_plugin(ext / "loose.py", "loose")
        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        first = by_id(m, "loose")
        gen = m.generation

        m.reload_plugins()

        assert m.generation == gen + 1
        assert by_id(m, "loose") is not first

    def test_reload_picks_up_new_file_contents(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_plugin(ext / "loose.py", "loose", version="1.0.0")
        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        assert by_id(m, "loose").version == "1.0.0"

        write_plugin(ext / "loose.py", "loose", version="2.0.0")
        m.reload_plugins()
        assert by_id(m, "loose").version == "2.0.0"

    def test_teardown_removes_sprites_from_draw_layers(
        self, tmp_path, granted_features
    ):
        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=tmp_path / "x")
        m.load_plugins()

        layer = LayeredDirty()
        for plugin in m.plugins:
            layer.add(plugin.sprites)
        assert len(layer) > 0

        m.reload_plugins()

        # Old sprites were killed → they left the dashboard's draw layer.
        assert len(layer) == 0

    def test_request_reload_is_consumed_once(self, tmp_path, granted_features):
        m = make_manager(tmp_path)
        assert m.consume_reload_request() is False
        m.request_reload()
        assert m.consume_reload_request() is True
        assert m.consume_reload_request() is False


class TestUpdateLoop:
    def test_dashboard_only_plugin_waits_for_active_dashboard(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_plugin(ext / "hw.py", "hw", extra="dashboard_only = True")
        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        plugin = by_id(m, "hw")

        m.update(0.016)
        assert getattr(plugin, "updates", 0) == 0

        m.set_dashboard_active(True)
        m.update(0.016)
        assert plugin.updates == 1

        m.set_dashboard_active(False)
        m.update(0.016)
        assert plugin.updates == 1

    def test_shift_lights_run_while_a_menu_covers_the_dashboard(
        self, tmp_path, granted_features
    ):
        """The LED bar is a physical peripheral: like the signal pipeline it
        never pauses for a UI state (a dashboard_only gate used to freeze it
        mid-pattern in Setup, showing lit LEDs that meant nothing). The
        peripheral's own guards — the Setup toggle, stale-link supervision —
        are what blank it."""
        from unittest.mock import MagicMock

        m = make_manager(
            tmp_path, packaged_dir=PACKAGED_DIR, external=tmp_path / "empty"
        )
        m.load_plugins()
        plugin = by_id(m, "shift-lights")
        plugin._peripheral = MagicMock()

        m.set_dashboard_active(False)  # e.g. Setup pushed over the dashboard
        m.update(0.016)

        plugin._peripheral.update.assert_called_once()

    def test_crashing_plugin_is_disabled_not_fatal(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_plugin(ext / "ok.py", "ok")
        write_plugin(
            ext / "bad.py",
            "bad",
            extra="def update(self, dt):\n    raise RuntimeError('boom')",
        )
        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        m.update(0.016)
        m.update(0.016)

        assert by_id(m, "bad").enabled is False
        assert by_id(m, "ok").updates == 2

    def test_old_style_single_arg_plugin_still_loads(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        (ext).mkdir(parents=True)
        (ext / "legacy.py").write_text(
            "from instrument_cluster.core.plugin_system.sdk import GenericPlugin\n"
            "class LegacyPlugin(GenericPlugin):\n"
            "    def __init__(self, bus):\n"
            "        super().__init__(bus)\n"
            "        self.name = 'Legacy'\n"
            "    def setup(self):\n"
            "        pass\n"
            "    def update(self, dt):\n"
            "        pass\n"
        )
        m = make_manager(tmp_path, external=ext)
        m.load_plugins()
        assert {p.name for p in m.plugins} == {"Legacy"}


class TestRectParity:
    """The converted gauge plugins must occupy exactly the rects the
    pre-plugin DashboardView._init_widgets laid out, at both layouts.

    One exception, recorded rather than hidden: the rpm gauge was deliberately
    resized for the Ferrari-style discrete tach, so its entry tracks the skin's
    current ``rpm_rect`` instead of the original geometry. Every other gauge is
    still pinned to what the pre-plugin view produced, which is what makes an
    accidental drift here a test failure.
    """

    # (plugin_id, anchor, [(skin rect field, status-lights shift)]) in build
    # order. The geometry itself is read from the skin, not repeated here: the
    # regressions this guards against are a plugin claiming the *wrong* rect,
    # anchoring it wrongly, or dropping the LayoutContext shift — not the
    # designer moving a gauge, which is their call and used to break this test
    # on every skin tweak.
    EXPECTED = [
        ("gear", "center", [("gear_rect", None)]),
        ("speed", "center", [("speed_rect", None)]),
        ("rpm", "center", [("rpm_rect", None)]),
        ("fastest-lap", "center", [("fastest_lap_rect", "+sl")]),
        ("predicted-lap", "center", [("predicted_lap_rect", "+sl")]),
        ("fuel-strategy", "center",
         [("fuel_per_lap_rect", "+sl"), ("fuel_laps_rect", "+sl")]),
        ("track-name", "center", [("track_rect", "+sl")]),
        ("lap-time", "center", [("lap_time_rect", "-sr")]),
        ("delta", "center", [("delta_rect", "-sr")]),
        ("tire-temps", "topleft", [("tire:0:0", "-sr"), ("tire:1:0", "-sr"),
                                   ("tire:0:1", "-sr"), ("tire:1:1", "-sr")]),
        ("lap-counter", "topleft", [("lap_counter_rect", "-sr")]),
    ]

    @staticmethod
    def skin_rect(field):
        """The design-space rect a plugin is expected to claim."""
        from instrument_cluster.ui.skins import SKIN_1280

        d = SKIN_1280.dashboard
        if field.startswith("tire:"):
            _, col, row = field.split(":")
            g = d.tire_grid
            return (
                g.origin[0] + int(col) * g.col_step,
                g.origin[1] + int(row) * g.row_step,
                g.cell[0],
                g.cell[1],
            )
        return getattr(d, field)

    @pytest.mark.parametrize("status_lights", [False, True])
    def test_gauge_rects_match_the_original_layout(
        self, tmp_path, granted_features, monkeypatch, status_lights
    ):
        import pygame

        from instrument_cluster.ui.utils import srect

        layout = LayoutContext(status_lights=status_lights)
        monkeypatch.setattr(
            pm_mod.LayoutContext, "from_config", classmethod(lambda cls: layout)
        )
        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=tmp_path / "x")
        m.load_plugins()

        def expected_rect(field, shift, anchor):
            # Mirrors Widget.__init__'s anchor placement of the scaled
            # design rect, with the LayoutContext shift applied to x exactly
            # as the pre-plugin view applied it.
            x, y, w, h = self.skin_rect(field)
            if shift == "+sl":
                x += layout.shift_l
            elif shift == "-sr":
                x -= layout.shift_r
            px, py, w, h = srect(x, y, w, h)
            if anchor == "center":
                return pygame.Rect(px - w // 2, py - h // 2, w, h)
            return pygame.Rect(px, py, w, h)

        for pid, anchor, rects in self.EXPECTED:
            plugin = by_id(m, pid)
            actual = [w.rect for w in plugin.widgets]
            expected = [expected_rect(f, sh, anchor) for f, sh in rects]
            assert actual == expected, f"rect drift in plugin '{pid}'"


class TestExclusiveProvider:
    """A granted, ready exclusive plugin replaces the standard gauge
    layout; every failure in that chain (feature not granted, not ready,
    provider_ready raising) falls back to the default dashboard."""

    def write_exclusive(self, ext, ready="True", feature='"gated_dash"'):
        write_widget_plugin(
            ext / "exclusive-dash" / "exclusive-dash.py",
            "exclusive-dash",
            cls="ExclusiveDashPlugin",
            extra=(
                f"required_feature = {feature}\n"
                "exclusive = True\n"
                "@classmethod\n"
                "def provider_ready(cls):\n"
                f"    return {ready}"
            ),
        )

    def test_ready_provider_replaces_standard_gauges(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        self.write_exclusive(ext)
        granted_features.add("gated_dash")

        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=ext)
        m.load_plugins()

        # Screen gauges are replaced by the provider; the (free)
        # shift-lights hardware plugin keeps running alongside.
        assert plugin_ids(m) == {"exclusive-dash", "shift-lights"}
        assert m.active_provider() is by_id(m, "exclusive-dash")

    def test_ungranted_provider_keeps_standard_dashboard(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        self.write_exclusive(ext)

        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=ext)
        m.load_plugins()

        ids = plugin_ids(m)
        assert "exclusive-dash" not in ids
        assert "gear" in ids
        assert m.active_provider() is None

    def test_unready_provider_loads_as_ordinary_plugin(
        self, tmp_path, granted_features
    ):
        """Not ready (e.g. its data hasn't synced yet): no takeover, the
        standard gauges stay — but the plugin still loads, so its state
        can be queried and a later sync can flip it via reload."""
        ext = tmp_path / "ext"
        self.write_exclusive(ext, ready="False")
        granted_features.add("gated_dash")

        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=ext)
        m.load_plugins()

        ids = plugin_ids(m)
        assert "gear" in ids
        assert "exclusive-dash" in ids

    def test_provider_ready_raising_falls_back(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        self.write_exclusive(ext, ready="1 / 0")
        granted_features.add("gated_dash")

        m = make_manager(tmp_path, packaged_dir=PACKAGED_DIR, external=ext)
        m.load_plugins()

        assert "gear" in plugin_ids(m)

    def test_first_ready_provider_by_id_wins(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        for pid in ("aaa-dash", "zzz-dash"):
            write_widget_plugin(
                ext / pid / f"{pid}.py",
                pid,
                cls="ExclusivePlugin",
                extra="exclusive = True",
            )

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert plugin_ids(m) == {"aaa-dash"}
        assert m.active_provider().plugin_id == "aaa-dash"


class TestSyncHooks:
    """background_sync hooks are collected per load from every granted
    candidate class — independent of readiness and instantiation, so an
    unready provider's data can still be synced into existence."""

    HOOK = (
        'required_feature = "gated_dash"\n'
        "exclusive = True\n"
        "@classmethod\n"
        "def provider_ready(cls):\n"
        "    return False\n"
        "@classmethod\n"
        "def background_sync(cls, ctx):\n"
        "    return None"
    )

    def test_hook_registered_for_granted_unready_class(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_widget_plugin(
            ext / "syncer" / "syncer.py", "syncer", cls="Syncer", extra=self.HOOK
        )
        granted_features.add("gated_dash")

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert [cls.plugin_id for cls in m.sync_hooks] == ["syncer"]

    def test_no_hooks_for_ungranted_class(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_widget_plugin(
            ext / "syncer" / "syncer.py", "syncer", cls="Syncer", extra=self.HOOK
        )

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert m.sync_hooks == []

    def test_plugins_without_hook_register_nothing(
        self, tmp_path, granted_features
    ):
        ext = tmp_path / "ext"
        write_plugin(ext / "plain.py", "plain")

        m = make_manager(tmp_path, external=ext)
        m.load_plugins()

        assert m.sync_hooks == []


class TestContributedClasses:
    """Classes registered directly on the manager (extensions do this
    from wire()) load like packaged ones, and an external file can
    still shadow them by plugin_id for a hot fix."""

    def _contributed(self):
        from instrument_cluster.core.plugin_system.sdk import GenericPlugin

        class ContributedPlugin(GenericPlugin):
            plugin_id = "contrib"
            version = "1.0.0"

            def setup(self):
                self.did_setup = True

            def update(self, dt):
                pass

        return ContributedPlugin

    def test_contributed_class_loads(self, tmp_path, granted_features):
        m = make_manager(tmp_path)
        m.contributed_classes.append(self._contributed())
        m.load_plugins()
        assert plugin_ids(m) == {"contrib"}
        assert by_id(m, "contrib").did_setup is True

    def test_external_shadows_contributed(self, tmp_path, granted_features):
        ext = tmp_path / "ext"
        write_plugin(ext / "contrib.py", "contrib", version="9.9.9")
        m = make_manager(tmp_path, external=ext)
        m.contributed_classes.append(self._contributed())
        m.load_plugins()
        assert plugin_ids(m) == {"contrib"}
        assert by_id(m, "contrib").version == "9.9.9"

    def test_contributed_respects_feature_gate(self, tmp_path, granted_features):
        cls = self._contributed()
        cls.required_feature = "gated_thing"
        m = make_manager(tmp_path)
        m.contributed_classes.append(cls)
        m.load_plugins()
        assert plugin_ids(m) == set()

        granted_features.add("gated_thing")
        m.reload_plugins()
        assert plugin_ids(m) == {"contrib"}


class TestReloadFeatureInvalidation:
    def _reload(self, m):
        assert m.consume_reload_request() is True
        m.reload_plugins()

    def test_default_reload_invalidates_the_feature_provider(
        self, tmp_path, granted_features
    ):
        m = make_manager(tmp_path)
        m.load_plugins()
        before = pm_mod.NullFeatureProvider.invalidate_count
        m.request_reload()
        self._reload(m)
        assert pm_mod.NullFeatureProvider.invalidate_count == before + 1

    def test_slot_switch_reload_skips_the_invalidation(
        self, tmp_path, granted_features
    ):
        """A dashboard slot switch changes no feature grants — skipping
        the provider invalidation avoids stalling the swipe."""
        m = make_manager(tmp_path)
        m.load_plugins()
        before = pm_mod.NullFeatureProvider.invalidate_count
        m.request_reload(invalidate_features=False)
        self._reload(m)
        assert pm_mod.NullFeatureProvider.invalidate_count == before

    def test_merged_requests_invalidate_if_any_asked(
        self, tmp_path, granted_features
    ):
        m = make_manager(tmp_path)
        m.load_plugins()
        before = pm_mod.NullFeatureProvider.invalidate_count
        m.request_reload(invalidate_features=False)
        m.request_reload()  # e.g. a background feature refresh raced the swipe
        self._reload(m)
        assert pm_mod.NullFeatureProvider.invalidate_count == before + 1
