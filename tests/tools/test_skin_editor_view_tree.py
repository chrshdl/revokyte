"""Per-view widget trees: complete, valid, and in sync with the canvas.

The tree scopes the designer's field list to the selected view, which
creates a new failure mode: a schema field assigned to *no* view becomes
invisible and uneditable. These tests make that a test failure instead —
adding a skin field now requires assigning it to a view tree.
"""

from instrument_cluster.ui.skins import SKIN_1280

from tools.skin_editor import view_tree, viewhost
from tools.skin_editor.bindings import bindings_for
from tools.skin_editor.paths import get_at, walk

#: The skin's identity — deliberately not designer-editable.
# Identity, not geometry: which panel and which car the skin is for.
UNASSIGNED_OK = {"name", "size", "car_id"}


def test_every_schema_field_is_reachable_from_some_view():
    schema_paths = {path for path, _axis, _v in walk(SKIN_1280)} - UNASSIGNED_OK
    assigned = view_tree.all_assigned_paths()
    missing = schema_paths - assigned
    assert not missing, (
        f"skin fields not shown in any view tree (invisible to the "
        f"designer): {sorted(missing)}"
    )


def test_every_tree_path_exists_in_the_schema():
    schema_paths = {path for path, _axis, _v in walk(SKIN_1280)}
    stale = view_tree.all_assigned_paths() - schema_paths
    assert not stale, f"view trees reference removed fields: {sorted(stale)}"


def test_every_view_has_a_tree():
    for view_id, _label in viewhost.VIEWS:
        assert view_tree.tree_for(view_id), f"view {view_id!r} has no tree"


def test_no_duplicate_paths_within_a_view():
    for view_id, _label in viewhost.VIEWS:
        seen = []
        for _section, paths in view_tree.tree_for(view_id):
            seen.extend(paths)
        dupes = {p for p in seen if seen.count(p) > 1}
        assert not dupes, f"{view_id}: duplicated tree entries {sorted(dupes)}"


def test_canvas_bindings_are_in_their_views_tree():
    # Clicking an element on the canvas selects its field in the tree; a
    # binding whose path is missing from the view's tree would select
    # nothing visible.
    for view_id, _label in viewhost.VIEWS:
        tree_paths = {
            p for _s, paths in view_tree.tree_for(view_id) for p in paths
        }
        for binding in bindings_for(view_id):
            assert binding.path in tree_paths, (
                f"{view_id}: canvas binding {binding.path!r} missing from "
                f"the view tree"
            )


def test_tree_paths_resolve_on_every_skin():
    from instrument_cluster.ui.skins import SKIN_800, SKIN_1024

    for skin in (SKIN_1280, SKIN_1024, SKIN_800):
        for path in view_tree.all_assigned_paths():
            get_at(skin, path)  # raises if the path is invalid
