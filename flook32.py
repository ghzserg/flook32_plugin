# -*- coding: utf-8 -*-
#
# ============================================================================
# FLOOK32 Sensor for Klipper
# ============================================================================
# 
# Plugin for integrating the FLOOK32 thermal chamber controller into the Klipper ecosystem.
# Provides bidirectional communication: reads air temperature via REST API
# or WebSocket, controls heating via G-code commands, monitors errors.
#
# Copyright (C) 2026 t.me/schreid
# This program is free software under GPLv3.
# Full license text: https://www.gnu.org/licenses/gpl-3.0.html
#
# ═══════════════════════════════════════════════════════════════════════════════
#                              HOW IT WORKS
# ═══════════════════════════════════════════════════════════════════════════════
#
# The plugin registers a virtual temperature sensor in Klipper and communicates
# with FLOOK32 on the local network. Temperature is updated in real time via WebSocket
# (if websocket-client is installed) or periodic HTTP polling (fallback).
#
# ═══════════════════════════════════════════════════════════════════
#                         CONNECTION MODES
# ═══════════════════════════════════════════════════════════════════
#
# 1. MANUAL MODE (flook_ip set in config):
#    • The plugin connects immediately to the specified IP
#    • UDP discovery is not used for connection
#    • On the first HTTP response, sends a UDP request with the device ID
#      so FLOOK32 saves Klipper's IP for Moonraker operation
#    • If connection is lost, keeps trying the same IP
#
# 2. AUTOMATIC MODE (flook_ip not set, auto_discover=True):
#    • The plugin starts a UDP listener on port 12345
#    • Sends a broadcast request FLOOK_DISCOVERY
#    • FLOOK32 responds with TRUE/FALSE (ID match)
#    • On first launch, selects the device with the lowest uptime
#    • Saves the device ID for subsequent connections
#    • On connection loss, restarts UDP discovery
#
# ═══════════════════════════════════════════════════════════════════
#                    TEMPERATURE TRANSMISSION
# ═══════════════════════════════════════════════════════════════════
#
# 1. WEBSOCKET (preferred):
#    • Data arrives in real time (every second)
#    • Format: JSON with fields a (air), h (heater), tg (target)
#    • Automatic reconnection on disconnect
#    • While WebSocket is active, HTTP polling is NOT performed
#
# 2. HTTP POLLING (fallback):
#    • Periodic request GET /api/all
#    • Interval: report_interval (5-60 sec, default 10)
#    • Used when WebSocket is unavailable or not installed
#
# ═══════════════════════════════════════════════════════════════════
#                    UDP DISCOVERY (PROTOCOL)
# ═══════════════════════════════════════════════════════════════════
#
# Request format (plugin → FLOOK32):
#   FLOOK_DISCOVERY:<device_id>   — with ID (if saved)
#   FLOOK_DISCOVERY               — without ID (first launch)
#
# Response format (FLOOK32 → plugin):
#   FLOOK32:TRUE:<IP>:<uptime>:<T_air>:<device_id>   — ID matched
#   FLOOK32:FALSE:<IP>:<uptime>:<T_air>:<device_id>  — ID did not match
#   FLOOK32:<IP>:<uptime>:<T_air>:<device_id>        — old format (without ID)
#
# Device selection logic:
#   • If ID is saved → connects ONLY to the device with TRUE and matching ID
#   • If ID is not saved → selects device with TRUE and lowest uptime
#   • If all devices responded FALSE → active search with ID specified
#
# ═══════════════════════════════════════════════════════════════════
#                    SAVING DEVICE ID
# ═══════════════════════════════════════════════════════════════════
#
# The device ID is saved so that on the next launch
# the plugin can connect to THE SAME FLOOK32, not a random one.
# This is critical if there are multiple printers with FLOOK32 on the network.
#
# Storage locations (in priority order):
#   1. Moonraker DB (http://localhost:7125/server/database/item)
#   2. File ~/.flook32_id (if Moonraker is unavailable)
#
# Reset ID: FLOOK_RESET_ID command in the Klipper console
#
# ═══════════════════════════════════════════════════════════════════
#                    SENDING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
#
# On the first successful connection, the plugin sends to FLOOK32
# ALL parameters explicitly specified in printer.cfg. This allows
# configuring the device directly from the Klipper config.
#
# IMPORTANT: ONLY explicitly specified parameters are sent.
# Parameters not specified in the config remain unchanged
# on the device (default values or previous settings).
#
# ═══════════════════════════════════════════════════════════════════
#                    ERROR MONITORING
# ═══════════════════════════════════════════════════════════════════
#
# The plugin periodically requests /api/error-log and outputs
# FLOOK32 critical errors to the Klipper console with recommendations
# for resolution.
#
# Settings:
#   • enable_error_notifications — on/off monitoring
#   • error_check_interval — check frequency (15-120 sec)
#   • error_notification_max_age — maximum error age
#   • show_trends — show temperature trends before the error
#
# ═══════════════════════════════════════════════════════════════════
#                    G-CODE COMMANDS
# ═══════════════════════════════════════════════════════════════════
#
# The plugin registers 17 G-code commands for controlling FLOOK32
# directly from the Klipper console. Full list in the G-CODE COMMANDS section.
#
# ═══════════════════════════════════════════════════════════════════
#
# CONFIGURATION EXAMPLE:
#   [flook32]
#   
#   [temperature_sensor chamber]
#   sensor_type: flook32
#   flook_ip: 192.168.1.37
#
# INSTALLATION:
#   1. Copy flook32.py to ~/klipper/klippy/extras/             
#   2. Install websocket-client (optional):                   
#      pip install websocket-client 
#   3. Copy flook32.cfg to the folder with printer.cfg
#   4. Add [include flook32.cfg] to printer.cfg                    
#   5. Restart Klipper   
#
# DEPENDENCIES:
#   • Python standard library (always available):
#       - socket, json, threading, select, time, logging, os
#   • websocket-client — OPTIONAL:
#       - For real-time temperature updates
#       - Install: pip install websocket-client
#       - Without it, works via HTTP polling
#   • requests — OPTIONAL:
#       - For saving ID in Moonraker DB
#       - Install: pip install requests
#       - Without it, ID is saved to file ~/.flook32_id
#       - Plugin operation is not affected
#
# AUTHOR: t.me/schreid
# VERSION: 0.1.0b
# ============================================================================

# ============================================================================
# IMPORTS
# ============================================================================

# Python standard library — always available, no installation required
import socket                   # UDP/TCP sockets for communication with FLOOK32
import time                     # Timers, delays, timestamps
import threading                # Parallel threads: UDP listener, WebSocket
import logging                  # Logging to klippy.log (main Klipper log)
import json                     # Parsing JSON responses from FLOOK32 API
import select                   # Non-blocking UDP socket polling (select/poll)
import os                       # File system operations (read/write ~/.flook32_id)
import sys                      # System functions (paths, Python version)

# ============================================================================
# OPTIONAL DEPENDENCIES
# ============================================================================
# These libraries are not mandatory — the plugin works without them.
# They are imported dynamically via try/except to avoid
# import errors when Klipper starts.

# WebSocket client — provides real-time temperature updates.
# Install: pip install websocket-client
# If not installed — the plugin uses HTTP polling (slower).
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False

# Requests — used for saving device ID to Moonraker DB.
# Included in the standard Python distribution in the Klipper environment.
# If unavailable — ID is saved only to file ~/.flook32_id.
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ============================================================================
# CONSTANTS
# ============================================================================

# Temperature limits for the Klipper sensor.
# Going beyond these bounds is considered a sensor error.
MIN_TEMP = -100.0              # Minimum displayed temperature (°C)
MAX_TEMP = 200.0               # Maximum displayed temperature (°C)

# UDP discovery of FLOOK32 on the local network.
# The port must match UDP_PORT in the FLOOK32 firmware.
UDP_PORT = 12345               # Port for sending and receiving UDP packets
UDP_BROADCAST_IP = "255.255.255.255"  # Broadcast address (all devices on the network)

# ============================================================================
# COMPACT PARAMETER MAPPING (COMPACT MAPPING)
# ============================================================================
# 
# When sending configuration to FLOOK32 via POST /api/config, each parameter
# is transmitted in JSON with a short key (2-4 characters) to save traffic and
# packet size. This dictionary maps full parameter names from
# printer.cfg to short FLOOK32 API keys.
#
# Example:
#   printer.cfg:        max_heater_temp: 100.0
#   Short key:          mt
#   JSON to FLOOK32:    {"mt": 100.0}
#
# Used in _send_config_to_esp() when building JSON for sending.

compact_mapping = {
    # ========== TEMPERATURE THRESHOLDS ==========
    'max_heater_temp': 'mt',              # Max. heater temperature (°C)
    'critical_temp': 'ct',                # Critical temperature (°C)
    'critical_hysteresis': 'ch',          # Overheat reset hysteresis (°C)
    'max_air_temp': 'ma',                 # Max. air temperature (°C)
    'air_hysteresis': 'ah',              # Air overheat hysteresis (°C)
    'hysteresis': 'hy',                  # Air control hysteresis (°C)
    'heater_hysteresis': 'hh',           # Heater hysteresis (°C)
    'enable_heater_hysteresis': 'eH',    # Enable heater-based control (bool)
    'default_target_temp': 'dt',         # Default target temperature (°C)
    'invert_heater_signal': 'iH',        # Invert SSR signal (bool)
    'invert_fan_signal': 'iF',           # Invert fan signal (bool)
    'max_fan_duty': 'mFD',               # Max. fan power (0-1023)
    
    # ========== FAN ==========
    'fan_on_temp': 'fT',                 # Fan turn-on temperature (°C)
    'fan_off_hysteresis': 'fH',          # Fan turn-off hysteresis (°C)
    'fan_min_on_time': 'fM',             # Min. operating time (sec)
    'fan_efficiency_timeout': 'fE',      # Efficiency check timeout (sec)
    'fan_efficiency_threshold': 'fF',    # Efficiency threshold (°C)
    'enable_fan_efficiency_check': 'eF', # Enable efficiency check (bool)
    
    # ========== THERMAL RUNAWAY (FOUR-PHASE PROTECTION) ==========
    'enable_thermal_runaway': 'tR',      # Enable protection (bool)
    'runaway_phase1_time': 'r1',         # Phase 1 duration (min)
    'runaway_phase2_time': 'r2',         # Phase 2 duration (min)
    'runaway_max_time_to_target': 'rT',  # Max. time to target (min)
    'runaway_quick_check_temp': 'rQC',   # Phase 0: min. heater temperature after 45 sec (°C)
    'runaway_min_heater_rise': 'rH',     # Min. heater rise (°C/min)
    'runaway_min_air_rise': 'rA',        # Min. air rise (°C/min)
    'runaway_max_heater_drop': 'rD',     # Max. heater drop (°C)
    'runaway_hysteresis': 'rY',          # Trigger hysteresis (°C)
    'runaway_recovery_timeout': 'rR',    # Recovery timeout (sec)
    'runaway_fan_on': 'rF',              # Turn on fan on trigger (bool)
    
    # ========== UNEXPECTED HEAT ==========
    'enable_unexpected_heat': 'uH',      # Enable protection (bool)
    'unexpected_heat_timeout': 'uT',     # Wait timeout (sec)
    'unexpected_heat_threshold': 'uP',   # Trigger threshold (°C)
    'min_cooling_rate': 'mC',            # Min. cooling rate (°C/sec)
    'unexpected_heat_hysteresis': 'uY',  # Reset hysteresis (°C)
    'unexpected_heat_clear_time': 'uC',  # Auto-reset time (ms)
    'unexpected_heat_safe_offset': 'uS', # Safe offset (°C)
    'enable_unexpected_heat_adaptive': 'uA', # Adaptive threshold (bool)
    'adaptive_base_temp': 'aB',          # Base temperature (°C)
    'adaptive_coefficient': 'aC',        # Adaptation coefficient
    'adaptive_min_offset': 'aM',         # Min. adaptive offset (°C)
    
    # ========== RATE OF RISE CONTROL ==========
    'enable_abnormal_rate': 'eA',        # Enable control (bool)
    'abnormal_rate_threshold': 'aT',     # Abnormal rate threshold (°C/sec)
    
    # ========== MAX6675 (THERMOCOUPLE) ==========
    'max6675_offset': 'mO',              # Calibration offset (°C)
    'enable_max6675_protection': 'mP',   # Enable sensor protection (bool)
    'max6675_stability_samples': 'mS',   # Samples for stability
    'max6675_temp_jump_threshold': 'mJ', # Temperature jump threshold (°C)
    'max6675_min_temp': 'mN',            # Min. allowable temperature (°C)
    'max6675_max_temp': 'mX',            # Max. allowable temperature (°C)
    
    # ========== DS18B20 (AIR SENSOR) ==========
    'ds18b20_offset': 'dO',              # Calibration offset (°C)
    'ds18b20_scale': 'dS',               # Scaling coefficient
    'ds18b20_cal_enabled': 'dC',         # Enable calibration (bool)
    'enable_air_sensor_protection': 'aP',# Enable sensor protection (bool)
    'air_sensor_stability_samples': 'aS',# Samples for stability
    'air_sensor_temp_jump_threshold': 'aJ', # Jump threshold (°C)
    'air_sensor_min_temp': 'aN',         # Min. temperature (°C)
    'air_sensor_max_temp': 'aX',         # Max. temperature (°C)
    'air_sensor_unstable_range': 'aU',   # Instability range (°C)
    'air_sensor_unstable_deviation': 'aV', # Deviation (°C)
    'air_sensor_unstable_window': 'aW',  # Analysis window (measurements)
    'air_sensor_direction_changes': 'aD',# Direction changes
    
    # ========== ERRORS AND BLOCKING ==========
    'max_error_retries': 'mR',           # Max. retries before blocking
    'error_window_minutes': 'eW',        # Error counting window (min)
    'min_time_between_same_errors': 'mE',# Min. time between errors (ms)
    'min_time_between_overheat_counts': 'mOc', # Min. time between overheats (ms)
    'unlock_password': 'uPw',            # Unlock password
    'settings_locked': 'sl',             # Settings lock (bool)
    
    # ========== LED INDICATION ==========
    'led_enabled': 'lE',                 # Enable LED (bool)
    'led_count': 'lC',                   # Number of LEDs
    'led_brightness': 'lB',              # Brightness (0-255)
    'led_pin': 'lP',                     # LED pin
    
    # ========== HEARTBEAT (WATCHDOG TIMER) ==========
    'heartbeat_pulse_ms': 'hP',          # Pulse duration (ms)
    'heartbeat_pause_ms': 'hQ',          # Pause between pulses (ms)
    
    # ========== SYSTEM INTERVALS ==========
    'read_interval': 'rI',               # Sensor read interval (ms)
    'control_interval': 'cI',            # Main control loop (ms)
    'trend_interval': 'tI',              # Trend saving interval (ms)
    'heap_check_interval': 'hI',         # Memory check interval (ms)
    'loop_watchdog_timeout': 'lW',       # Task Watchdog timeout (ms)
    'enable_loop_watchdog': 'eL',        # Enable Watchdog (bool)
    'udp_discovery_timeout': 'uD',       # UDP discovery timeout (ms)
    'discovery_retry_interval': 'dR',    # UDP retry interval (ms)
    
    # ========== MOONRAKER AUTO-SHUTDOWN ==========
    'auto_shutdown_enabled': 'aSd',      # Enable auto-shutdown (bool)
    'auto_shutdown_minutes': 'aSm',      # Minutes to wait after printing
    
    # ========== THERMAL MODEL ==========
    'enable_thermal_model': 'tM',        # Enable model (bool)
    'thermal_model_sensitivity': 'tS',   # Sensitivity (0.5-3.0)
    'thermal_model_check_interval': 'tC',# Check interval (ms)
    'thermal_model_log_warnings': 'tL',  # Log warnings (bool)
    
    # ========== HARDWARE PINS ==========
    'pin_ssr': 'pS',                     # SSR pin (heater)
    'pin_fan': 'pF',                     # Fan pin (PWM)
    'pin_watchdog': 'pW',                # Watchdog pin (heartbeat)
    'pin_onewire': 'pO',                 # OneWire pin (DS18B20)
    'pin_max_sck': 'pK',                 # MAX6675 SCK pin
    'pin_max_so': 'pM',                  # MAX6675 SO pin
    'pin_max_cs': 'pC',                  # MAX6675 CS pin
    'pin_buzzer': 'pB',                  # Buzzer pin
    'pin_led': 'pL',                     # LED pin
    
    # ========== CONTROL INTERVALS ==========
    'heater_control_interval': 'hC',     # Heater control interval (ms)
    'fan_control_interval': 'fC',        # Fan control interval (ms)
    'runaway_check_interval': 'rC',      # Runaway check interval (ms)
    'unexpected_check_interval': 'uCc',  # Unexpected Heat check interval (ms)
    'rate_check_interval': 'rAc',        # Rate of rise check interval (ms)
    
    # ========== FAN AUTO-LIMIT ==========
    'enable_fan_auto_limit': 'eFAL',     # Enable auto-limit (bool)
    'fan_auto_limit_hysteresis': 'fALH', # Auto-limit hysteresis (°C)
    'fan_auto_limit_adjust_step': 'fALA',# Duty adjustment step
    'fan_auto_limit_min_duty': 'fALM',   # Minimum duty
    'fan_auto_limit_check_interval': 'fALI', # Check interval (ms)
    'fan_auto_limit_stable_count': 'fALS',# Measurements for stabilization
    'fan_auto_limit_adapted': 'fALAd',   # Auto-limit adaptation flag (bool)
    
    # ========== BUZZER ==========
    'buzzer_enabled': 'bE',              # Enable buzzer (bool)
    'buzzer_non_critical_enabled': 'bN', # Signal on non-critical errors (bool)
    'buzzer_melody': 'bM',               # Melody (0=short, 1=double, 2=alarm)
}

# ============================================================================
# MAIN SENSOR CLASS
# ============================================================================

class FLOOK32Sensor:
    """
    3D printer chamber temperature sensor integrated with the FLOOK32 controller.
    
    The class implements the Klipper sensor interface and provides:
      - Automatic discovery of FLOOK32 on the local network via UDP broadcast
      - Real-time air temperature reading (WebSocket or HTTP)
      - Heating control via G-code commands (17 commands)
      - FLOOK32 error monitoring with output to the Klipper console
      - Sending user configuration to the device
    
    Connection modes:
      1. MANUAL (flook_ip set) — direct connection to the specified IP
      2. AUTOMATIC (auto_discover=True) — discovery via UDP broadcast
    
    Data transmission (in priority order):
      1. WebSocket — real-time updates (if websocket-client is installed)
      2. HTTP polling — periodic requests (interval: report_interval)
    """
    
    def __init__(self, config):
        """
        Sensor initialization when the Klipper plugin loads.
        
        Parameters:
          config — Klipper configuration object containing all settings from printer.cfg
        
        Initialization order:
          1. Load basic connection parameters (IP, port, mode)
          2. Load ALL configuration parameters (temperatures, protections, pins, ...)
          3. Determine explicitly specified parameters (for sending to the device)
          4. Initialize state variables (temperatures, flags, counters)
          5. Load saved device ID
          6. Register G-code commands
          7. Start background threads (UDP listener, polling loop)
        """
        
        # =====================================================================
        # BASIC INITIALIZATION
        # =====================================================================
        
        # Klipper printer object — entry point to the entire system
        self.printer = config.get_printer()
        # Reactor — Klipper task scheduler (used for timers)
        self.reactor = self.printer.get_reactor()
        # Sensor name — the last part of the section name (e.g., "chamber")
        self.name = config.get_name().split()[-1]
        
        logging.info("=" * 60)
        logging.info("FLOOK32 sensor '{}' initialization (mode: air)".format(self.name))
        logging.info("=" * 60)
        
        # =====================================================================
        # CONNECTION PARAMETERS
        # =====================================================================
        
        # IP address of FLOOK32 on the local network
        # If not set — auto-discovery via UDP will be used
        self.flook_ip = config.get('flook_ip', None)
        # HTTP/WebSocket port (default 80)
        self.flook_port = config.getint('flook_port', 80)
        
        # Determine connection mode
        if self.flook_ip:
            # MANUAL MODE: IP specified explicitly, auto-discovery not required
            self.auto_discover = False
            logging.info("Manual mode, IP={}:{}".format(self.flook_ip, self.flook_port))
        else:
            # AUTOMATIC MODE: IP not set, searching via UDP
            self.auto_discover = config.getboolean('auto_discover', True)
            logging.info("Automatic mode, auto-discovery={}".format(
                'enabled' if self.auto_discover else 'disabled'))
        
        # =====================================================================
        # POLLING AND NOTIFICATION PARAMETERS
        # =====================================================================
        
        # Silent mode — disables ALL messages in the Klipper console
        # (logging to file continues regardless of this parameter)
        self.silent_mode = config.getboolean('silent', False)
        if self.silent_mode:
            logging.info("Silent mode enabled")
        
        # HTTP polling interval (used ONLY when WebSocket is unavailable)
        # Range: 5-60 seconds, default 10 seconds
        self.report_interval = config.getfloat('report_interval', 10.0, minval=5.0, maxval=60.0)
        logging.info("Report interval = {} sec".format(self.report_interval))
        
        # =====================================================================
        # ERROR AUTO-NOTIFICATION SETTINGS
        # =====================================================================
        
        # Enable/disable FLOOK32 error monitoring
        self.enable_error_notifications = config.getboolean('enable_error_notifications', True)
        # Maximum error age for output (sec). 0 = no limit
        self.error_notification_max_age = config.getint('error_notification_max_age', 600, minval=0, maxval=86400)
        # Error API check frequency (sec)
        self.error_check_interval = config.getint('error_check_interval', 30, minval=15, maxval=120)
        # Show temperature trends before the error
        self.show_trends = config.getboolean('show_trends', True)
        # Maximum number of trend lines (0 = all)
        self.max_trend_lines = config.getint('max_trend_lines', 30, minval=0, maxval=100)
        
        if self.enable_error_notifications:
            logging.info("Error auto-notifications: ENABLED")
        else:
            logging.info("Error auto-notifications: DISABLED")
        
        # =====================================================================
        # LOADING ALL CONFIGURATION PARAMETERS
        # =====================================================================
        # Each parameter has a default value, valid range
        # and detailed description in printer.cfg.
        # Here they are loaded into object attributes for use in methods.
        
        # --- HEATER PARAMETERS ---
        self.max_heater_temp = config.getfloat('max_heater_temp', 100.0, minval=30, maxval=300)
        self.critical_temp = config.getfloat('critical_temp', 110.0, minval=40, maxval=350)
        self.critical_hysteresis = config.getfloat('critical_hysteresis', 5.0, minval=0.1, maxval=50)
        self.max_air_temp = config.getfloat('max_air_temp', 70.0, minval=20, maxval=200)
        self.air_hysteresis = config.getfloat('air_hysteresis', 3.0, minval=0.1, maxval=50)
        self.hysteresis = config.getfloat('hysteresis', 0.5, minval=0.1, maxval=5.0)
        self.heater_hysteresis = config.getfloat('heater_hysteresis', 4.0, minval=1.0, maxval=30.0)
        self.enable_heater_hysteresis = config.getboolean('enable_heater_hysteresis', True)
        self.default_target_temp = config.getfloat('default_target_temp', 0.0, minval=0, maxval=100)
        self.invert_heater_signal = config.getboolean('invert_heater_signal', False)
        self.max_fan_duty = config.getint('max_fan_duty', 1023, minval=0, maxval=1023)
        
        # --- FAN PARAMETERS ---
        self.fan_on_temp = config.getfloat('fan_on_temp', 55.0, minval=0, maxval=120)
        self.fan_off_hysteresis = config.getfloat('fan_off_hysteresis', 3.0, minval=1, maxval=30)
        self.fan_min_on_time = config.getint('fan_min_on_time', 30, minval=10, maxval=300)
        self.invert_fan_signal = config.getboolean('invert_fan_signal', False)
        self.fan_efficiency_timeout = config.getfloat('fan_efficiency_timeout', 120.0, minval=30, maxval=600)
        self.fan_efficiency_threshold = config.getfloat('fan_efficiency_threshold', 2.0, minval=0.5, maxval=20)
        self.enable_fan_efficiency_check = config.getboolean('enable_fan_efficiency_check', True)
        self.enable_fan_auto_limit = config.getboolean('enable_fan_auto_limit', False)
        self.fan_auto_limit_hysteresis = config.getfloat('fan_auto_limit_hysteresis', 3.0, minval=0.5, maxval=10)
        self.fan_auto_limit_adjust_step = config.getint('fan_auto_limit_adjust_step', 10, minval=1, maxval=20)
        self.fan_auto_limit_min_duty = config.getint('fan_auto_limit_min_duty', 400, minval=0, maxval=1023)
        self.fan_auto_limit_check_interval = config.getint('fan_auto_limit_check_interval', 5000, minval=1000, maxval=30000)
        self.fan_auto_limit_stable_count = config.getint('fan_auto_limit_stable_count', 3, minval=1, maxval=10)
        
        # --- THERMAL RUNAWAY (FOUR-PHASE PROTECTION) ---
        self.enable_thermal_runaway = config.getboolean('enable_thermal_runaway', True)
        self.runaway_phase1_time = config.getint('runaway_phase1_time', 5, minval=1, maxval=30)
        self.runaway_phase2_time = config.getint('runaway_phase2_time', 15, minval=5, maxval=60)
        self.runaway_max_time_to_target = config.getfloat('runaway_max_time_to_target', 30.0, minval=10, maxval=120)
        self.runaway_min_heater_rise = config.getfloat('runaway_min_heater_rise', 2.0, minval=0.5, maxval=30)
        self.runaway_min_air_rise = config.getfloat('runaway_min_air_rise', 0.5, minval=0.1, maxval=10)
        self.runaway_max_heater_drop = config.getfloat('runaway_max_heater_drop', 15.0, minval=5, maxval=50)
        self.runaway_hysteresis = config.getfloat('runaway_hysteresis', 2.0, minval=0.5, maxval=10)
        self.runaway_recovery_timeout = config.getint('runaway_recovery_timeout', 30, minval=10, maxval=300)
        self.runaway_fan_on = config.getboolean('runaway_fan_on', False)
        self.runaway_quick_check_temp = config.getfloat('runaway_quick_check_temp', 60.0, minval=20, maxval=200)
        
        # --- UNEXPECTED HEAT ---
        self.enable_unexpected_heat = config.getboolean('enable_unexpected_heat', True)
        self.unexpected_heat_timeout = config.getfloat('unexpected_heat_timeout', 45.0, minval=5, maxval=300)
        self.unexpected_heat_threshold = config.getfloat('unexpected_heat_threshold', 15.0, minval=5, maxval=50)
        self.min_cooling_rate = config.getfloat('min_cooling_rate', 1.0, minval=0.01, maxval=20)
        self.unexpected_heat_hysteresis = config.getfloat('unexpected_heat_hysteresis', 3.0, minval=0.5, maxval=20)
        self.unexpected_heat_clear_time = config.getint('unexpected_heat_clear_time', 30000, minval=5000, maxval=600000)
        self.unexpected_heat_safe_offset = config.getfloat('unexpected_heat_safe_offset', 10.0, minval=5, maxval=50)
        self.enable_unexpected_heat_adaptive = config.getboolean('enable_unexpected_heat_adaptive', False)
        self.adaptive_base_temp = config.getfloat('adaptive_base_temp', 20.0, minval=10, maxval=40)
        self.adaptive_coefficient = config.getfloat('adaptive_coefficient', 0.3, minval=0, maxval=1)
        self.adaptive_min_offset = config.getfloat('adaptive_min_offset', 30.0, minval=10, maxval=100)
        
        # --- ABNORMAL RATE OF RISE CONTROL ---
        self.enable_abnormal_rate = config.getboolean('enable_abnormal_rate', True)
        self.abnormal_rate_threshold = config.getfloat('abnormal_rate_threshold', 5.0, minval=0.5, maxval=50)
        
        # --- MAX6675 (THERMOCOUPLE) ---
        self.max6675_offset = config.getfloat('max6675_offset', 0.0, minval=-50, maxval=50)
        self.enable_max6675_protection = config.getboolean('enable_max6675_protection', True)
        self.max6675_stability_samples = config.getint('max6675_stability_samples', 3, minval=1, maxval=10)
        self.max6675_temp_jump_threshold = config.getfloat('max6675_temp_jump_threshold', 20.0, minval=5, maxval=100)
        self.max6675_min_temp = config.getfloat('max6675_min_temp', -50.0, minval=-100, maxval=0)
        self.max6675_max_temp = config.getfloat('max6675_max_temp', 400.0, minval=100, maxval=1000)
        
        # --- DS18B20 (AIR SENSOR) ---
        self.ds18b20_offset = config.getfloat('ds18b20_offset', 0.0, minval=-10, maxval=10)
        self.ds18b20_scale = config.getfloat('ds18b20_scale', 1.0, minval=0.9, maxval=1.1)
        self.ds18b20_cal_enabled = config.getboolean('ds18b20_cal_enabled', False)
        self.enable_air_sensor_protection = config.getboolean('enable_air_sensor_protection', True)
        self.air_sensor_stability_samples = config.getint('air_sensor_stability_samples', 5, minval=3, maxval=20)
        self.air_sensor_temp_jump_threshold = config.getfloat('air_sensor_temp_jump_threshold', 2.0, minval=1, maxval=50)
        self.air_sensor_min_temp = config.getfloat('air_sensor_min_temp', -40.0, minval=-100, maxval=0)
        self.air_sensor_max_temp = config.getfloat('air_sensor_max_temp', 125.0, minval=50, maxval=200)
        self.air_sensor_unstable_range = config.getfloat('air_sensor_unstable_range', 3.0, minval=0.5, maxval=20)
        self.air_sensor_unstable_deviation = config.getfloat('air_sensor_unstable_deviation', 1.5, minval=0.1, maxval=10)
        self.air_sensor_unstable_window = config.getint('air_sensor_unstable_window', 10, minval=3, maxval=50)
        self.air_sensor_direction_changes = config.getint('air_sensor_direction_changes', 3, minval=1, maxval=20)
        
        # --- ERROR AND BLOCKING SYSTEM ---
        self.max_error_retries = config.getint('max_error_retries', 3, minval=1, maxval=20)
        self.error_window_minutes = config.getint('error_window_minutes', 10, minval=1, maxval=240)
        self.min_time_between_same_errors = config.getint('min_time_between_same_errors', 30000, minval=1000, maxval=300000)
        self.min_time_between_overheat_counts = config.getint('min_time_between_overheat_counts', 5000, minval=1000, maxval=60000)
        self.unlock_password = config.get('unlock_password', 'unlock')
        self.settings_locked = config.getboolean('settings_locked', True)
        
        # --- LED INDICATION ---
        self.led_enabled = config.getboolean('led_enabled', True)
        self.led_count = config.getint('led_count', 3, minval=1, maxval=100)
        self.led_brightness = config.getint('led_brightness', 50, minval=0, maxval=255)
        self.led_pin = config.getint('led_pin', 27, minval=0, maxval=39)
        
        # --- HEARTBEAT (WATCHDOG TIMER) ---
        self.heartbeat_pulse_ms = config.getint('heartbeat_pulse_ms', 100, minval=10, maxval=1000)
        self.heartbeat_pause_ms = config.getint('heartbeat_pause_ms', 900, minval=100, maxval=10000)
        
        # --- SYSTEM INTERVALS ---
        self.read_interval = config.getint('read_interval', 1000, minval=100, maxval=5000)
        self.control_interval = config.getint('control_interval', 3000, minval=1000, maxval=30000)
        self.trend_interval = config.getint('trend_interval', 5000, minval=500, maxval=10000)
        self.heap_check_interval = config.getint('heap_check_interval', 30000, minval=5000, maxval=60000)
        self.loop_watchdog_timeout = config.getint('loop_watchdog_timeout', 30000, minval=5000, maxval=60000)
        self.enable_loop_watchdog = config.getboolean('enable_loop_watchdog', True)
        self.udp_discovery_timeout = config.getint('udp_discovery_timeout', 30000, minval=5000, maxval=60000)
        self.discovery_retry_interval = config.getint('discovery_retry_interval', 1000, minval=500, maxval=10000)
        
        # --- MOONRAKER AUTO-SHUTDOWN ---
        self.auto_shutdown_enabled = config.getboolean('auto_shutdown_enabled', False)
        self.auto_shutdown_minutes = config.getint('auto_shutdown_minutes', 30, minval=5, maxval=120)
        
        # --- THERMAL MODEL ---
        self.enable_thermal_model = config.getboolean('enable_thermal_model', False)
        self.thermal_model_sensitivity = config.getfloat('thermal_model_sensitivity', 1.0, minval=0.5, maxval=3.0)
        self.thermal_model_check_interval = config.getint('thermal_model_check_interval', 2000, minval=500, maxval=10000)
        self.thermal_model_log_warnings = config.getboolean('thermal_model_log_warnings', True)
        
        # --- HARDWARE PINS ---
        self.pin_ssr = config.getint('pin_ssr', 32, minval=0, maxval=39)
        self.pin_fan = config.getint('pin_fan', 33, minval=0, maxval=39)
        self.pin_watchdog = config.getint('pin_watchdog', 26, minval=0, maxval=39)
        self.pin_onewire = config.getint('pin_onewire', 21, minval=0, maxval=39)
        self.pin_max_sck = config.getint('pin_max_sck', 18, minval=0, maxval=39)
        self.pin_max_so = config.getint('pin_max_so', 19, minval=0, maxval=39)
        self.pin_max_cs = config.getint('pin_max_cs', 5, minval=0, maxval=39)
        self.pin_buzzer = config.getint('pin_buzzer', 25, minval=0, maxval=39)
        self.pin_led = config.getint('pin_led', 27, minval=0, maxval=39)
        
        # --- ADDITIONAL CONTROL INTERVALS ---
        self.heater_control_interval = config.getint('heater_control_interval', 200, minval=50, maxval=1000)
        self.fan_control_interval = config.getint('fan_control_interval', 1000, minval=500, maxval=5000)
        self.runaway_check_interval = config.getint('runaway_check_interval', 5000, minval=1000, maxval=30000)
        self.unexpected_check_interval = config.getint('unexpected_check_interval', 2000, minval=500, maxval=10000)
        self.rate_check_interval = config.getint('rate_check_interval', 1000, minval=500, maxval=5000)
        
        # --- BUZZER ---
        self.buzzer_enabled = config.getboolean('buzzer_enabled', True)
        self.buzzer_non_critical_enabled = config.getboolean('buzzer_non_critical_enabled', False)
        self.buzzer_melody = config.getint('buzzer_melody', 1, minval=0, maxval=2)
        
        # =====================================================================
        # DETERMINING EXPLICITLY SPECIFIED PARAMETERS
        # =====================================================================
        # Parameters NOT in this list are considered "explicitly specified"
        # and will be sent to FLOOK32 on first connection.
        connection_params = ['flook_ip', 'flook_port', 'auto_discover', 'sensor_type', 
                           'sensor_mode', 'min_temp', 'max_temp', 'report_interval',
                           'enable_error_notifications', 'error_notification_max_age', 
                           'error_check_interval', 'silent', 'show_trends', 'max_trend_lines']
        
        self._explicit_params = {}
        
        if hasattr(config, 'get_prefix_options'):
            for param in config.get_prefix_options(''):
                if param not in connection_params:
                    value = config.get(param, None)
                    self._explicit_params[param] = value
        else:
            # Fallback if get_prefix_options is unavailable
            known_params = ['max_heater_temp', 'critical_temp', 'fan_on_temp', 
                          'auto_shutdown_enabled', 'auto_shutdown_minutes']
            for param in known_params:
                try:
                    value = config.get(param, None)
                    if value is not None:
                        self._explicit_params[param] = value
                except:
                    pass
        
        self._has_custom_config = len(self._explicit_params) > 0
        
        # =====================================================================
        # STATE VARIABLES (DATA RECEIVED FROM FLOOK32)
        # =====================================================================
        self.air_temp = 25.0               # Air temperature (DS18B20)
        self.heater_temp = 25.0            # Heater temperature (MAX6675)
        self.target_temp = 0.0             # Target temperature
        self.heater_state = False          # Heater state (on/off)
        self.fan_state = False             # Fan state
        self.fan_duty = 0                  # Fan power (0-1023)
        self.system_locked = False         # System lock flag
        self.lock_message = ""             # Lock reason message
        self.uptime = 0                    # Device uptime (sec)
        self.error_count = 0               # Number of errors in the log
        self.klipper_detected = False      # Klipper detected?
        self.klipper_ip = ""               # Klipper IP
        self.thermal_confidence = 0        # Thermal model confidence (%)
        self.thermal_heater_rate = 0       # Heating rate (°C/min)
        self.thermal_cooling_rate = 0      # Cooling rate (°C/sec)
        self.device_id = None              # Device ID (from /api/all)
        
        # Temperature limits for the Klipper sensor
        self.min_temp = MIN_TEMP          # -100°C
        self.max_temp = MAX_TEMP          # 200°C
        
        # HTTP connection error counters
        self._http_errors = 0             # Current number of consecutive errors
        self._max_http_errors = 5         # Threshold for declaring connection loss
        self.connection_lost_time = 0     # Connection loss time (0 = connected)
        
        # Variables for error auto-notifications
        self._last_error_check_time = 0   # Last error check time
        self._last_critical_ts = 0        # Timestamp of last processed critical error
        self._connected_before = False    # Was there a connection before
        self._device_found_after_reset = False  # Device found after reset?
        
        # Variables for sending configuration
        self._config_sending = False      # Flag: configuration is being sent right now
        self._config_sent_message = False # Has the sending message already been output?
        self._queue_lock = threading.Lock()  # Lock for the sending queue
        self.config_sent = False          # Configuration successfully sent?
        self.config_apply_attempts = 0    # Number of sending attempts
        self.max_config_attempts = 3      # Maximum number of attempts
        
        # =====================================================================
        # OPERATING MODE AND DEVICE ID
        # =====================================================================
        
        # Manual mode: IP specified explicitly, auto-discovery not used
        self.manual_mode = self.flook_ip is not None
        # ID storage method: "moonraker", "file", or None
        self._storage_method = None
        # Moonraker API URL cache
        self._moonraker_url_cache = None
        # Device selected (for auto mode)
        self.device_selected = False
        
        # Flags to prevent repeated warnings
        self._wrong_id_warning_shown = False    # ID mismatch warning
        self._no_device_warning_shown = False   # No devices warning
        self._no_id_warning_shown = False       # No saved ID warning
        
        if not self.manual_mode:
            # Load saved device ID (if any)
            self.saved_device_id = self._load_device_id()
            if self.saved_device_id:
                logging.info("Loaded device ID: {}".format(self.saved_device_id))
        else:
            # In manual mode, ID is not needed
            self.saved_device_id = None
        
        # =====================================================================
        # WEBSOCKET (OPTIONAL, FOR REAL-TIME UPDATES)
        # =====================================================================
        self.ws = None                     # WebSocket object
        self.ws_thread = None              # WebSocket thread
        self.ws_running = False            # WebSocket running flag
        self.ws_connected = False          # Connection flag
        self.ws_reconnect_delay = 10       # Reconnect delay (sec)
        self._ws_error_reported = False    # Has WebSocket error already been output?
        
        # =====================================================================
        # UDP DISCOVERY
        # =====================================================================
        self.udp_running = False           # UDP listener running flag
        self.udp_thread = None             # UDP listener thread
        
        # =====================================================================
        # REGISTRATION IN KLIPPER
        # =====================================================================
        
        # Register the sensor in Klipper as temperature_sensor
        self.printer.add_object("temperature_sensor " + self.name, self)
        
        # Lock for thread-safe temperature access
        self.temp_lock = threading.Lock()
        # Flag to stop all threads (called on Klipper shutdown)
        self.stop_thread = False
        # Queue of deferred notifications (before gcode initialization)
        self._pending_notifications = []
        
        # Get the G-code object for registering commands
        self.gcode = self.printer.lookup_object('gcode')
        # Register 17 G-code commands
        self._safe_register_commands()
        
        # =====================================================================
        # STARTING BACKGROUND THREADS
        # =====================================================================
        
        # Main sensor polling loop (WebSocket or HTTP)
        self.sensor_thread = threading.Thread(target=self._sensor_loop)
        self.sensor_thread.daemon = True
        self.sensor_thread.start()
        
        # UDP listener for auto-discovery (only in automatic mode)
        if not self.manual_mode and self.auto_discover and not self.flook_ip:
            self.udp_running = True
            self.udp_thread = threading.Thread(target=self._udp_discovery_loop)
            self.udp_thread.daemon = True
            self.udp_thread.start()
            logging.info("UDP discovery started")
        
        # Send accumulated notifications (if any)
        self._flush_pending_notifications()
        
        logging.info("FLOOK32 sensor '{}' initialized (mode: air)".format(self.name))
        logging.info("=" * 60)
    
    def _safe_register_commands(self):
        """
        Safe registration of G-code commands.
        
        Uses try/except for each command to avoid
        errors on re-registration (if multiple sensors are in the config).
        """
        commands = [
            ('FLOOK_STATUS', self.cmd_FLOOK_STATUS),
            ('FLOOK_TEMP', self.cmd_FLOOK_TEMP),
            ('FLOOK_SET', self.cmd_FLOOK_SET),
            ('FLOOK_OFF', self.cmd_FLOOK_OFF),
            ('FLOOK_DISCOVER', self.cmd_FLOOK_DISCOVER),
            ('FLOOK_SET_IP', self.cmd_FLOOK_SET_IP),
            ('FLOOK_ADAPT_START', self.cmd_FLOOK_ADAPT_START),
            ('FLOOK_ADAPT_ABORT', self.cmd_FLOOK_ADAPT_ABORT),
            ('FLOOK_ADAPT_STATUS', self.cmd_FLOOK_ADAPT_STATUS),
            ('FLOOK_UNLOCK', self.cmd_FLOOK_UNLOCK),
            ('FLOOK_LOCK', self.cmd_FLOOK_LOCK),
            ('FLOOK_REBOOT', self.cmd_FLOOK_REBOOT),
            ('FLOOK_ERRORS', self.cmd_FLOOK_ERRORS),
            ('FLOOK_CONFIG_GET', self.cmd_FLOOK_CONFIG_GET),
            ('FLOOK_AUTO_SHUTDOWN', self.cmd_FLOOK_AUTO_SHUTDOWN),
            ('FLOOK_AUTO_SHUTDOWN_STATUS', self.cmd_FLOOK_AUTO_SHUTDOWN_STATUS),
            ('FLOOK_RESET_ID', self.cmd_FLOOK_RESET_ID),
            ('FLOOK_CALIBRATE', self.cmd_FLOOK_CALIBRATE),
        ]
        for cmd_name, handler in commands:
            try:
                self.gcode.register_command(cmd_name, handler)
            except:
                pass  # Command already registered by another instance
    
    # =====================================================================
    # HELPER METHODS
    # =====================================================================
    
    def _normalize_id(self, device_id):
        """
        Normalizes the device ID: converts to uppercase
        and pads with zeros on the left to 8 characters (hex format).
        
        Example: "1a2b" → "00001A2B"
        """
        if not device_id:
            return None
        device_id = str(device_id).upper()
        return device_id.zfill(8)
    
    def _send_notification(self, message, is_error=False):
        """
        Sends a notification to the Klipper console and optionally to Moonraker.
        
        Parameters:
          message  — message text
          is_error — True for errors (prefix "!! "), False for info ("// ")
        """
        if is_error:
            logging.error("FLOOK32: {}".format(message))
        else:
            logging.info("FLOOK32: {}".format(message))
        
        # In silent mode, do not output messages to the console
        if self.silent_mode:
            return
        
        prefix = "!! " if is_error else "// "
        final_msg = prefix + "FLOOK32: " + message
        
        # If gcode is not yet initialized — add to queue
        if not hasattr(self, 'gcode') or not self.gcode:
            self._queue_notification(message, is_error)
            return
        
        try:
            self.gcode.respond_raw(final_msg)
        except:
            pass
        
        # For critical errors, also send to Moonraker
        if is_error and HAS_REQUESTS:
            threading.Thread(target=self._send_moonraker_notification, 
                           args=(final_msg, is_error), daemon=True).start()
    
    def _queue_notification(self, message, is_error=False):
        """Adds a notification to the queue if gcode is not yet available."""
        if not hasattr(self, '_pending_notifications'):
            self._pending_notifications = []
        self._pending_notifications.append((message, is_error))
    
    def _flush_pending_notifications(self):
        """Sends all accumulated notifications from the queue."""
        if hasattr(self, '_pending_notifications') and self._pending_notifications:
            for message, is_error in self._pending_notifications:
                self._send_notification(message, is_error)
            self._pending_notifications.clear()
    
    def _send_moonraker_notification(self, message, is_error=False):
        """Sends a notification to Moonraker (if available)."""
        if not HAS_REQUESTS:
            return
        try:
            moonraker_url = self._get_moonraker_url()
            if moonraker_url:
                payload = {"message": message, "type": "error" if is_error else "info"}
                requests.post(moonraker_url + "/server/notification", json=payload, timeout=1)
        except:
            pass
    
    def _get_moonraker_url(self):
        """
        Determines the Moonraker API URL (http://localhost:<port>).
        Iterates over standard ports: 7125, 7126, 7130.
        The result is cached to speed up subsequent calls.
        """
        if self._moonraker_url_cache is not None:
            return self._moonraker_url_cache
        
        for port in [7125, 7126, 7130]:
            url = "http://localhost:{}".format(port)
            try:
                response = requests.get(url + "/server/info", timeout=0.5)
                if response.status_code == 200:
                    self._moonraker_url_cache = url
                    return url
            except:
                continue
        return None
    
    def _save_device_id(self, device_id):
        """
        Saves the device ID.
        Priority: Moonraker DB -> file ~/.flook32_id
        """
        device_id = self._normalize_id(device_id)
        if not device_id:
            return False
        
        saved = False
        moonraker_url = self._get_moonraker_url()
        
        logging.info("=== FLOOK32 SAVING ID ===")
        logging.info("ID: {}".format(device_id))
        logging.info("Moonraker URL: {}".format(moonraker_url))
        logging.info("HAS_REQUESTS: {}".format(HAS_REQUESTS))
        
        if moonraker_url and HAS_REQUESTS:
            try:
                base_url = moonraker_url.rstrip('/')
                logging.info("Base URL: {}".format(base_url))
                
                # Create namespace via PUT
                namespace_url = base_url + "/server/database/namespace?namespace=flook32"
                logging.info("Namespace URL: {}".format(namespace_url))
                
                ns_response = requests.put(namespace_url, timeout=2)
                logging.info("Namespace response status: {}".format(ns_response.status_code))
                logging.info("Namespace response body: {}".format(ns_response.text[:200]))
                
                # Save ID
                payload = {"namespace": "flook32", "key": "device_id", "value": device_id}
                item_url = base_url + "/server/database/item"
                logging.info("Item URL: {}".format(item_url))
                logging.info("Payload: {}".format(payload))
                
                response = requests.post(item_url, json=payload, timeout=2)
                logging.info("Save response status: {}".format(response.status_code))
                logging.info("Save response body: {}".format(response.text[:200]))
                
                if response.status_code in (200, 201):
                    try:
                        resp_data = response.json()
                        if resp_data.get('result') or resp_data.get('value'):
                            logging.info("✅ ID saved to Moonraker DB")
                            self._storage_method = "moonraker"
                            saved = True
                        else:
                            logging.warning("Response does not contain result/value: {}".format(resp_data))
                    except Exception as json_err:
                        logging.warning("Failed to parse JSON: {}".format(json_err))
                        # Still consider it a success if the status is good
                        logging.info("✅ ID saved to Moonraker DB (status {})".format(response.status_code))
                        self._storage_method = "moonraker"
                        saved = True
                else:
                    logging.warning("❌ Save error, status: {}".format(response.status_code))
                    
            except Exception as e:
                logging.error("❌ Moonraker error: {}".format(e))
                import traceback
                logging.error(traceback.format_exc())
        else:
            logging.warning("Moonraker unavailable: url={}, requests={}".format(moonraker_url, HAS_REQUESTS))
        
        # Fallback to file
        if not saved:
            logging.info("Saving to file as fallback...")
            file_path = os.path.expanduser("~/.flook32_id")
            try:
                with open(file_path, 'w') as f:
                    f.write(device_id)
                logging.info("✅ ID saved to file: {}".format(file_path))
                self._storage_method = "file"
                saved = True
            except Exception as e:
                logging.error("❌ Failed to save ID to file: {}".format(e))
        
        return saved
    
    def _load_device_id(self):
        """Loads the saved device ID."""
        # Try Moonraker
        moonraker_url = self._get_moonraker_url()
        if moonraker_url and HAS_REQUESTS:
            try:
                base_url = moonraker_url.rstrip('/')
                response = requests.get(
                    base_url + "/server/database/item?namespace=flook32&key=device_id", 
                    timeout=2)
                
                if response.status_code == 200:
                    data = response.json()
                    # Check for result.value
                    value = data.get('result', {}).get('value')
                    if value:
                        device_id = self._normalize_id(value)
                        if device_id:
                            logging.info("Loaded ID from Moonraker DB: {}".format(device_id))
                            self._storage_method = "moonraker"
                            return device_id
            except Exception as e:
                logging.debug("Moonraker load error: {}".format(e))
        
        # Fallback to file
        file_path = os.path.expanduser("~/.flook32_id")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    device_id = self._normalize_id(f.read().strip())
                    if device_id:
                        logging.info("Loaded ID from file: {}".format(device_id))
                        self._storage_method = "file"
                        return device_id
        except Exception as e:
            logging.debug("File load error: {}".format(e))
        
        return None
    
    def _delete_device_id(self):
        """Deletes the saved device ID."""
        moonraker_url = self._get_moonraker_url()
        if moonraker_url and HAS_REQUESTS:
            try:
                requests.delete(
                    moonraker_url + "/server/database/item?namespace=flook32&key=device_id", 
                    timeout=2)
            except:
                pass
        
        file_path = os.path.expanduser("~/.flook32_id")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass
        
        self._storage_method = None
    
    # =====================================================================
    # HTTP COMMUNICATION WITH FLOOK32
    # =====================================================================
    
    def _http_get_json(self, path, timeout=3):
        """
        Performs an HTTP GET request to FLOOK32 and parses JSON from the response.
        
        Implementation features:
          • Uses low-level sockets (no requests) — minimal dependencies
          • Manual search for JSON in the response (skips HTTP headers)
          • Bracket balancing for precise JSON end detection
          • Protection against partial responses
        """
        if not self.flook_ip:
            return None
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.flook_ip, self.flook_port))
            
            request = "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n".format(path, self.flook_ip)
            sock.send(request.encode())
            
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            sock.close()
            
            text = response.decode('utf-8', errors='ignore')
            
            # Find the start of JSON ([ or {)
            start = -1
            for i, char in enumerate(text):
                if char in ['[', '{']:
                    start = i
                    break
            
            if start == -1:
                return None
            
            json_str = text[start:]
            
            # Find the end of JSON considering nesting and strings
            bracket_count = 0
            in_string = False
            escape = False
            end = 0
            
            for i, char in enumerate(json_str):
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"' and not escape:
                    in_string = not in_string
                    continue
                if not in_string:
                    if char in ['[', '{']:
                        bracket_count += 1
                    elif char in [']', '}']:
                        bracket_count -= 1
                        if bracket_count == 0:
                            end = i + 1
                            break
            
            if end == 0:
                return None
            
            json_str = json_str[:end]
            return json.loads(json_str)
            
        except:
            self._http_errors += 1
            return None
    
    def _http_post(self, path, data=None, timeout=3):
        """
        Performs an HTTP POST request to FLOOK32.
        Supports sending data in URL-encoded format.
        """
        if not self.flook_ip:
            return None
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.flook_ip, self.flook_port))
            
            body = ""
            if data:
                if isinstance(data, dict):
                    body = "&".join([k + "=" + v for k, v in data.items()])
                else:
                    body = str(data)
            
            request = "POST {} HTTP/1.1\r\nHost: {}\r\n".format(path, self.flook_ip)
            if body:
                request += "Content-Length: {}\r\n".format(len(body))
            request += "Connection: close\r\n\r\n"
            if body:
                request += body
            
            sock.send(request.encode())
            time.sleep(0.3)  # Give ESP32 time to process the request
            response = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except:
                    break
            response = response.decode()
            sock.close()
            
            if '\r\n\r\n' in response:
                return response.split('\r\n\r\n', 1)[1]
            return response
        except:
            return None
    
    def _async_run(self, work_fn, on_result=None):
        """
        Executes work_fn() in a separate (non-reactor) thread to avoid
        blocking the main Klippy thread with network I/O.

        IMPORTANT: it was precisely the blocking calls to _http_get_json/_http_post
        directly from G-code handlers (cmd_FLOOK_*) that caused "Timer too close" /
        MCU shutdown on weak hosts — the Klipper reactor could not send commands
        to the MCU in time while waiting for a network response.

        If on_result is passed, it will be called with the result of work_fn(),
        but marshaled back to the main thread via
        reactor.register_async_callback — so inside on_result you can
        safely call gcode.respond_info(...) and modify self state.
        """
        def _worker():
            try:
                result = work_fn()
            except Exception as e:
                logging.exception("FLOOK32 '{}': background request error: {}".format(self.name, e))
                result = None
            if on_result:
                try:
                    self.reactor.register_async_callback(
                        (lambda et, _r=result: on_result(_r)))
                except Exception:
                    # For older Klipper versions without register_async_callback —
                    # better to show the result slightly less "safely" than lose it silently.
                    on_result(result)
        threading.Thread(target=_worker, daemon=True).start()

    def _send_config_to_esp(self):
        """
        Sends the user configuration to FLOOK32.
        
        Algorithm:
          1. Unlocks settings via /api/unlock-settings
          2. Sends JSON with configuration via POST /api/config
          3. Locks settings back via /api/lock-settings
        """
        if not self.flook_ip or not self._has_custom_config:
            return False
        
        with self._queue_lock:
            if self._config_sending:
                return False
            self._config_sending = True
        
        try:
            config_data = {}
            for cfg_name, short_name in compact_mapping.items():
                if cfg_name in self._explicit_params and hasattr(self, cfg_name):
                    value = getattr(self, cfg_name)
                    if isinstance(value, bool):
                        value = 1 if value else 0
                    config_data[short_name] = value
            
            if not config_data:
                return True
            
            unlock_result = self._http_post(
                "/api/unlock-settings?password={}".format(self.unlock_password), timeout=2)
            
            if not unlock_result:
                return False
            unlock_lower = unlock_result.lower()
            if "unlocked" not in unlock_lower and "already" not in unlock_lower:
                return False
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((self.flook_ip, self.flook_port))
            body = json.dumps(config_data)
            request = "POST /api/config HTTP/1.1\r\n"
            request += "Host: {}\r\n".format(self.flook_ip)
            request += "Content-Type: application/json\r\n"
            request += "Content-Length: {}\r\n".format(len(body))
            request += "Connection: close\r\n\r\n"
            request += body
            sock.send(request.encode())
            response = sock.recv(4096).decode()
            sock.close()
            
            if "OK" in response or "OK_RESTART" in response:
                self._lock_settings()
                
                if "OK_RESTART" in response:
                    self.flook_ip = None
                    self.discovery_complete = False
                return True
            return False
        except:
            return False
        finally:
            with self._queue_lock:
                self._config_sending = False
    
    def _lock_settings(self):
        """Locks settings on the device (protection against accidental changes)."""
        if not self.flook_ip:
            return False
        try:
            self._http_post("/api/lock-settings", timeout=2)
            return True
        except:
            return False
    
    def _update_from_api(self):
        """
        Retrieves and parses data from FLOOK32 via HTTP GET /api/all.
        
        Updates all local state variables.
        On connection loss, starts the reconnection procedure.
        """
        if not self.flook_ip:
            return False
        
        data = self._http_get_json("/api/all", timeout=2)
        if not data:
            self._http_errors += 1
            if self._http_errors >= self._max_http_errors and self.connection_lost_time == 0:
                self.connection_lost_time = time.time()
                self._send_notification("Connection lost to {}".format(self.flook_ip), is_error=True)
                if not self.manual_mode:
                    self.flook_ip = None
                    self.discovery_complete = False
                    self.auto_discover = True
            return False
        
        was_lost = (self.connection_lost_time != 0)
        self._http_errors = 0
        
        if was_lost:
            downtime = time.time() - self.connection_lost_time
            self.connection_lost_time = 0
            logging.info("Connection to FLOOK32 {} restored (downtime: {:.1f} sec)".format(
                self.flook_ip, downtime))
            self._send_notification("Connection to FLOOK32 restored (downtime: {:.1f} sec)".format(
                downtime), is_error=False)
            self.auto_discover = False
        
        was_first_connection = not self._connected_before
        
        with self.temp_lock:
            # Parse compact JSON response (short keys to save traffic).
            # Each field is protected separately: a broken/unexpected type of one field
            # (for example, if the firmware temporarily sends garbage) should not
            # cause an unhandled exception and stop the entire thread.
            if 't' in data:
                try:
                    self.target_temp = float(data['t'])
                except (TypeError, ValueError):
                    pass
            if 's' in data:
                try:
                    state = int(data['s'])
                    self.heater_state = (state & 1) != 0  # Bit 0 = heater
                    self.fan_state = (state & 2) != 0     # Bit 1 = fan
                except (TypeError, ValueError):
                    pass
            if 'fp' in data:
                try:
                    self.fan_duty = int(data['fp'])
                except (TypeError, ValueError):
                    pass
            if 'a' in data:
                try:
                    temp = float(data['a'])
                    if MIN_TEMP <= temp <= MAX_TEMP:
                        self.air_temp = temp
                except (TypeError, ValueError):
                    pass
            if 'h' in data:
                try:
                    temp = float(data['h'])
                    if MIN_TEMP <= temp <= MAX_TEMP:
                        self.heater_temp = temp
                except (TypeError, ValueError):
                    pass
            if 'u' in data:
                self.uptime = data.get('u')
            if 'l' in data:
                try:
                    self.system_locked = data['l'] == 1
                except (TypeError, ValueError):
                    pass
            if 'e' in data:
                self.error_count = data.get('e')
            
            if 'id' in data:
                self.device_id = self._normalize_id(data['id'])
                
                if not self.saved_device_id:
                    self.saved_device_id = self.device_id
                    self._save_device_id(self.device_id)
                
                if was_first_connection and not self._device_found_after_reset:
                    logging.info("Device found, ID={}".format(self.device_id))
                    # In manual mode, send a UDP request with ID once
                    if self.manual_mode and self.saved_device_id:
                        self._send_manual_udp_discovery()
                    self._device_found_after_reset = True
                    self._connected_before = True
                    if self.saved_device_id:
                        self.discovery_complete = False
        
        return True
    
    # =====================================================================
    # UDP DISCOVERY (UNIFIED METHOD)
    # =====================================================================
    
    def _connect_to(self, ip, device_id):
        """
        Connects to the discovered device.
        If already connected to the same IP — do not spam notifications.
        """
        if self.flook_ip == ip and self.discovery_complete:
            return
        
        self.flook_ip = ip
        self.discovery_complete = True
        self.auto_discover = False
        
        if device_id and not self.saved_device_id:
            self.saved_device_id = device_id
            self._save_device_id(device_id)
        
        logging.info("UDP: connected to {}, ID={}".format(ip, device_id))
        self._send_notification("FLOOK32 found (IP: {}, ID: {})".format(
            ip, device_id if device_id else 'None'))
        
        if HAS_WEBSOCKET:
            self._start_websocket()

    def _send_manual_udp_discovery(self):
        """
        Sends a single UDP request with ID in manual mode.
        This allows FLOOK32 to save Klipper's IP for Moonraker operation.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            msg = "FLOOK_DISCOVERY:{}".format(self.saved_device_id)
            sock.sendto(msg.encode(), (UDP_BROADCAST_IP, UDP_PORT))
            sock.close()
            logging.info("Manual mode: UDP request with ID sent to broadcast")
        except Exception as e:
            logging.debug("Manual mode: UDP error: {}".format(e))
    
    def _udp_discovery_loop(self):
        """
        Unified UDP discovery loop. Sends a broadcast request
        and waits for responses from FLOOK32. Runs in one thread with one socket.
        
        Sends a request with ID (if saved), receives TRUE/FALSE,
        connects to the desired device.
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', UDP_PORT))
            sock.settimeout(2.0)
        except Exception as e:
            logging.error("UDP: failed to open socket: {}".format(e))
            return
        
        while self.udp_running and not self.stop_thread:
            if self.flook_ip and self.discovery_complete:
                time.sleep(5)
                continue
            
            try:
                if self.saved_device_id:
                    msg = "FLOOK_DISCOVERY:{}".format(self.saved_device_id)
                else:
                    msg = "FLOOK_DISCOVERY"
                
                sock.sendto(msg.encode(), (UDP_BROADCAST_IP, UDP_PORT))
                
                start = time.time()
                while time.time() - start < 3.0:
                    try:
                        data, addr = sock.recvfrom(1024)
                        response = data.decode().strip()
                        
                        if not response.startswith("FLOOK32:"):
                            continue
                        
                        parts = response.split(':')
                        
                        if len(parts) >= 6 and parts[1] in ('TRUE', 'FALSE'):
                            match_status = parts[1].upper() == 'TRUE'
                            ip = parts[2]
                            device_id = self._normalize_id(parts[5]) if len(parts) > 5 else None
                        elif len(parts) == 5 and parts[1].count('.') == 3:
                            match_status = True
                            ip = parts[1]
                            device_id = self._normalize_id(parts[4]) if len(parts) > 4 else None
                        else:
                            continue
                        
                        logging.debug("UDP response: {}, match={}, ID={}".format(ip, match_status, device_id))
                        
                        if self.saved_device_id:
                            if match_status and device_id == self.saved_device_id:
                                self._connect_to(ip, device_id)
                                break
                        else:
                            if match_status:
                                self._connect_to(ip, device_id)
                                break
                                
                    except socket.timeout:
                        break
                        
            except Exception as e:
                logging.debug("UDP error: {}".format(e))
            
            time.sleep(30 if self.flook_ip else 5)
        
        if sock:
            sock.close()
    
    # =====================================================================
    # WEBSOCKET (REAL-TIME UPDATES)
    # =====================================================================
    
    def _start_websocket(self):
        """Starts a WebSocket connection to FLOOK32."""
        if not HAS_WEBSOCKET or not self.flook_ip:
            return
        
        if self.ws_thread and self.ws_thread.is_alive():
            return
        
        self.ws_running = True
        self.ws_thread = threading.Thread(target=self._websocket_loop)
        self.ws_thread.daemon = True
        self.ws_thread.start()
    
    def _websocket_loop(self):
        """WebSocket loop with automatic reconnection on disconnect."""
        while self.ws_running and not self.stop_thread:
            try:
                url = "ws://{}:{}/ws".format(self.flook_ip, self.flook_port)
                self.ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except:
                pass
            
            if self.ws_running and not self.stop_thread:
                time.sleep(self.ws_reconnect_delay)
    
    def _on_ws_open(self, ws):
        """Callback: WebSocket connection established."""
        self.ws_connected = True
        logging.info("WebSocket connected to {}".format(self.flook_ip))
    
    def _on_ws_message(self, ws, message):
        """Callback: WebSocket message with metrics received."""
        try:
            data = json.loads(message)
            with self.temp_lock:
                if 'a' in data:
                    try:
                        temp = float(data['a'])
                        if MIN_TEMP <= temp <= MAX_TEMP:
                            self.air_temp = temp
                    except:
                        pass
                if 'h' in data:
                    try:
                        temp = float(data['h'])
                        if MIN_TEMP <= temp <= MAX_TEMP:
                            self.heater_temp = temp
                    except:
                        pass
                if 'tg' in data:
                    self.target_temp = float(data['tg'])
                if 'hs' in data:
                    self.heater_state = bool(data['hs'])
                if 'fs' in data:
                    self.fan_state = bool(data['fs'])
                if 'fp' in data:
                    self.fan_duty = int(data['fp'])
                if 'id' in data:
                    self.device_id = self._normalize_id(data['id'])
        except:
            pass
    
    def _on_ws_error(self, ws, error):
        """Callback: WebSocket error."""
        self.ws_connected = False
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Callback: WebSocket connection closed."""
        self.ws_connected = False
    
    def _stop_websocket(self):
        """Stops the WebSocket connection and thread."""
        self.ws_running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None
        self.ws_connected = False
    
    # =====================================================================
    # FLOOK32 ERROR MONITORING
    # =====================================================================
    
    def _check_and_report_errors(self):
        """
        Checks the FLOOK32 error log via API and notifies about new
        critical errors in the Klipper console.
        
        Each error is output only once (tracked by timestamp).
        Old errors are ignored according to error_notification_max_age.
        """
        if not self.enable_error_notifications or not self.flook_ip:
            return
        
        current_time = time.time()
        if current_time - self._last_error_check_time < self.error_check_interval:
            return
        
        self._last_error_check_time = current_time
        
        data = self._http_get_json("/api/error-log", timeout=2)
        if not data:
            return
        
        errors_list = data if isinstance(data, list) else data.get('errorLog', [])
        if not errors_list:
            return
        
        current_uptime_sec = self.uptime if self.uptime > 0 else 0
        sorted_errors = sorted(errors_list, key=lambda x: x.get('ts', 0))
        
        for err in sorted_errors:
            ts_sec = err.get('ts', 0)
            error_age = current_uptime_sec - ts_sec
            
            if self.error_notification_max_age > 0 and error_age > self.error_notification_max_age:
                continue
            
            sev = err.get('sev', err.get('severity', 'info'))
            if sev != 'critical':
                continue
            
            if ts_sec <= self._last_critical_ts:
                continue
            
            self._last_critical_ts = ts_sec
            
            msg = err.get('msg', err.get('message', ''))
            hours = ts_sec // 3600
            minutes = (ts_sec % 3600) // 60
            seconds = ts_sec % 60
            time_str = "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)
            count = err.get('count', 1)
            count_str = " (x{})".format(count) if count > 1 else ""
            
            error_message = "CRITICAL ERROR [{}]: {}{}".format(time_str, msg, count_str)
            self._send_notification(error_message, is_error=True)
            
            recommendations = self._get_recommendations_text(msg)
            if recommendations:
                self._send_notification(recommendations, is_error=True)
    
    def _get_recommendations_text(self, error_msg):
        """Returns recommendations for resolving typical errors."""
        if 'HEATER OVERHEAT' in error_msg or 'criticalOverheat' in error_msg:
            return "Recommendations: check SSR, heater and fan"
        elif 'AIR OVERHEAT' in error_msg or 'airOverheat' in error_msg:
            return "Recommendations: check air circulation"
        elif 'THERMAL RUNAWAY' in error_msg:
            return "Recommendations: check 220V power and MAX6675 temperature sensor"
        elif 'MAX6675' in error_msg:
            return "Recommendations: check MAX6675 and thermocouple connection"
        elif 'DS18B20' in error_msg:
            return "Recommendations: check DS18B20 connection"
        else:
            return "Recommendations: check FLOOK32 connection and error log"
    
    # =====================================================================
    # MAIN POLLING LOOP
    # =====================================================================
    
    def _sensor_loop(self):
        """
        Main sensor operation loop. Runs in a separate thread.
        
        Tasks:
          • Periodic polling of FLOOK32 (HTTP or WebSocket)
          • Sending configuration on first connection
          • Checking FLOOK32 errors
          • Passing temperature to Klipper via callback
        """
        mcu = self.printer.lookup_object('mcu')
        last_error_check = 0
        
        while not self.stop_thread:
            try:
                current_time = time.time()

                # Check FLOOK32 errors
                if current_time - last_error_check >= self.error_check_interval:
                    last_error_check = current_time
                    try:
                        self._check_and_report_errors()
                    except Exception:
                        logging.exception(
                            "FLOOK32 '{}': error checking error log".format(self.name))

                if self.flook_ip:
                    # Start WebSocket if available
                    if HAS_WEBSOCKET and not self.ws_connected and not self.ws_thread:
                        self._start_websocket()

                    # Send configuration on first connection
                    if (self._has_custom_config and not self.config_sent and
                        self.config_apply_attempts < self.max_config_attempts):
                        with self._queue_lock:
                            sending = self._config_sending
                        if not sending:
                            if self._send_config_to_esp():
                                self.config_sent = True
                                if not self._config_sent_message:
                                    self._send_notification("Configuration saved")
                                    self._config_sent_message = True
                            else:
                                self.config_apply_attempts += 1

                    # HTTP polling (if WebSocket is not connected)
                    if not self.ws_connected:
                        self._update_from_api()

                    # Pass temperature to Klipper
                    with self.temp_lock:
                        temp = self.air_temp

                    measured_time = self.reactor.monotonic()
                    print_time = mcu.estimated_print_time(measured_time)
                    if hasattr(self, '_callback'):
                        self._callback(print_time, temp)
            except Exception:
                # Any unexpected error (network, parsing, mcu not ready yet, etc.)
                # should not kill the sensor thread permanently — otherwise temperature
                # will stop updating until Klipper is restarted.
                logging.exception(
                    "FLOOK32 '{}': unhandled error in polling loop".format(self.name))

            time.sleep(self.report_interval)
    
    # =====================================================================
    # G-CODE COMMANDS
    # =====================================================================
    
    def cmd_FLOOK_STATUS(self, gcmd):
        """FLOOK_STATUS — show full device status."""
        with self.temp_lock:
            status = "═══ FLOOK32 '{}' ═══\n".format(self.name)
            status += "Sensor mode: air\n"
            if self.manual_mode:
                status += "Connection mode: MANUAL\nIP: {}:{}\n".format(self.flook_ip, self.flook_port)
            elif self.flook_ip:
                status += "Connection mode: AUTOMATIC\nIP: {}:{}\n".format(self.flook_ip, self.flook_port)
            else:
                status += "Connection mode: AUTOMATIC\nIP: Not connected\n"
            status += "Air: {:.1f}°C\n".format(self.air_temp)
            status += "Heater: {:.1f}°C\n".format(self.heater_temp)
            status += "Target: {:.1f}°C\n".format(self.target_temp)
            status += "Locked: {}\n".format('YES' if self.system_locked else 'NO')
            status += "Errors: {}\n".format(self.error_count)
            gcmd.respond_info(status)
    
    def cmd_FLOOK_TEMP(self, gcmd):
        """FLOOK_TEMP — show current temperature."""
        with self.temp_lock:
            gcmd.respond_info("Air: {:.1f}°C, Heater: {:.1f}°C".format(
                self.air_temp, self.heater_temp))
    
    def cmd_FLOOK_SET(self, gcmd):
        """FLOOK_SET S=<temperature> — set target temperature."""
        temp = gcmd.get_float('S', 0.0)
        if temp < 0 or temp > 70:
            gcmd.respond_info("Temperature must be between 0 and 70°C")
            return
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result and ("OK" in result or "success" in result):
                with self.temp_lock:
                    self.target_temp = temp
                self.gcode.respond_info("Target temperature set to {}°C".format(temp))
            else:
                self.gcode.respond_info("Failed to set temperature")

        self._async_run(
            lambda: self._http_post("/api/target?value={}".format(temp)), _done)
    
    def cmd_FLOOK_OFF(self, gcmd):
        """FLOOK_OFF — emergency heater shutdown (does not block the Klipper reactor)."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result and ("OK" in result or "success" in result):
                self.gcode.respond_info("Heating turned off")
            else:
                self.gcode.respond_info("Failed to turn off heating")

        self._async_run(lambda: self._http_post("/api/heater-off"), _done)
    
    def cmd_FLOOK_DISCOVER(self, gcmd):
        """FLOOK_DISCOVER — forced device discovery on the network (non-blocking)."""
        gcmd.respond_info("Searching for devices...")

        def _wait_and_report():
            # Previously there was a time.sleep(5) right in the command handler —
            # this blocked the Klipper reactor for 5 seconds. Now we wait
            # in a background thread while the reactor works as usual.
            time.sleep(5)
            return self.flook_ip, self.saved_device_id

        def _done(result):
            ip, device_id = result
            if ip:
                self.gcode.respond_info("Device found: {}, ID: {}".format(ip, device_id))
            else:
                self.gcode.respond_info("No devices found")

        self._async_run(_wait_and_report, _done)
    
    def cmd_FLOOK_SET_IP(self, gcmd):
        """FLOOK_SET_IP IP=<address> — set IP manually."""
        ip = gcmd.get('IP')
        if not ip:
            gcmd.respond_info("Usage: FLOOK_SET_IP IP=192.168.1.100")
            return
        try:
            socket.inet_aton(ip)
            self.flook_ip = ip
            self.auto_discover = False
            self.discovery_complete = True
            self._http_errors = 0
            if HAS_WEBSOCKET:
                self._start_websocket()
            gcmd.respond_info("IP set to {}".format(ip))
        except:
            gcmd.respond_info("Invalid IP: {}".format(ip))
    
    def cmd_FLOOK_ADAPT_START(self, gcmd):
        """FLOOK_ADAPT_START TARGET=<°C> — start adaptation."""
        target = gcmd.get_float('TARGET', 60.0, minval=40, maxval=70)
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result and "started" in result.lower():
                self.gcode.respond_info("Adaptation started up to {}°C".format(target))
            else:
                self.gcode.respond_info("Failed to start adaptation")

        self._async_run(
            lambda: self._http_post("/api/adapt/start?target={}".format(target)), _done)
    
    def cmd_FLOOK_ADAPT_ABORT(self, gcmd):
        """FLOOK_ADAPT_ABORT — abort adaptation."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result:
                self.gcode.respond_info("Adaptation aborted")
            else:
                self.gcode.respond_info("Failed to abort adaptation")

        self._async_run(lambda: self._http_post("/api/adapt/abort"), _done)
    
    def cmd_FLOOK_ADAPT_STATUS(self, gcmd):
        """FLOOK_ADAPT_STATUS — adaptation status."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(data):
            if data:
                status = "Adaptation: {}\n".format('ON' if data.get('inProgress') else 'OFF')
                status += "Progress: {}%\n".format(data.get('progress', 0))
                status += "Message: {}".format(data.get('message', ''))
                self.gcode.respond_info(status)
            else:
                self.gcode.respond_info("Failed to get status")

        self._async_run(lambda: self._http_get_json("/api/adapt/status"), _done)
    
    def cmd_FLOOK_UNLOCK(self, gcmd):
        """FLOOK_UNLOCK [PASSWORD=<password>] — unlock settings."""
        password = gcmd.get('PASSWORD', self.unlock_password)
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result and "unlocked" in result.lower():
                self.gcode.respond_info("Settings unlocked")
            else:
                self.gcode.respond_info("Failed to unlock")

        self._async_run(
            lambda: self._http_post("/api/unlock-settings?password={}".format(password)), _done)
    
    def cmd_FLOOK_LOCK(self, gcmd):
        """FLOOK_LOCK — lock settings."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result:
                self.gcode.respond_info("Settings locked")
            else:
                self.gcode.respond_info("Failed to lock")

        self._async_run(lambda: self._http_post("/api/lock-settings"), _done)
    
    def cmd_FLOOK_REBOOT(self, gcmd):
        """FLOOK_REBOOT — reboot FLOOK32 (does not block the reactor)."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return
        gcmd.respond_info("Rebooting FLOOK32...")

        def _work():
            self._http_post("/api/reboot")
            return True

        def _done(_result):
            if HAS_WEBSOCKET:
                self._stop_websocket()
            self.flook_ip = None
            self.discovery_complete = False
            self.config_sent = False
            self._config_sent_message = False
            self._http_errors = 0
            self.gcode.respond_info("Command sent")

        self._async_run(_work, _done)
    
    def cmd_FLOOK_ERRORS(self, gcmd):
        """FLOOK_ERRORS — show error log (last 10 entries)."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(data):
            if not data:
                self.gcode.respond_info("Failed to get error log")
                return
            errors_list = data if isinstance(data, list) else data.get('errorLog', [])
            if not errors_list:
                self.gcode.respond_info("Error log is empty")
                return
            self.gcode.respond_info("=== ERROR LOG ===")
            for err in errors_list[-10:]:
                ts = err.get('ts', 0)
                hours = ts // 3600
                minutes = (ts % 3600) // 60
                seconds = ts % 60
                msg = err.get('msg', err.get('message', ''))
                sev = err.get('sev', err.get('severity', 'info'))
                icon = "🔥" if sev == "critical" else "⚠️" if sev == "warning" else "ℹ️"
                self.gcode.respond_info("{} [{:02d}:{:02d}:{:02d}] {}".format(
                    icon, hours, minutes, seconds, msg))

        self._async_run(lambda: self._http_get_json("/api/error-log"), _done)
    
    def cmd_FLOOK_CONFIG_GET(self, gcmd):
        """FLOOK_CONFIG_GET — show current device configuration."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(data):
            if not data:
                self.gcode.respond_info("Failed to get configuration")
                return
            status = "⚙️ FLOOK32 CONFIGURATION:\n"
            status += "  maxHeaterTemp: {}°C\n".format(data.get('mt', 0))
            status += "  criticalTemp: {}°C\n".format(data.get('ct', 0))
            status += "  maxAirTemp: {}°C\n".format(data.get('ma', 0))
            status += "  hysteresis: {}°C\n".format(data.get('hy', 0))
            status += "  heaterHysteresis: {}°C\n".format(data.get('hh', 0))
            status += "  fanOnTemp: {}°C\n".format(data.get('fT', 0))
            status += "  maxFanDuty: {}\n".format(data.get('mFD', 1023))
            status += "  invertHeaterSignal: {}\n".format('Yes' if data.get('iH') else 'No')
            status += "  invertFanSignal: {}\n".format('Yes' if data.get('iF') else 'No')
            status += "  autoShutdownEnabled: {}\n".format('Yes' if data.get('aSd') else 'No')
            status += "  autoShutdownMinutes: {}\n".format(data.get('aSm', 30))
            status += "  adaptationPerformed: {}\n".format('Yes' if data.get('aPd') else 'No')
            self.gcode.respond_info(status)

        self._async_run(lambda: self._http_get_json("/api/config"), _done)
    
    def cmd_FLOOK_AUTO_SHUTDOWN(self, gcmd):
        """FLOOK_AUTO_SHUTDOWN [ENABLE=1] [MINUTES=30] — configure auto-shutdown."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return
        enable = gcmd.get_int('ENABLE', None)
        minutes = gcmd.get_int('MINUTES', None)
        params = []
        if enable is not None:
            params.append("enable={}".format('1' if enable == 1 else '0'))
        if minutes is not None:
            params.append("minutes={}".format(minutes))
        if params:
            query = '&'.join(params)

            def _done(result):
                if result and ("OK" in result or "success" in result):
                    self.gcode.respond_info("Auto-shutdown updated")
                else:
                    self.gcode.respond_info("Failed to update")

            self._async_run(
                lambda: self._http_post("/api/moonraker-shutdown?{}".format(query)), _done)
        else:
            gcmd.respond_info("Usage: FLOOK_AUTO_SHUTDOWN ENABLE=1 MINUTES=30")
    
    def cmd_FLOOK_AUTO_SHUTDOWN_STATUS(self, gcmd):
        """FLOOK_AUTO_SHUTDOWN_STATUS — auto-shutdown status."""
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(data):
            if data:
                enabled = data.get('aSd', False)
                minutes = data.get('aSm', 30)
                self.gcode.respond_info("Auto-shutdown: {} ({} min)".format(
                    'ON' if enabled else 'OFF', minutes))
            else:
                self.gcode.respond_info("Failed to get status")

        self._async_run(lambda: self._http_get_json("/api/config"), _done)
    
    def cmd_FLOOK_RESET_ID(self, gcmd):
        """
        FLOOK_RESET_ID — reset the saved device ID and start re-discovery.
        Useful when replacing FLOOK32 or changing the device.
        """
        if self.manual_mode:
            gcmd.respond_info("Manual mode, ID reset not required")
            return
        
        old_id = self.saved_device_id if self.saved_device_id else "None"
        
        self.saved_device_id = None
        self.flook_ip = None
        self.discovery_complete = False
        self._connected_before = False
        self._device_found_after_reset = False
        self._wrong_id_warning_shown = False
        self._no_device_warning_shown = False
        self._no_id_warning_shown = False
        self._last_critical_ts = 0
        
        self._delete_device_id()
        
        gcmd.respond_info("ID reset (was: {})".format(old_id))
        gcmd.respond_info("UDP loop will find the device in 1-2 iterations...")
    
    def cmd_FLOOK_CALIBRATE(self, gcmd):
        """FLOOK_CALIBRATE TEMP=<reference> — MAX6675 calibration."""
        temp = gcmd.get_float('TEMP', 100.0, minval=0, maxval=400)
        if not self.flook_ip:
            gcmd.respond_info("No connected device")
            return

        def _done(result):
            if result and ("OK" in result or "success" in result):
                self.gcode.respond_info("Calibration completed with reference {}°C".format(temp))
            else:
                self.gcode.respond_info("Failed to perform calibration")

        self._async_run(
            lambda: self._http_post("/api/calibrate-max6675?temp={}".format(temp)), _done)
    
    # =====================================================================
    # KLIPPER INTERFACE
    # =====================================================================
    
    def setup_minmax(self, min_temp, max_temp):
        """Set temperature range (called by Klipper)."""
        pass
    
    def get_report_time_delta(self):
        """Returns the polling interval in seconds."""
        return self.report_interval
    
    def setup_callback(self, cb):
        """Sets the callback for passing temperature to Klipper."""
        self._callback = cb
    
    def get_temp(self, eventtime):
        """
        Returns the current air temperature.
        Called by Klipper to update sensor readings.
        """
        with self.temp_lock:
            temp = self.air_temp
            if temp < MIN_TEMP or temp > MAX_TEMP:
                temp = 25.0
            return temp, 0.0
    
    def stats(self, eventtime):
        """Returns statistics for Klipper reports."""
        with self.temp_lock:
            temp = self.air_temp
            status = '{}: air={:.1f} target={:.1f}'.format(
                self.name, temp, self.target_temp)
            if self.flook_ip:
                status += ' ip={}'.format(self.flook_ip)
            return False, status
    
    def close(self):
        """
        Graceful shutdown: stop all threads,
        close WebSocket and UDP socket.
        """
        self.stop_thread = True
        self.udp_running = False
        self._stop_websocket()
        if self.sensor_thread.is_alive():
            self.sensor_thread.join(timeout=2.0)

# ============================================================================
# ENTRY POINT FOR KLIPPER
# ============================================================================

def load_config(config):
    """
    Registers the FLOOK32 sensor in Klipper.
    Called automatically when the plugin loads.
    """
    pheaters = config.get_printer().load_object(config, "heaters")
    pheaters.add_sensor_factory("flook32", FLOOK32Sensor)
