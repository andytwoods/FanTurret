import RPi.GPIO as GPIO, time

# Motor 1 (matches the HAT)
DIR1, STEP1, EN1 = 13, 19, 12
MODE1 = (16, 17, 20)   # MODE0/1/2

# Motor 2
DIR2, STEP2, EN2 = 24, 18, 4
MODE2 = (21, 22, 27)   # MODE0/1/2

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in [DIR1, STEP1, EN1, *MODE1, DIR2, STEP2, EN2, *MODE2]:
    GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

# Full step (safe even if DIPs are already set)
GPIO.output(MODE1, (0, 0, 0))
GPIO.output(MODE2, (0, 0, 0))

def spin_one(step_pin, dir_pin, en_pin, steps=400, hz=100):
    GPIO.output(en_pin, GPIO.HIGH)   # ACTIVE-HIGH enable (your board)
    GPIO.output(dir_pin, GPIO.HIGH)
    half = 1.0/(hz*2.0)
    for _ in range(steps):
        GPIO.output(step_pin, 1); time.sleep(half)
        GPIO.output(step_pin, 0); time.sleep(half)
    GPIO.output(en_pin, GPIO.LOW)    # disable to keep cool
    time.sleep(0.3)

print("[1] Motor 1 → should move")
spin_one(STEP1, DIR1, EN1)

print("[2] Motor 2 → should move")
spin_one(STEP2, DIR2, EN2)

print("[3] Both together → should move in sync")
GPIO.output(EN1, GPIO.HIGH)
GPIO.output(EN2, GPIO.HIGH)
GPIO.output(DIR1, GPIO.HIGH)
GPIO.output(DIR2, GPIO.LOW)   # opposite direction so it’s obvious
half = 1.0/(100*2.0)
for _ in range(400):
    GPIO.output(STEP1, 1); GPIO.output(STEP2, 1); time.sleep(half)
    GPIO.output(STEP1, 0); GPIO.output(STEP2, 0); time.sleep(half)

# Tidy
GPIO.output(EN1, GPIO.LOW)
GPIO.output(EN2, GPIO.LOW)
GPIO.cleanup()
