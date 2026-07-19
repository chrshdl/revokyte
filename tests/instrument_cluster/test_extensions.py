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
