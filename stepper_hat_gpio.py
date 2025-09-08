
"""
Stepper HAT (GPIO) adapter – controller_gpio-compatible API for DRV8825-style HAT
-----------------------------------------------------------------------------
Drop-in replacement for `controller_gpio` that drives TWO NEMA‑17 steppers via the
Waveshare Stepper Motor HAT using STEP/DIR/EN + MODE pins (no I2C).

Usage in your app:
    from stepper_hat_gpio import controller_gpio
    controller_gpio.pan(deg)   # -90..90
    controller_gpio.tilt(deg)  # -90..90

Notes:
- This module starts a lightweight background thread per axis which incrementally
  steps toward the last commanded angle. Calling pan()/tilt() repeatedly simply
  updates the target; the thread handles the motion.
- Designed for the user's board where ENABLE is ACTIVE-HIGH (EN=1 runs).
- Requires: sudo apt install -y python3-rpi.gpio
"""

from __future__ import annotations
import threading, time, atexit
from typing import Tuple

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except Exception:
    # Fallback dummy mode for non-Pi dev machines
    _HAS_GPIO = False

# ----------------- CONFIG -----------------
ACTIVE_HIGH_ENABLE = True      # User's HAT: EN=1 to enable
HOLD_ENABLE_WHEN_IDLE = True   # Keep torque on when idle
IDLE_DISABLE_AFTER_S = 2.0     # If HOLD is False, disable after this idle time

# Pin map (BCM numbering) – matches Waveshare HAT docs
M1_DIR, M1_STEP, M1_EN  = 13, 19, 12
M1_MODE                 = (16, 17, 20)   # MODE0, MODE1, MODE2

M2_DIR, M2_STEP, M2_EN  = 24, 18, 4
M2_MODE                 = (21, 22, 27)   # MODE0, MODE1, MODE2

# Microstepping – set to match your DIP (or leave FULL and set all DIP OFF)
# Valid: 'FULL','HALF','1/4','1/8','1/16','1/32'
MICROSTEP = 'FULL'
_MICRO_TABLE = {
    'FULL': (0,0,0),
    'HALF': (1,0,0),
    '1/4':  (0,1,0),
    '1/8':  (1,1,0),
    '1/16': (0,0,1),
    '1/32': (1,0,1),
}

# Motion tuning
STEPS_PER_REV = 200               # 1.8° motor
MAX_HZ        = 400               # max step frequency (steps/s)
START_HZ      = 80                # initial step rate from standstill
ACCEL_SPS2    = 800               # acceleration (steps/s^2)
JOG_SLEEP     = 0.001             # idle loop sleep

# Travel limits
MIN_DEG, MAX_DEG = -90.0, 90.0

# ------------------------------------------

def _safe_gpio_setup():
    if not _HAS_GPIO:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

def _pins_setup(dir_pin:int, step_pin:int, en_pin:int, mode_pins:Tuple[int,int,int]):
    if not _HAS_GPIO:
        return
    for p in (dir_pin, step_pin, en_pin, *mode_pins):
        GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
    # Set microstep bits (safe even if DIP overrides)
    m = _MICRO_TABLE.get(MICROSTEP.upper(), (0,0,0))
    GPIO.output(mode_pins, m)
    # Disable at start
    _set_enable(en_pin, False)

def _cleanup_axis(en_pin:int):
    if not _HAS_GPIO:
        return
    _set_enable(en_pin, False)

def _set_enable(en_pin:int, run:bool):
    if not _HAS_GPIO:
        return
    level = GPIO.HIGH if (run == ACTIVE_HIGH_ENABLE) else GPIO.LOW
    GPIO.output(en_pin, level)

def _pulse_step(step_pin:int, half_period:float):
    if not _HAS_GPIO:
        time.sleep(half_period*2)
        return
    GPIO.output(step_pin, GPIO.HIGH); time.sleep(half_period)
    GPIO.output(step_pin, GPIO.LOW);  time.sleep(half_period)

class _AxisRunner(threading.Thread):
    def __init__(self, name:str, dir_pin:int, step_pin:int, en_pin:int, mode_pins:Tuple[int,int,int], deg_to_steps:float):
        super().__init__(name=name, daemon=True)
        self.dir_pin, self.step_pin, self.en_pin, self.mode_pins = dir_pin, step_pin, en_pin, mode_pins
        self.deg_to_steps = deg_to_steps
        self._target_steps = 0
        self._pos_steps = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_motion_t = time.time()
        _pins_setup(dir_pin, step_pin, en_pin, mode_pins)

    def set_target_deg(self, deg:float):
        d = max(MIN_DEG, min(MAX_DEG, float(deg)))
        with self._lock:
            self._target_steps = int(round(d * self.deg_to_steps))

    def run(self):
        cur_hz = 0.0
        while not self._stop.is_set():
            with self._lock:
                delta = self._target_steps - self._pos_steps
            if delta != 0:
                # Enable before motion
                _set_enable(self.en_pin, True)
                # Direction
                direction = 1 if delta > 0 else -1
                if _HAS_GPIO:
                    GPIO.output(self.dir_pin, GPIO.HIGH if direction > 0 else GPIO.LOW)
                # Simple accel ramp toward MAX_HZ
                target_hz = min(MAX_HZ, START_HZ + abs(delta))  # crude: more distance → higher allowed speed
                # accelerate
                if cur_hz < target_hz:
                    cur_hz = min(target_hz, cur_hz + ACCEL_SPS2 * 0.002)  # update approx every ~2ms
                elif cur_hz > target_hz:
                    cur_hz = max(START_HZ, cur_hz - ACCEL_SPS2 * 0.002)
                # Bound
                cur_hz = max(START_HZ, min(MAX_HZ, cur_hz))
                half = 1.0 / (cur_hz * 2.0)
                # Step once
                _pulse_step(self.step_pin, half)
                self._pos_steps += direction
                self._last_motion_t = time.time()
            else:
                # No motion
                if not HOLD_ENABLE_WHEN_IDLE:
                    if time.time() - self._last_motion_t > IDLE_DISABLE_AFTER_S:
                        _set_enable(self.en_pin, False)
                time.sleep(JOG_SLEEP)

    def stop(self):
        self._stop.set()
        _cleanup_axis(self.en_pin)

class _ControllerGPIO:
    def __init__(self):
        self._dummy = not _HAS_GPIO
        steps_per_deg = (STEPS_PER_REV * _micro_multiplier()) / 360.0
        _safe_gpio_setup()
        self._pan_axis  = _AxisRunner("pan-axis",  M1_DIR, M1_STEP, M1_EN, M1_MODE, steps_per_deg)
        self._tilt_axis = _AxisRunner("tilt-axis", M2_DIR, M2_STEP, M2_EN, M2_MODE, steps_per_deg)
        self._pan_axis.start()
        self._tilt_axis.start()
        atexit.register(self._cleanup)

    def _cleanup(self):
        try:
            self._pan_axis.stop()
            self._tilt_axis.stop()
            if _HAS_GPIO:
                GPIO.cleanup()
        except Exception:
            pass

    # API-compatible
    def pan(self, angle_deg: float):
        if self._dummy:
            print(f"[GPIO controller_gpio] pan -> {angle_deg}")
            return
        self._pan_axis.set_target_deg(angle_deg)

    def tilt(self, angle_deg: float):
        if self._dummy:
            print(f"[GPIO controller_gpio] tilt -> {angle_deg}")
            return
        self._tilt_axis.set_target_deg(angle_deg)

def _micro_multiplier():
    # Steps per rev multiplier based on microstepping
    m = MICROSTEP.upper()
    return {'FULL':1,'HALF':2,'1/4':4,'1/8':8,'1/16':16,'1/32':32}.get(m,1)

# Public instance
controller_gpio = _ControllerGPIO()
