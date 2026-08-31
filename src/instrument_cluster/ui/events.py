import pygame

BUTTON_SETUP_PRESSED = pygame.event.custom_type()
BUTTON_SETUP_RELEASED = pygame.event.custom_type()
BUTTON_SETUP_LONGPRESSED = pygame.event.custom_type()
BUTTON_SETUP_LONGRELEASED = pygame.event.custom_type()

BUTTON_BACK_PRESSED = pygame.event.custom_type()
BUTTON_BACK_RELEASED = pygame.event.custom_type()

BRIGHTNESS_DOWN_PRESSED = pygame.event.custom_type()
BRIGHTNESS_DOWN_RELEASED = pygame.event.custom_type()
BRIGHTNESS_UP_PRESSED = pygame.event.custom_type()
BRIGHTNESS_UP_RELEASED = pygame.event.custom_type()

TELEMETRY_MODE_PRESSED = pygame.event.custom_type()
TELEMETRY_MODE_RELEASED = pygame.event.custom_type()
TELEMETRY_MODE_SELECTED = pygame.event.custom_type()

ENTER_IP_OK_BUTTON_PRESSED = pygame.event.custom_type()
ENTER_IP_OK_BUTTON_RELEASED = pygame.event.custom_type()
ENTER_IP_KEYPAD_BUTTON_PRESSED = pygame.event.custom_type()
ENTER_IP_KEYPAD_BUTTON_RELEASED = pygame.event.custom_type()
ENTER_IP_DEL_BUTTON_PRESSED = pygame.event.custom_type()
ENTER_IP_DEL_BUTTON_RELEASED = pygame.event.custom_type()

INSTALL_PRESSED = pygame.event.custom_type()
INSTALL_RELEASED = pygame.event.custom_type()

# PC-agent pairing (feeds whose richest channels only exist on the game PC)
AGENT_BASIC_PRESSED = pygame.event.custom_type()
AGENT_BASIC_RELEASED = pygame.event.custom_type()

# Listener-feed setup (feeds that push telemetry to an address we show)
LISTENER_CONTINUE_PRESSED = pygame.event.custom_type()
LISTENER_CONTINUE_RELEASED = pygame.event.custom_type()

CHECK_UPDATES_PRESSED = pygame.event.custom_type()
CHECK_UPDATES_RELEASED = pygame.event.custom_type()

DIFF_REFERENCE_MODE_PRESSED = pygame.event.custom_type()
DIFF_REFERENCE_MODE_RELEASED = pygame.event.custom_type()
DIFF_REFERENCE_MODE_SELECTED = pygame.event.custom_type()

# Dashboard bezel status lights (TC/ASM) on/off
STATUS_LIGHTS_PRESSED = pygame.event.custom_type()
STATUS_LIGHTS_RELEASED = pygame.event.custom_type()
STATUS_LIGHTS_TOGGLED = pygame.event.custom_type()  # event_data: checked (bool)

# Physical shift-light LED bar (Blinkt!)
SHIFT_LIGHTS_PRESSED = pygame.event.custom_type()
SHIFT_LIGHTS_RELEASED = pygame.event.custom_type()
SHIFT_LIGHTS_TOGGLED = pygame.event.custom_type()  # event_data: checked (bool)

# Wi-Fi setup
WIFI_SETUP_PRESSED = pygame.event.custom_type()
WIFI_SETUP_RELEASED = pygame.event.custom_type()

# Software screen (version inventory + factory reset + extension rows)
SOFTWARE_PRESSED = pygame.event.custom_type()
SOFTWARE_RELEASED = pygame.event.custom_type()

# Factory reset (Pi only). Two-tap: the first release arms the row, the
# second within the timeout performs the reset. See SoftwareState.
FACTORY_RESET_PRESSED = pygame.event.custom_type()
FACTORY_RESET_RELEASED = pygame.event.custom_type()

WIFI_NETWORK_SELECTED = pygame.event.custom_type()  # event_data: ssid, secured
WIFI_OTHER_SELECTED = pygame.event.custom_type()  # type a hidden SSID manually

WIFI_RESCAN_PRESSED = pygame.event.custom_type()
WIFI_RESCAN_RELEASED = pygame.event.custom_type()

WIFI_KEY_PRESSED = pygame.event.custom_type()  # event_data: label (single char/space)
WIFI_KEY_RELEASED = pygame.event.custom_type()
WIFI_BACKSPACE_PRESSED = pygame.event.custom_type()
WIFI_BACKSPACE_RELEASED = pygame.event.custom_type()
WIFI_BACKSPACE_LONGPRESSED = pygame.event.custom_type()
WIFI_SHIFT_PRESSED = pygame.event.custom_type()
WIFI_SHIFT_RELEASED = pygame.event.custom_type()
WIFI_MODE_PRESSED = pygame.event.custom_type()  # toggle letters <-> symbols
WIFI_MODE_RELEASED = pygame.event.custom_type()
WIFI_REVEAL_PRESSED = pygame.event.custom_type()  # show/hide password
WIFI_REVEAL_RELEASED = pygame.event.custom_type()

WIFI_CONNECT_PRESSED = pygame.event.custom_type()
WIFI_CONNECT_RELEASED = pygame.event.custom_type()

WIFI_NETWORK_ROW_PRESSED = pygame.event.custom_type()  # visual-only press; no handler
WIFI_OTHER_ROW_PRESSED = pygame.event.custom_type()  # visual-only press; no handler

# Stale-feed notice (ui/feed_update_window.py). Its only action: updating
# is the point of the notice, so there is nothing to decline.
FEED_UPDATE_NOW_PRESSED = pygame.event.custom_type()
FEED_UPDATE_NOW_RELEASED = pygame.event.custom_type()

# Testing & Validation: the standing-start acceleration timer
# (states/accel_test_state.py).
ACCEL_TEST_PRESSED = pygame.event.custom_type()
ACCEL_TEST_RELEASED = pygame.event.custom_type()

ACCEL_DISTANCE_PRESSED = pygame.event.custom_type()
ACCEL_DISTANCE_RELEASED = pygame.event.custom_type()
ACCEL_DISTANCE_SELECTED = pygame.event.custom_type()  # event_data: mode (metres)

ACCEL_RESET_PRESSED = pygame.event.custom_type()
ACCEL_RESET_RELEASED = pygame.event.custom_type()
