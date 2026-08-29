"""Skin infrastructure and per-skin layout smoke tests.

Three concerns:

* resolution — ``active_skin()`` picks the right skin for each display
  profile (and falls back to the 1280 skin for unknown logical sizes);
* schema sanity — every value in every skin is an integer and every
  rect/position lands inside the skin's resolution;
* extraction fidelity — SKIN_1280 must stay identical to the legacy
  constants it was extracted from, until the last legacy consumer is
  migrated. These assertions are the tripwire against the two drifting
  apart mid-migration.
"""

from dataclasses import is_dataclass

import pytest

from instrument_cluster.ui.skins import (
    SKIN_800,
    SKIN_1024,
    SKIN_1280,
    active_skin,
)
from instrument_cluster.ui.skins.schema import axis_of, iter_px_fields

ALL_SKINS = [SKIN_1280, SKIN_1024, SKIN_800]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "profile_name, expected",
    [
        ("dev", SKIN_1280),
        ("rpi_display_2", SKIN_1280),
        ("waveshare_7", SKIN_1024),
        ("waveshare_5", SKIN_800),
    ],
)
def test_active_skin_per_profile(force_profile, profile_name, expected):
    with force_profile(profile_name):
        assert active_skin() is expected


def test_active_skin_defaults_to_1280_without_display():
    # Lazy dev default (tests never construct a Display).
    assert active_skin() is SKIN_1280


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------
def _walk(obj, path=""):
    for f, value in iter_px_fields(obj):
        where = f"{path}.{f.name}" if path else f.name
        if is_dataclass(value):
            yield from _walk(value, where)
        else:
            yield where, axis_of(f), value


@pytest.mark.parametrize("skin", ALL_SKINS, ids=lambda s: s.name)
def test_all_values_are_ints(skin):
    for where, axis, value in _walk(skin):
        # "const" carries resolution-independent values, which are usually
        # counts but may be a verbatim string (dashboard.rpm_variant selects
        # which RPM gauge the panel wears). This guard is about geometry, so
        # skip strings rather than demand ints from a field that is a choice.
        if where == "name" or axis in ("family", "color"):
            continue
        if axis == "const" and isinstance(value, str):
            continue
        values = value if isinstance(value, tuple) else (value,)
        for v in values:
            assert isinstance(v, int), f"{skin.name}: {where} = {value!r}"


@pytest.mark.parametrize("skin", ALL_SKINS, ids=lambda s: s.name)
def test_font_families_are_valid(skin):
    from instrument_cluster.ui.utils import FontFamily

    for where, axis, value in _walk(skin):
        if axis == "family":
            assert value in FontFamily.__members__, (
                f"{skin.name}: {where} = {value!r} is not a FontFamily"
            )


@pytest.mark.parametrize("skin", ALL_SKINS, ids=lambda s: s.name)
def test_color_references_are_valid(skin):
    from instrument_cluster.ui.colors import Color

    for where, axis, value in _walk(skin):
        if axis == "color":
            assert value in Color.__members__, (
                f"{skin.name}: {where} = {value!r} is not a palette Color"
            )


@pytest.mark.parametrize("skin", ALL_SKINS, ids=lambda s: s.name)
def test_geometry_within_bounds(skin):
    w, h = skin.size
    for where, axis, value in _walk(skin):
        if axis == "rect":
            x, y, rw, rh = value
            assert 0 <= x <= w and 0 <= y <= h, f"{skin.name}: {where}"
            assert 0 < rw <= w and 0 < rh <= h, f"{skin.name}: {where}"
        elif axis == "pos":
            x, y = value
            assert 0 <= x <= w and 0 <= y <= h, f"{skin.name}: {where}"
        elif axis == "size":
            sw, sh = value
            assert 0 < sw <= w and 0 < sh <= h, f"{skin.name}: {where}"
        elif axis in ("font", "font_pixel"):
            assert value >= 8, f"{skin.name}: {where} = {value}"


@pytest.mark.parametrize("skin", ALL_SKINS, ids=lambda s: s.name)
def test_pixel_fonts_are_even(skin):
    # Pixeltype renders best on its 8px grid — the seed generator snaps to
    # it — but a designer may deliberately land off-grid (the 800 skin's
    # header runs at 20). Odd sizes are always ragged though, so hold the
    # line at even.
    for where, axis, value in _walk(skin):
        if axis == "font_pixel":
            assert value % 2 == 0, f"{skin.name}: {where} = {value}"


# ---------------------------------------------------------------------------
# Extraction fidelity (1280 skin == legacy constants)
# ---------------------------------------------------------------------------
def test_skin_1280_keeps_the_original_grid():
    # The 1280 skin IS the original design — pin its load-bearing numbers
    # so a stray regeneration or edit can't silently reshape the shipped
    # layout. (The legacy constants these were extracted from are gone;
    # the skin is now the single source.)
    d = SKIN_1280.dashboard
    assert d.footer_y == 636 and d.button_h == 72
    assert d.track_rect == (186, 454, 352, 94)
    assert d.gear_rect == (640, 400, 186, 232)
    assert d.lap_counter_rect == (1172, 630, 90, 78)
    # Widened and lowered for the Ferrari 296-style segmented bar; the gear
    # dial dropped to y=400 to keep clear of it.
    assert d.rpm_rect == (640, 214, 320, 98)

    s = SKIN_1280.setup
    # 5 uniform cells span the header line (100) to the bottom (720).
    assert s.row_top == 122 and s.row_pitch == 124 and s.row_height == 80

    k = SKIN_1280.keyboard
    assert (k.key_w, k.key_h, k.gap) == (112, 78, 10)
    assert k.top == 300 and k.row_step == 90


def test_layout_context_shifts_follow_skin(force_profile):
    from instrument_cluster.core.plugin_system.plugin_layout import LayoutContext

    on = LayoutContext(status_lights=True)
    off = LayoutContext(status_lights=False)
    for profile, skin in [("dev", SKIN_1280), ("waveshare_5", SKIN_800)]:
        with force_profile(profile):
            assert (on.shift_l, on.shift_r) == (
                skin.dashboard.shift_l_on,
                skin.dashboard.shift_r_on,
            )
            assert (off.shift_l, off.shift_r) == (0, 0)


# ---------------------------------------------------------------------------
# Per-skin dashboard smoke test: every gauge fits, nothing overlaps
# ---------------------------------------------------------------------------
def _plugin_classes():
    from instrument_cluster.plugins.delta import DeltaPlugin
    from instrument_cluster.plugins.fastest_lap import FastestLapPlugin
    from instrument_cluster.plugins.fuel_strategy import FuelStrategyPlugin
    from instrument_cluster.plugins.gear import GearPlugin
    from instrument_cluster.plugins.lap_counter import LapCounterPlugin
    from instrument_cluster.plugins.lap_time import LapTimePlugin
    from instrument_cluster.plugins.rpm import RpmPlugin
    from instrument_cluster.plugins.speed import SpeedPlugin
    from instrument_cluster.plugins.tire_temps import TireTempsPlugin
    from instrument_cluster.plugins.track_name import TrackNamePlugin

    return [
        DeltaPlugin,
        FastestLapPlugin,
        FuelStrategyPlugin,
        GearPlugin,
        LapCounterPlugin,
        LapTimePlugin,
        RpmPlugin,
        SpeedPlugin,
        TireTempsPlugin,
        TrackNamePlugin,
    ]


@pytest.mark.parametrize("profile", ["dev", "waveshare_7", "waveshare_5"], ids=str)
@pytest.mark.parametrize("lights", [False, True], ids=["plain", "lights"])
def test_dashboard_gauges_fit_per_skin(force_profile, profile, lights):
    import pygame

    from instrument_cluster.core.plugin_system.plugin_bus_view import (
        PluginBusView,
    )
    from instrument_cluster.core.plugin_system.plugin_layout import LayoutContext
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus

    with force_profile(profile):
        skin = active_skin()
        bus = PluginBusView(VehicleBus())
        layout = LayoutContext(status_lights=lights)

        rects: list[tuple[str, pygame.Rect]] = []
        for cls in _plugin_classes():
            plugin = cls(bus, layout)
            for widget in plugin.build_widgets():
                rects.append((cls.plugin_id, pygame.Rect(widget.rect)))

        screen = pygame.Rect(0, 0, *skin.size)
        if lights:
            # The bezel strips reserve the outer columns; gauges shift
            # inward and must stay clear of them.
            x, _, w, _ = skin.dashboard.status_light_rect
            screen = pygame.Rect(x + w, 0, skin.width - 2 * (x + w), skin.height)
        for name, rect in rects:
            assert screen.contains(rect), f"{skin.name}/{name}: {rect} outside"

        # The rpm bar deliberately tucks under the speed box (borderless,
        # its ink stays inside) — the one overlap the design intends.
        allowed = {frozenset(("speed", "rpm"))}
        for i, (name_a, rect_a) in enumerate(rects):
            for name_b, rect_b in rects[i + 1 :]:
                if frozenset((name_a, name_b)) in allowed:
                    continue
                assert not rect_a.colliderect(rect_b), (
                    f"{skin.name}: {name_a} {rect_a} overlaps {name_b} {rect_b}"
                )


def test_overlay_geometry_stays_inside_every_skin():
    for skin in ALL_SKINS:
        o = skin.overlays
        # The shared status pill (Wi-Fi note and no-telemetry alert) sits
        # in the free strip the dashboard leaves between the track row and
        # the footer.
        assert o.wifi_pill_center_y + o.wifi_pill_height // 2 <= skin.height
        # The feed-update card and its button fit centred on screen.
        assert o.feed_card_size[0] <= skin.width
        assert o.feed_card_size[1] <= skin.height
        assert o.feed_button_size[0] < o.feed_card_size[0]
