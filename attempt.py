#!/usr/bin/env python3
import time

# use the smooth PWM adapter you added
# (exports BOTH `controller` and `pantilthat`; they’re the same instance)
from stepper_hat_pigpio import controller  # or: from stepper_hat_pigpio import pantilthat as controller

# --- one-time sanity: pigpio daemon must be running ---
# sudo apt update && sudo apt install -y python3-pigpio pigpio
# sudo systemctl enable --now pigpiod

def sweep_pan():
    print("[pan] centre → +45 → -45 → 0")
    controller.pan(0);   time.sleep(0.3)
    controller.pan(45);  time.sleep(0.8)
    controller.pan(-45); time.sleep(0.8)
    controller.pan(0);   time.sleep(0.6)

def sweep_tilt():
    print("[tilt] centre → +30 → -30 → 0")
    controller.tilt(0);   time.sleep(0.3)
    controller.tilt(30);  time.sleep(0.6)
    controller.tilt(-30); time.sleep(0.6)
    controller.tilt(0);   time.sleep(0.5)

def both_together():
    print("[both] opposite directions")
    controller.pan(35)
    controller.tilt(-35)
    time.sleep(0.8)
    controller.pan(0)
    controller.tilt(0)
    time.sleep(0.6)

if __name__ == "__main__":
    # do a few quiet sweeps
    sweep_pan()
    sweep_tilt()
    both_together()

    print("done.")
