"""Canvas direct manipulation: synthetic mouse gestures against the
Canvas + SkinDocument stack (no window, no app shell)."""

import pygame
import pytest

from instrument_cluster.ui.skins import SKIN_1280, reset_skin_overrides

from tools.skin_editor.bindings import bindings_for
from tools.skin_editor.canvas import Canvas
from tools.skin_editor.document import SkinDocument, UndoStack


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_skin_overrides()


@pytest.fixture
def rig():
    doc = SkinDocument(SKIN_1280)
    undo = UndoStack()
    events = {"selected": None}

    canvas = Canvas(
        (0, 0, 1280, 720),
        on_edit=lambda path, value: doc.set(path, value),
        on_select=lambda b: events.__setitem__("selected", b),
        on_gesture_end=lambda path, old: undo.push(doc, path, old, doc.get(path)),
    )
    canvas.bindings = bindings_for("dashboard")
    canvas.set_surface(pygame.Surface(SKIN_1280.size))
    canvas.zoom_full = True
    canvas._layout()
    return doc, undo, canvas, events


def _mouse(kind, pos, button=1):
    if kind == "down":
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)
    if kind == "up":
        return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button)
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos)


def test_click_selects_smallest_hit_binding(rig):
    doc, _undo, canvas, events = rig
    # The gear dial center: gear_rect (640, 400) center-anchored.
    origin = canvas.origin
    pos = (origin[0] + 640, origin[1] + 400)
    canvas.handle(_mouse("down", pos), doc.skin, doc.get)
    assert events["selected"] is not None
    assert events["selected"].path == "dashboard.gear_rect"


def test_drag_moves_center_anchored_rect_and_coalesces_undo(rig):
    doc, undo, canvas, _events = rig
    origin = canvas.origin
    start = (origin[0] + 640, origin[1] + 400)
    old = doc.get("dashboard.gear_rect")

    canvas.handle(_mouse("down", start), doc.skin, doc.get)
    for step in (10, 20, 30):
        canvas.handle(
            _mouse("move", (start[0] + step, start[1])), doc.skin, doc.get
        )
    canvas.handle(_mouse("up", (start[0] + 30, start[1])), doc.skin, doc.get)

    assert doc.get("dashboard.gear_rect") == (old[0] + 30, old[1], old[2], old[3])
    # Whole gesture = one undo entry.
    assert undo.can_undo
    undo.undo()
    assert doc.get("dashboard.gear_rect") == old
    assert not undo.can_undo


def test_resize_handle_grows_center_rect_symmetrically(rig):
    doc, _undo, canvas, _events = rig
    old = doc.get("dashboard.gear_rect")  # (640, 400, 186, 232) center
    origin = canvas.origin

    # Select, then grab the east handle (right edge, vertical center).
    center = (origin[0] + 640, origin[1] + 400)
    canvas.handle(_mouse("down", center), doc.skin, doc.get)
    canvas.handle(_mouse("up", center), doc.skin, doc.get)
    east = (origin[0] + 640 + old[2] // 2, origin[1] + 400)
    canvas.handle(_mouse("down", east), doc.skin, doc.get)
    canvas.handle(_mouse("move", (east[0] + 10, east[1])), doc.skin, doc.get)
    canvas.handle(_mouse("up", (east[0] + 10, east[1])), doc.skin, doc.get)

    new = doc.get("dashboard.gear_rect")
    assert new[0] == old[0] and new[1] == old[1]  # center unchanged
    assert new[2] == old[2] + 20  # symmetric growth
    assert new[3] == old[3]


def test_hline_drag_edits_scalar(rig):
    doc, _undo, canvas, events = rig
    origin = canvas.origin
    footer_y = doc.get("dashboard.footer_y")
    pos = (origin[0] + 300, origin[1] + footer_y)
    canvas.handle(_mouse("down", pos), doc.skin, doc.get)
    assert events["selected"].path == "dashboard.footer_y"
    canvas.handle(_mouse("move", (pos[0], pos[1] - 12)), doc.skin, doc.get)
    canvas.handle(_mouse("up", (pos[0], pos[1] - 12)), doc.skin, doc.get)
    assert doc.get("dashboard.footer_y") == footer_y - 12


def test_edits_clamp_to_skin_bounds(rig):
    doc, _undo, _canvas, _events = rig
    doc.set("dashboard.footer_y", 5000)
    assert doc.get("dashboard.footer_y") == SKIN_1280.height
    doc.set("setup.row_font_size", 3)
    assert doc.get("setup.row_font_size") == 8  # font floor
