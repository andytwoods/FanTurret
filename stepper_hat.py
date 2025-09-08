"""
Waveshare Stepper Motor HAT (B) adapter for FanTurret

This module provides a minimal adapter that mimics the Pimoroni controller_gpio API
(pan(angle_deg), tilt(angle_deg)) but drives the Waveshare Stepper Motor HAT (B).

Design goals:
- Keep the rest of the app unchanged by exposing an object named `controller_gpio`
  with methods pan(int degrees) and tilt(int degrees).
- Safely no-op on non-Raspberry Pi environments (e.g., Windows dev), while
  logging the intent. On a Pi with the HAT attached, it will attempt real control.

Notes on hardware:
- The Waveshare Stepper Motor HAT (B) uses PCA9685 (I2C, default address 0x40)
  to generate waveforms to drive stepper phases through driver transistors.
- Different motor wirings may use different channels; you can configure channels below.
- For 28BYJ-48 (5V) geared stepper typical full steps per output shaft rev ~2048
  (32 steps/rotor rev * 63.683:1 gear ≈ 2038–4096 depending on half/full stepping).
- Update STEPPER_CONFIG to match your motors and mechanical ratios.

IMPORTANT: For precise motion and acceleration control you may want to replace this
with Waveshare's official Python examples/library. This adapter aims for simplicity.
"""
from __future__ import annotations

import sys
import time
from typing import List

try:
    # Prefer smbus2 if available
    try:
        from smbus2 import SMBus
    except Exception:  # pragma: no cover
        from smbus import SMBus  # type: ignore
    HAS_I2C = True
except Exception:
    HAS_I2C = False
    SMBus = None  # type: ignore

# ------------------ Configuration ------------------

# Mechanical/electrical configuration per axis
STEPPER_CONFIG = {
    'i2c_addr': 0x40,       # PCA9685 default I2C address for Waveshare HAT
    'freq_hz': 1000,        # PCA9685 PWM frequency; we mainly use on/off

    # Channels for the 4 coils of each motor (adjust to your hat mapping)
    # These are example mappings; consult the Waveshare wiki for the exact
    # channel mapping of your HAT revision. You may need to change these.
    'pan_channels': [0, 1, 2, 3],
    'tilt_channels': [4, 5, 6, 7],

    # Motion/geometry parameters
    # steps_per_rev: effective full steps per output shaft revolution (after gearing)
    'pan_steps_per_rev': 2048,
    'tilt_steps_per_rev': 2048,
    'pan_gear_ratio': 1.0,   # additional external gear ratio if any
    'tilt_gear_ratio': 1.0,
    'microstep': 2,          # 1 for full-step, 2 for half-step, etc.

    # Limits (degrees)
    'min_deg': -90,
    'max_deg': 90,

    # Step delay (seconds) — tune for smoothness and torque
    'step_delay': 0.0015,
}

# Half-step sequence (8 steps) for 4-wire unipolar/bipolar via ULN2003-style drivers
# Each entry corresponds to coil energizing pattern for channels [A1, A2, B1, B2]
HALF_STEP_SEQ: List[List[int]] = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]

# Full-step sequence (4 steps)
FULL_STEP_SEQ: List[List[int]] = [
    [1, 0, 1, 0],
    [0, 1, 1, 0],
    [0, 1, 0, 1],
    [1, 0, 0, 1],
]


# ------------------ PCA9685 Minimal Driver ------------------
class PCA9685:
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus: SMBus, address: int = 0x40):
        self.bus = bus
        self.address = address
        self._init_chip()

    def _write8(self, reg: int, val: int) -> None:
        self.bus.write_byte_data(self.address, reg, val & 0xFF)

    def _read8(self, reg: int) -> int:
        return self.bus.read_byte_data(self.address, reg) & 0xFF

    def _init_chip(self) -> None:
        # Sleep
        self._write8(self.MODE1, 0x10)
        # Set prescale for frequency
        # prescale = round(25MHz / (4096 * freq)) - 1
        freq = max(40, min(1500, STEPPER_CONFIG['freq_hz']))
        prescale_val = int(round(25000000.0 / (4096.0 * freq)) - 1)
        self._write8(self.PRESCALE, prescale_val)
        # Wake up
        self._write8(self.MODE1, 0x00)
        time.sleep(0.005)
        # Auto-increment
        self._write8(self.MODE1, 0xA1)

    def set_pwm(self, channel: int, on: int, off: int) -> None:
        base = self.LED0_ON_L + 4 * channel
        self._write8(base + 0, on & 0xFF)
        self._write8(base + 1, (on >> 8) & 0x0F)
        self._write8(base + 2, off & 0xFF)
        self._write8(base + 3, (off >> 8) & 0x0F)

    def set_pin(self, channel: int, value: int) -> None:
        # value 0 -> OFF, 1 -> ON (full 100% duty)
        if value:
            self.set_pwm(channel, 0, 4095)
        else:
            self.set_pwm(channel, 0, 0)


# add near the top
import threading
from collections import deque

# ------------------ Stepper Axis ------------------
class StepperAxis:
    def __init__(self, pca: PCA9685 | None, channels: List[int], steps_per_rev: int, gear_ratio: float, microstep: int, step_delay: float):
        ...
        self.seq = HALF_STEP_SEQ if self.microstep >= 2 else FULL_STEP_SEQ

        # --- NEW: async control state ---
        self._cv = threading.Condition()
        self._mailbox = deque(maxlen=1)  # holds at most one target deg
        self._gen = 0                    # generation counter – cancels current move
        self._stop = False
        self._worker = threading.Thread(target=self._run, name=f"axis-worker-{id(self)}", daemon=True)
        self._worker.start()

    def shutdown(self):
        with self._cv:
            self._stop = True
            self._gen += 1
            self._cv.notify_all()
        # do not join daemon worker on exit

    def _energize(self, pattern: List[int]):
        ...

    def _deenergize_all(self):
        ...

    def steps_per_deg(self) -> float:
        return len(self.seq) * self.steps_per_rev / 360.0

    # --- NEW: non-blocking setter that cancels current move and replaces queue ---
    def set_target_deg(self, target_deg: float):
        target_deg = max(STEPPER_CONFIG['min_deg'], min(STEPPER_CONFIG['max_deg'], float(target_deg)))
        with self._cv:
            self._mailbox.clear()
            self._mailbox.append(target_deg)
            self._gen += 1  # invalidate any in-flight loop
            self._cv.notify_all()

    # --- NEW: worker loop; always heads toward the latest target, dropping stale ones ---
    def _run(self):
        seq_len = len(self.seq)
        while True:
            with self._cv:
                while not self._mailbox and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                target_deg = self._mailbox[-1]   # only care about newest
                my_gen = self._gen

            # step toward target, checking for cancellation each micro-step
            spd = self.steps_per_deg()
            target_step = int(round(target_deg * spd))
            delta = target_step - self.current_step
            step_dir = 1 if delta >= 0 else -1
            steps = abs(delta)

            if steps == 0:
                # already there – update degree and loop, in case a newer target arrived
                self.current_deg = target_deg
                continue

            idx = self.current_step % seq_len
            for _ in range(steps):
                # cancelled/newer command?
                with self._cv:
                    if my_gen != self._gen or self._stop:
                        break
                idx = (idx + step_dir) % seq_len
                self._energize(self.seq[idx])
                time.sleep(self.step_delay)
                self.current_step += step_dir

            # snap and record final position for this generation
            self.current_deg = self.current_step / spd
            # optional: de-energise to reduce heat
            # self._deenergize_all()


# ------------------ Public Adapter ------------------
class controller_gpioAdapter:
    ...
    def pan(self, angle_deg: int | float) -> None:
        try:
            angle = float(angle_deg)
        except Exception:
            return
        if self._dummy:
            print(f"[StepperHAT] pan -> {angle:.2f} deg (dummy)")
            self.pan_axis.current_deg = max(STEPPER_CONFIG['min_deg'], min(STEPPER_CONFIG['max_deg'], angle))
            return
        # NEW: non-blocking, cancels any in-flight motion
        self.pan_axis.set_target_deg(angle)

    def tilt(self, angle_deg: int | float) -> None:
        try:
            angle = float(angle_deg)
        except Exception:
            return
        if self._dummy:
            print(f"[StepperHAT] tilt -> {angle:.2f} deg (dummy)")
            self.tilt_axis.current_deg = max(STEPPER_CONFIG['min_deg'], min(STEPPER_CONFIG['max_deg'], angle))
            return
        # NEW: non-blocking, cancels any in-flight motion
        self.tilt_axis.set_target_deg(angle)


# Graceful shutdown helper (optional)
def _shutdown():
    try:
        controller_gpio.pan_axis.shutdown()
        controller_gpio.tilt_axis.shutdown()
    except Exception:
        pass


# Expose instance named `controller_gpio` to minimize changes in callers
controller_gpio = controller_gpioAdapter()
