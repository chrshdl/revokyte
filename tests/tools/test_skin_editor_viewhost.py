"""The editor's dashboard host discovers gauges like the app does.

The ViewHost goes through PluginManager over the packaged plugin
directory, so a newly added gauge plugin appears in the canvas with no
editor change. This pins that: everything the manager loads for the editor
must match the packaged WidgetPlugin set exactly (hardware-only plugins
like shift-lights are dropped — they paint nothing on screen), which is
also the regression guard for the day predicted-lap went missing from a
hand-written list.
"""

import importlib
import pkgutil

import pytest

from instrument_cluster import plugins as plugins_pkg
from instrument_cluster.config import ConfigManager
from instrument_cluster.core.plugin_system.sdk import WidgetPlugin

from tools.skin_editor import viewhost


@pytest.fixture
def isolated_config(tmp_path):
    original = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    try:
        yield
    finally:
        ConfigManager.set_path(original)


def _packaged_widget_plugin_ids() -> set[str]:
    ids = set()
    for module_info in pkgutil.iter_modules(plugins_pkg.__path__):
        module = importlib.import_module(
            f"{plugins_pkg.__name__}.{module_info.name}"
        )
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, WidgetPlugin)
                and obj is not WidgetPlugin
                and obj.__module__ == module.__name__
            ):
                ids.add(obj.plugin_id)
    return ids


def test_editor_manager_loads_every_visual_packaged_plugin(isolated_config):
    # Fresh manager for the test process state.
    viewhost._manager = None
    try:
        manager = viewhost._plugin_manager()
        loaded_ids = {plugin.plugin_id for plugin in manager.plugins}
        assert loaded_ids == _packaged_widget_plugin_ids()
        # Discovery, not a hand-written list: the historical regression.
        assert "predicted-lap" in loaded_ids
    finally:
        viewhost._manager = None
