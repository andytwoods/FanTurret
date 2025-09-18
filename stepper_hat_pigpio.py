# stepper_hat_pigpio.py
# Smooth stepper control for a 2-axis pan/tilt fan using pigpio.
# Now includes min/max angle limits.

from __future__ import annotations
import math, time, threading, atexit
from typing import Tuple

try:
    import pigpio

    _HAS_PIGPIO = True
except Exception:
    pigpio = None  # type: ignore
    _HAS_PIGPIO = False

# =========================
# ===== USER SETTINGS =====
# =========================

ACTIVE_HIGH_ENABLE = True
HOLD_ENABLE_WHEN_IDLE = True
IDLE_DISABLE_AFTER_S = 1.5

SPEED_SCALE = .1
FREQ_MIN_HZ = 500
FREQ_MAX_HZ = 4000
RAMP_UPDATE_S = 0.002
# FINISH_PULSE_FREQ_HZ is no longer used, as the ramp's final frequency is used instead.
IDLE_SLEEP_S = 0.01

# HAT pinout (BCM)
M1_DIR, M1_STEP, M1_EN = 13, 19, 12  # X / pan
M1_MODE = (16, 17, 20)

M2_DIR, M2_STEP, M2_EN = 24, 18, 4  # Y / tilt
M2_MODE = (21, 22, 27)

MICROSTEP = '1/32'
_MICRO_TABLE = {
    'FULL': (0, 0, 0),
    'HALF': (1, 0, 0),
    '1/4': (0, 1, 0),
    '1/8': (1, 1, 0),
    '1/16': (0, 0, 1),
    '1/32': (1, 0, 1),
}

# ===== conversion pan/tilt <-> steps =====
STEPS_PER_DEG_PAN = 4
STEPS_PER_DEG_TILT = 10

# ===== angle limits =====
PAN_MIN_DEG = -90
PAN_MAX_DEG = 90
TILT_MIN_DEG = PAN_MIN_DEG
TILT_MAX_DEG = PAN_MAX_DEG


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def s_curve_01(u: float) -> float:
    u = clamp(u, 0.0, 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


def trapezoid_fraction(steps_done: float, total_steps: int) -> float:
    if total_steps <= 0: return 1.0
    # Symmetrical trapezoid: ramp up for first 40%, constant for 20%, ramp down for final 40%
    ramp_frac = 0.4
    u = clamp(steps_done / float(total_steps), 0.0, 1.0)
    if u < ramp_frac:  # Acceleration phase
        return u / ramp_frac
    if u > (1.0 - ramp_frac):  # Deceleration phase
        return (1.0 - u) / ramp_frac
    return 1.0  # Constant speed phase


class Axis:
    def __init__(self, pi: pigpio.pi, name: str,
                 dir_pin: int, step_pin: int, en_pin: int,
                 mode_pins: Tuple[int, int, int]):
        self.pi = pi;
        self.name = name
        self.dir_pin, self.step_pin, self.en_pin = dir_pin, step_pin, en_pin
        self.mode_pins = mode_pins
        self._lock = threading.RLock()
        self._target_steps = 0
        self._pos_steps = 0
        self._last_motion_t = 0.0
        self._speed_scale = SPEED_SCALE
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        for g in (self.dir_pin, self.step_pin, self.en_pin, *self.mode_pins):
            self.pi.set_mode(g, pigpio.OUTPUT)
        self._apply_microstep(MICROSTEP)
        self._set_enable(False)
        self._thread.start()

    def _set_enable(self, en: bool) -> None:
        self.pi.write(self.en_pin, 1 if (en == ACTIVE_HIGH_ENABLE) else 0)

    def _apply_microstep(self, mode: str) -> None:
        ms = _MICRO_TABLE.get(mode.upper())
        if not ms: raise ValueError(f"Unknown MICROSTEP '{mode}'")
        for pin, lvl in zip(self.mode_pins, ms):
            self.pi.write(pin, 1 if lvl else 0)

    def _set_dir(self, forward: bool) -> None:
        self.pi.write(self.dir_pin, 1 if forward else 0)

    def _hardware_pwm(self, freq_hz: int) -> None:
        duty = 500_000 if freq_hz > 0 else 0
        self.pi.hardware_PWM(self.step_pin, int(freq_hz), duty)

    def _emit_exact_pulses(self, count: int, freq_hz: int) -> None:
        if count <= 0: return
        # Ensure frequency is reasonable to prevent extremely long/short pulses
        freq_hz = clamp(freq_hz, 1, 50000)
        half_us = int(500_000 / freq_hz)
        pulses = []
        for _ in range(count):
            pulses.append(pigpio.pulse(1 << self.step_pin, 0, half_us))
            pulses.append(pigpio.pulse(0, 1 << self.step_pin, half_us))
        self.pi.wave_clear()
        self.pi.wave_add_generic(pulses)
        wid = self.pi.wave_create()
        try:
            self.pi.wave_send_once(wid)
            while self.pi.wave_tx_busy(): time.sleep(0.001)
        finally:
            if self.pi.connected:
                self.pi.wave_delete(wid)

    def move_to(self, absolute_steps: int) -> None:
        with self._lock: self._target_steps = int(absolute_steps)

    def get_position(self) -> int:
        with self._lock: return int(self._pos_steps)

    # =========================================================================
    # REVISED _move_block
    # This function has been rewritten to be smoother and more accurate.
    # =========================================================================
    def _move_block(self, total_steps: int, forward: bool) -> None:
        if total_steps <= 0: return
        self._set_dir(forward)
        self._set_enable(True)

        fmin = int(FREQ_MIN_HZ * self._speed_scale)
        fmax = int(FREQ_MAX_HZ * self._speed_scale)
        fmin = max(fmin, 1)
        fmax = max(fmax, fmin)

        self._hardware_pwm(fmin)
        steps_done_in_ramp = 0.0
        steps_done_in_finish = 0
        t_prev = time.perf_counter()
        final_freq = fmin

        try:
            # Main ramp loop. Position is NOT updated here to avoid jitter.
            while steps_done_in_ramp < total_steps and not self._stop_evt.is_set():
                u = trapezoid_fraction(steps_done_in_ramp, total_steps)
                k = s_curve_01(u)
                final_freq = int(round(fmin + (fmax - fmin) * k))
                # Ensure frequency is at least 1 to avoid PWM issues
                if final_freq < 1: final_freq = 1
                self._hardware_pwm(final_freq)

                time.sleep(RAMP_UPDATE_S)
                t_now = time.perf_counter()
                dt = t_now - t_prev
                t_prev = t_now
                steps_done_in_ramp += final_freq * dt

            # Stop the PWM before emitting the final precise pulses
            self._hardware_pwm(0)

            # Calculate remaining pulses to perfectly match the target
            remaining = int(round(total_steps - steps_done_in_ramp))

            if remaining > 0 and not self._stop_evt.is_set():
                # FIXED: Use the last frequency of the ramp for a smooth, jerk-free transition
                self._emit_exact_pulses(remaining, final_freq)
                steps_done_in_finish = remaining

        finally:
            self._hardware_pwm(0)
            # FIXED: Update the official position once, after the move is complete.
            # This is more accurate and correctly handles interruptions by _stop_evt.
            actual_steps_moved = int(round(steps_done_in_ramp)) + steps_done_in_finish

            # Clamp the result to avoid overshooting due to rounding.
            actual_steps_moved = min(actual_steps_moved, total_steps)

            with self._lock:
                self._pos_steps += actual_steps_moved if forward else -actual_steps_moved
                self._last_motion_t = time.time()

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            with self._lock:
                delta = self._target_steps - self._pos_steps
            if delta != 0:
                steps, fwd = abs(int(delta)), delta > 0
                self._move_block(steps, fwd)
            else:
                if not HOLD_ENABLE_WHEN_IDLE:
                    if (time.time() - self._last_motion_t) > IDLE_DISABLE_AFTER_S:
                        self._set_enable(False)
                time.sleep(IDLE_SLEEP_S)
        self._hardware_pwm(0)
        if not HOLD_ENABLE_WHEN_IDLE: self._set_enable(False)

    def stop(self):
        self._stop_evt.set()


class Controller:
    def __init__(self) -> None:
        if not _HAS_PIGPIO: raise RuntimeError("pigpio not available")
        self.pi = pigpio.pi()
        if not self.pi.connected: raise RuntimeError("pigpiod not connected")
        self._x = Axis(self.pi, "X", M1_DIR, M1_STEP, M1_EN, M1_MODE)  # Pan
        self._y = Axis(self.pi, "Y", M2_DIR, M2_STEP, M2_EN, M2_MODE)  # Tilt
        atexit.register(self.shutdown)

    # --- pan/tilt API with limits ---
    # FIXED: The pan() and tilt() methods were swapped. This is now correct.
    def pan(self, degrees: float) -> None:
        """Controls the Pan axis (physical pan mechanism)."""
        print(f"Panning to {degrees} degrees")
        deg = clamp(degrees, PAN_MIN_DEG, PAN_MAX_DEG)
        steps = int(round(deg * STEPS_PER_DEG_PAN))
        # Send pan steps to the axis currently wired as the "tilt" motor
        self._y.move_to(steps)

    def tilt(self, degrees: float) -> None:
        """Controls the Tilt axis (physical tilt mechanism)."""
        print(f"Tilting to {degrees} degrees")
        deg = clamp(degrees, TILT_MIN_DEG, TILT_MAX_DEG)
        steps = int(round(deg * STEPS_PER_DEG_TILT))
        # Send tilt steps to the axis currently wired as the "pan" motor
        self._x.move_to(steps)

    def get_pan_tilt(self) -> Tuple[float, float]:
        # Report physical pan from the axis driven by pan(), and tilt from the other
        x_deg = self._y.get_position() / STEPS_PER_DEG_PAN
        y_deg = self._x.get_position() / STEPS_PER_DEG_TILT
        return x_deg, y_deg


    def stop(self):
        self._x.stop(); self._y.stop()

    def shutdown(self):
        print("\nShutting down controller...")
        try:
            # Move to a neutral position before shutting down
            self.pan(0)
            self.tilt(0)
            time.sleep(2.0)
            self.stop()
            time.sleep(0.05)
        finally:
            if self.pi and self.pi.connected:
                print("Stopping pigpio connection.")
                # Ensure motors are disabled
                self._x._set_enable(False)
                self._y._set_enable(False)
                self.pi.stop()


if __name__ == "__main__":
    try:
        print("Starting pan/tilt demo...")
        controller = Controller()

        print("\nMoving to Pan: +45, Tilt: -20")
        controller.pan(45)
        #controller.tilt(-20)
        time.sleep(3.0)
        print(f"Current position: {controller.get_pan_tilt()}")


        print("\nMoving to home position (0, 0)")
        controller.pan(0)
        controller.tilt(0)
        time.sleep(3.0)
        final_pos = controller.get_pan_tilt()
        print(f"Final position: ({final_pos[0]:.2f}, {final_pos[1]:.2f})")

    except RuntimeError as e:
        print(f"Error: {e}")
        print("Please ensure the pigpio daemon is running (`sudo pigpiod`).")
    except KeyboardInterrupt:
        print("\nDemo interrupted by user.")
    finally:
        # The atexit handler will call shutdown automatically,
        # but we can call it here if the script ends normally.
        if 'controller' in locals():
            controller.shutdown()
        print("Demo finished.")
else:
    controller = Controller()