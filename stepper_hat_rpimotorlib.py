"""
RpiMotorLib-based backend for 2-axis pan/tilt control (alternate to stepper_hat_pigpio)
-----------------------------------------------------------------------------
Exports a `controller` instance with the same API used by main.py:
    controller.pan(deg)
    controller.tilt(deg)
    controller.get_pan_tilt() -> (pan_deg, tilt_deg)

This implementation uses RpiMotorLib's A4988/DRV8825 driver to step motors via
STEP/DIR and MODE pins. It keeps a lightweight background thread per axis that
moves toward the last commanded angle; repeated pan()/tilt() calls simply update
an internal target.

Select this backend by setting env var STEPPER_BACKEND=rpimotorlib before
starting the app. main.py will import this module when that var is set.
"""
from __future__ import annotations
import atexit
import threading
import time
from typing import Tuple

try:
    from RpiMotorLib import RpiMotorLib  # RpiMotorLib provides A4988Nema class
    import RPi.GPIO as GPIO
    _HAS_RPIMOTOR = True
except Exception:
    # Allow running on non-Pi/dev machines without the library installed
    _HAS_RPIMOTOR = False
    RpiMotorLib = None  # type: ignore
    GPIO = None  # type: ignore

# =========================
# ===== USER SETTINGS =====
# =========================
ACTIVE_HIGH_ENABLE = True
HOLD_ENABLE_WHEN_IDLE = True
IDLE_DISABLE_AFTER_S = 1.5

# HAT pinout (BCM) – same as other backends
M1_DIR, M1_STEP, M1_EN = 13, 19, 12  # X / pan (wired on board)
M1_MODE = (16, 17, 20)

M2_DIR, M2_STEP, M2_EN = 24, 18, 4   # Y / tilt (wired on board)
M2_MODE = (21, 22, 27)

# Microstepping mode supported by RpiMotorLib steptype strings
# Valid: 'Full','Half','1/4','1/8','1/16','1/32'
MICROSTEP = '1/16'

# ===== conversion pan/tilt <-> steps =====
# Keep consistent feel with the pigpio backend defaults
STEPS_PER_DEG_PAN = 4
STEPS_PER_DEG_TILT = 10

# ===== angle limits =====
PAN_MIN_DEG = -90
PAN_MAX_DEG = 90
TILT_MIN_DEG = PAN_MIN_DEG
TILT_MAX_DEG = PAN_MAX_DEG

# Motion tuning – RpiMotorLib uses stepdelay (seconds between steps)
MAX_STEP_HZ = 800     # maximum step rate (Hz)
MIN_STEP_HZ = 100     # start/low speed (Hz)
ACCEL_SPS2 = 1500     # crude accel used to ramp step rate in the thread
IDLE_SLEEP_S = 0.01


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class Axis(threading.Thread):
    def __init__(self, name: str, dir_pin: int, step_pin: int, en_pin: int,
                 mode_pins: Tuple[int, int, int], steps_per_deg: int):
        super().__init__(name=name, daemon=True)
        self.dir_pin, self.step_pin, self.en_pin = dir_pin, step_pin, en_pin
        self.mode_pins = mode_pins
        self.steps_per_deg = steps_per_deg
        self._target_steps = 0
        self._pos_steps = 0
        self._last_motion_t = 0.0
        self._stop_evt = threading.Event()
        self._lock = threading.RLock()

        if _HAS_RPIMOTOR:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for p in (dir_pin, step_pin, en_pin, *mode_pins):
                GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
            # MODE pins: RpiMotorLib will toggle them per step type, but safe to preset
            # We'll let motor_go steptype handle microstep selection; mode pins may be -1 to ignore.
            # Keep them as usable pins so the library can set them if required.
            # Enable output default disabled
            self._set_enable(False)
            # Instantiate motor driver: use A4988Nema class for DRV8825-style drivers
            # Pass the MODE pins tuple so steptype strings are supported.
            self._motor = RpiMotorLib.A4988Nema(dir_pin, step_pin, mode_pins, "DRV8825")
        else:
            self._motor = None

        self.start()

    def _set_enable(self, enable: bool) -> None:
        if not _HAS_RPIMOTOR:
            return
        level = GPIO.HIGH if (enable == ACTIVE_HIGH_ENABLE) else GPIO.LOW
        GPIO.output(self.en_pin, level)

    def move_to(self, absolute_steps: int) -> None:
        with self._lock:
            self._target_steps = int(absolute_steps)

    def get_position(self) -> int:
        with self._lock:
            return int(self._pos_steps)

    def stop(self) -> None:
        self._stop_evt.set()
        if _HAS_RPIMOTOR:
            self._set_enable(False)

    def _step_chunk(self, steps: int, clockwise: bool, step_hz: float) -> None:
        if steps <= 0:
            return
        if _HAS_RPIMOTOR and self._motor is not None:
            step_hz = max(1.0, min(MAX_STEP_HZ, step_hz))
            delay = 1.0 / step_hz
            # Use the configured microstep mode as steptype string
            steptype = MICROSTEP.capitalize() if MICROSTEP.lower() == 'full' else MICROSTEP
            try:
                # motor_go is blocking; run small chunks to remain responsive
                self._motor.motor_go(clockwise, steptype, steps, delay, False, 0.0)
            except Exception:
                # Fail quietly on dev machines without real hardware
                time.sleep(delay * steps)
        else:
            # Dev fallback: just sleep to simulate motion duration
            time.sleep(steps / max(1.0, step_hz))

    def run(self) -> None:
        cur_hz = MIN_STEP_HZ
        while not self._stop_evt.is_set():
            with self._lock:
                delta = self._target_steps - self._pos_steps
            if delta != 0:
                # Enable coils while moving
                self._set_enable(True)
                direction = 1 if delta > 0 else -1
                # Simple speed planning: farther distance -> higher speed
                target_hz = MIN_STEP_HZ + min(abs(delta), MAX_STEP_HZ - MIN_STEP_HZ)
                # accelerate/decelerate towards target_hz
                if cur_hz < target_hz:
                    cur_hz = min(target_hz, cur_hz + ACCEL_SPS2 * 0.002)
                elif cur_hz > target_hz:
                    cur_hz = max(MIN_STEP_HZ, cur_hz - ACCEL_SPS2 * 0.002)
                cur_hz = clamp(cur_hz, MIN_STEP_HZ, MAX_STEP_HZ)

                # Step in small chunks to stay responsive to target updates
                chunk = min(200, abs(delta))
                self._step_chunk(chunk, clockwise=(direction > 0), step_hz=cur_hz)
                with self._lock:
                    self._pos_steps += direction * chunk
                self._last_motion_t = time.time()
            else:
                # Idle: optionally disable
                if not HOLD_ENABLE_WHEN_IDLE:
                    if (time.time() - self._last_motion_t) > IDLE_DISABLE_AFTER_S:
                        self._set_enable(False)
                time.sleep(IDLE_SLEEP_S)


class Controller:
    def __init__(self) -> None:
        # Always create Axis threads; they handle missing hardware gracefully
        self._x = Axis("X", M1_DIR, M1_STEP, M1_EN, M1_MODE, STEPS_PER_DEG_TILT)  # note swapped mapping
        self._y = Axis("Y", M2_DIR, M2_STEP, M2_EN, M2_MODE, STEPS_PER_DEG_PAN)
        atexit.register(self.shutdown)

    # Match pigpio backend mapping and limits
    def pan(self, degrees: float) -> None:
        deg = clamp(degrees, PAN_MIN_DEG, PAN_MAX_DEG)
        steps = int(round(deg * STEPS_PER_DEG_PAN))
        # Send pan to Y axis to preserve current wiring mapping
        self._y.move_to(steps)

    def tilt(self, degrees: float) -> None:
        deg = clamp(degrees, TILT_MIN_DEG, TILT_MAX_DEG)
        steps = int(round(deg * STEPS_PER_DEG_TILT))
        # Send tilt to X axis to preserve current wiring mapping
        self._x.move_to(steps)

    def get_pan_tilt(self) -> Tuple[float, float]:
        x_deg = self._y.get_position() / STEPS_PER_DEG_PAN
        y_deg = self._x.get_position() / STEPS_PER_DEG_TILT
        return x_deg, y_deg

    def stop(self) -> None:
        self._x.stop(); self._y.stop()

    def shutdown(self) -> None:
        try:
            self.pan(0); self.tilt(0)
            time.sleep(1.0)
            self.stop()
        finally:
            if _HAS_RPIMOTOR:
                try:
                    GPIO.cleanup()
                except Exception:
                    pass


# Public instance for easy import in main.py
controller = Controller()
