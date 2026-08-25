"""The extension seam: no installed extensions is the silent default, a
broken extension rolls back without touching the others, and a wired
extension's registrations reach the main loop."""

from instrument_cluster import extensions as ext_mod
from instrument_cluster.extensions import ExtensionRuntime, SetupEntry


def _load(runtime):
    runtime.load(
        vehicle_bus=object(),
        state_manager=object(),
        window_manager=object(),
        plugin_manager=object(),
    )


def _register_hooks(monkeypatch, *hooks):
    """Substitute the entry-point lookup with (name, wire) pairs."""
    monkeypatch.setattr(ext_mod, "_wire_hooks", lambda: iter(hooks))


def test_no_extensions_is_a_silent_noop(monkeypatch):
    _register_hooks(monkeypatch)
    runtime = ExtensionRuntime()
    _load(runtime)
    assert runtime.active is False
    assert runtime.setup_entries == []
    assert runtime.update_signals() == {}


def test_wire_registrations_reach_the_runtime(monkeypatch):
    class Processor:
        stopped = False

        def update(self):
            return {"ext_key": 1}

        def stop(self):
            self.stopped = True

    processor = Processor()

    def wire(runtime):
        runtime.add_signal_processor(processor)
        runtime.add_setup_entry(
            SetupEntry(
                icon="x", label="Software", button_text="OS", make_state=lambda sm: None
            )
        )

    _register_hooks(monkeypatch, ("demo", wire))
    runtime = ExtensionRuntime()
    _load(runtime)

    assert runtime.active is True
    assert runtime.loaded == ["demo"]
    assert runtime.update_signals() == {"ext_key": 1}
    assert [e.label for e in runtime.setup_entries] == ["Software"]
    runtime.stop()
    assert processor.stopped is True


def test_broken_extension_rolls_back_only_itself(monkeypatch):
    def good_wire(runtime):
        runtime.add_setup_entry(
            SetupEntry(
                icon="x", label="Good", button_text="!", make_state=lambda sm: None
            )
        )

    def broken_wire(runtime):
        runtime.add_setup_entry(
            SetupEntry(
                icon="x", label="Broken", button_text="!", make_state=lambda sm: None
            )
        )
        raise RuntimeError("boom")

    _register_hooks(monkeypatch, ("good", good_wire), ("broken", broken_wire))
    runtime = ExtensionRuntime()
    _load(runtime)

    assert runtime.loaded == ["good"]
    assert [e.label for e in runtime.setup_entries] == ["Good"]


def test_broken_extension_stops_its_processors(monkeypatch):
    class Processor:
        stopped = False

        def update(self):
            return {}

        def stop(self):
            self.stopped = True

    processor = Processor()

    def broken_wire(runtime):
        runtime.add_signal_processor(processor)
        raise RuntimeError("boom")

    _register_hooks(monkeypatch, ("broken", broken_wire))
    runtime = ExtensionRuntime()
    _load(runtime)

    assert runtime.active is False
    assert runtime.update_signals() == {}
    assert processor.stopped is True


def test_crashing_processor_is_dropped_not_fatal(monkeypatch):
    class Bad:
        def update(self):
            raise RuntimeError("boom")

    class Good:
        def update(self):
            return {"ok": True}

    def wire(runtime):
        runtime.add_signal_processor(Bad())
        runtime.add_signal_processor(Good())

    _register_hooks(monkeypatch, ("demo", wire))
    runtime = ExtensionRuntime()
    _load(runtime)

    assert runtime.update_signals() == {"ok": True}
    # The crashing processor is gone; the healthy one keeps publishing.
    assert runtime.update_signals() == {"ok": True}


# --------------------------------------------------------------------------
# Extension-declared views (§6 of docs/VIEW_REGISTRY_REFACTOR.md)
# --------------------------------------------------------------------------
class _AView:
    pass


class _BView:
    pass


def _entry(label, view_class=None):
    from instrument_cluster.extensions import SetupEntry

    return SetupEntry(
        icon="",
        label=label,
        button_text="go",
        make_state=lambda sm: None,
        view_class=view_class,
    )


def test_register_views_collects_what_an_extension_declares(monkeypatch):
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()

    def wire(rt):
        rt.register_views([_AView, _BView])

    monkeypatch.setattr(
        "instrument_cluster.extensions._wire_hooks", lambda: [("demo", wire)]
    )
    runtime.load(
        vehicle_bus=None, state_manager=None, window_manager=None, plugin_manager=None
    )

    assert runtime.view_classes == [_AView, _BView]


def test_a_broken_extension_rolls_back_its_views_too(monkeypatch):
    """Views join the same wire()-granularity rollback as every other
    registration — a half-wired extension must not leave the registry
    preloading a view whose owner never finished setting itself up."""
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()

    def good(rt):
        rt.register_views([_AView])

    def broken(rt):
        rt.register_views([_BView])
        raise RuntimeError("half-wired")

    monkeypatch.setattr(
        "instrument_cluster.extensions._wire_hooks",
        lambda: [("good", good), ("broken", broken)],
    )
    runtime.load(
        vehicle_bus=None, state_manager=None, window_manager=None, plugin_manager=None
    )

    assert runtime.view_classes == [_AView], "the broken one's view survived"
    assert runtime.loaded == ["good"]


def test_a_row_whose_view_failed_to_build_is_dropped():
    """Fail-open must not leave a button that opens nothing."""
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()
    keep = _entry("Licence", view_class=_AView)
    lose = _entry("Updates", view_class=_BView)
    runtime.setup_entries.extend([keep, lose])

    dropped = runtime.drop_rows_missing_views({_BView})

    assert runtime.setup_entries == [keep]
    assert dropped == [lose]


def test_software_rows_are_pruned_as_well():
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()
    lose = _entry("Updates", view_class=_BView)
    runtime.software_entries.append(lose)

    runtime.drop_rows_missing_views({_BView})

    assert runtime.software_entries == []


def test_rows_without_a_declared_view_are_left_alone():
    """view_class is optional — a row that builds its own view, or opens a
    core screen, has no registry dependency to break."""
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()
    plain = _entry("Plain")
    runtime.setup_entries.append(plain)

    runtime.drop_rows_missing_views({_AView, _BView})

    assert runtime.setup_entries == [plain]


def test_nothing_failed_means_nothing_dropped():
    from instrument_cluster.extensions import ExtensionRuntime

    runtime = ExtensionRuntime()
    runtime.setup_entries.append(_entry("Licence", view_class=_AView))

    assert runtime.drop_rows_missing_views(()) == []
    assert len(runtime.setup_entries) == 1
