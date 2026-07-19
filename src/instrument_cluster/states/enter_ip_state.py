from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import ConfigManager
from ..states.install_state import InstallState
from ..states.setup_state import SetupState
from ..states.state import State
from ..ui.events import (
    BUTTON_BACK_RELEASED,
    ENTER_IP_DEL_BUTTON_RELEASED,
    ENTER_IP_KEYPAD_BUTTON_RELEASED,
    ENTER_IP_OK_BUTTON_RELEASED,
)
from ..ui.views.enter_ip_view import EnterIPView

if TYPE_CHECKING:
    from ..addons.feeds import FeedDescriptor
    from ..states.state_manager import StateManager


class EnterIPState(State):
    def __init__(
        self,
        state_manager: StateManager = None,
        descriptor: "FeedDescriptor" = None,
        recent_connected: list[str] | None = None,
    ):
        super().__init__(state_manager)

        self.descriptor = descriptor
        self.view = EnterIPView(
            recent_connected=recent_connected,
            title=descriptor.ip_prompt_title if descriptor else None,
        )

    def background_color(self):
        return self.view.background_color

    def draw_static_background(self, bg):
        self.view.draw_static_elements(bg)

    def create_group(self):
        return None

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        return self.view.draw(surface, self.background)

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

    def handle_event(self, event):
        # 1. View handles click animations / textfield focus
        self.view.handle_event(event)

        # 2. State handles Logic
        if event.type == BUTTON_BACK_RELEASED:
            return self.on_back_released()

        if event.type in (
            ENTER_IP_KEYPAD_BUTTON_RELEASED,
            ENTER_IP_DEL_BUTTON_RELEASED,
        ):
            return self.on_keypad_released(event)

        if event.type == ENTER_IP_OK_BUTTON_RELEASED:
            return self.on_ok_released()

        return False

    def on_back_released(self):
        self.state_manager.change_state(SetupState(self.state_manager))
        return True

    def on_ok_released(self):
        # Access data directly from the view
        ip = self.view.textfield.text.strip()

        if not self.is_valid_ipv4(ip):
            # Optional: Tell view to show error state?
            return True

        self.state_manager.change_state(
            InstallState(self.state_manager, descriptor=self.descriptor, ip=ip)
        )
        ConfigManager.last_connected(ip)
        return True

    def on_keypad_released(self, event):
        label = getattr(event, "label", None)
        if not label:
            return True

        # Manipulate View's TextField
        tf = self.view.textfield
        txt = tf.text

        if label == ".":
            if txt.count(".") < 3 and "." not in txt[-1:]:
                tf.set_text(txt + ".")
        elif label == "<":
            tf.set_text(txt[:-1])
            tf.cursor_position = min(tf.cursor_position, len(tf.text))
        elif label == "#":
            pass
        else:
            if len(label) >= 7:
                # Shortcut button (Recent IP) pressed
                tf.set_text(label)
                self.on_ok_released()
                return True
            else:
                tf.set_text(txt + label)
                tf.cursor_position = len(tf.text)

        tf.dirty = 1
        return True

    def is_valid_ipv4(self, ip_str):
        parts = ip_str.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if part == "":
                return False
            if len(part) > 1 and part.startswith("0"):
                return False
            try:
                num = int(part)
            except ValueError:
                return False
            if num < 0 or num > 255:
                return False
        return True
