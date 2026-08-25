"""The Software screen's state: version inventory is passive; this state
owns the factory-reset two-tap confirmation (moved here from Setup when
the row moved) and routes extension-contributed action rows (e.g. the
Pro update flow)."""

from ..extensions import runtime as extensions
from ..logger import Logger
from ..states.state_manager import StateManager
from ..ui.events import BUTTON_BACK_RELEASED, FACTORY_RESET_RELEASED
from ..ui.views.software_view import SoftwareView
from .state import State


class SoftwareState(State):
    # Factory reset is guarded by a two-tap confirmation: the first tap arms
    # the row for this many seconds, a second tap within the window performs
    # the (destructive, irreversible) reset. No tap within the window disarms.
    FACTORY_RESET_ARM_TIMEOUT_S = 5.0

    view_class = SoftwareView

    def __init__(self, state_manager: StateManager | None = None):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        # >0 while the factory-reset row is armed; counts down in update().
        self._factory_reset_armed_s = 0.0

    def update(self, dt):
        super().update(dt)
        # Count down a pending factory-reset confirmation; disarm on timeout.
        if self._factory_reset_armed_s > 0.0:
            self._factory_reset_armed_s -= dt
            if self._factory_reset_armed_s <= 0.0:
                self._disarm_factory_reset()
        self.view.update(dt)

    def exit(self):
        # Leaving the screen cancels a pending factory-reset confirmation,
        # so it never survives to a later visit.
        self._disarm_factory_reset()
        super().exit()

    def handle_event(self, event):
        if self.view.handle_event(event):
            return True

        if event.type == BUTTON_BACK_RELEASED:
            self.state_manager.pop_state()
            return True

        # Rows contributed by extensions (none installed = none shown).
        for entry in extensions.software_entries:
            if event.type == entry.released:
                self.state_manager.push_state(entry.make_state(self.state_manager))
                return True

        if event.type == FACTORY_RESET_RELEASED:
            return self.on_factory_reset_released()

        return False

    def on_factory_reset_released(self):
        """Two-tap guard: first tap arms, second (while armed) resets."""
        if self._factory_reset_armed_s > 0.0:
            self._disarm_factory_reset()
            self._perform_factory_reset()
        else:
            self._factory_reset_armed_s = self.FACTORY_RESET_ARM_TIMEOUT_S
            self.view.set_factory_reset_armed(True)
            self.logger.info("Factory reset armed; awaiting confirming tap")
        return True

    def _disarm_factory_reset(self):
        if self._factory_reset_armed_s > 0.0:
            self.logger.debug("Factory reset disarmed")
        self._factory_reset_armed_s = 0.0
        # exit() disarms, and it can run before enter() ever borrowed a view.
        if self.view is not None:
            self.view.set_factory_reset_armed(False)

    def _perform_factory_reset(self):
        # Imported lazily so importing SoftwareState never pulls the reset
        # machinery (and its subprocess/reboot surface) into scope.
        from ..core.system.factory_reset import perform_factory_reset

        self.logger.warning("Factory reset confirmed by user")
        try:
            perform_factory_reset()
        except Exception:
            # A failed reset must not crash the HMI; log and stay here.
            self.logger.exception("Factory reset failed")
