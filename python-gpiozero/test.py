import gpiozero as GPIO
import time
from DRV8825 import DRV8825


try:
    Motor1 = DRV8825(dir_pin=13, step_pin=19, enable_pin=12, mode_pins=(16, 17, 20))
    Motor2 = DRV8825(dir_pin=24, step_pin=18, enable_pin=4, mode_pins=(21, 22, 27))

    # Test with very slow movement first
    Motor1.SetMicroStep('softward', 'fullstep')
    Motor1.TurnStep(Dir='forward', steps=50, stepdelay=0.0015)  # Very slow - 0.1 second delay
    time.sleep(2)
    Motor1.TurnStep(Dir='backward', steps=50, stepdelay=0.0015)

    # Fix the typo and increase step delay for Motor1
    Motor1.SetMicroStep('softward', 'fullstep')
    Motor1.TurnStep(Dir='forward', steps=200, stepdelay=0.01)  # Increased delay
    time.sleep(0.5)
    Motor1.TurnStep(Dir='backward', steps=400, stepdelay=0.01)  # Increased delay
    Motor1.Stop()

    # Fix the typo: 'hardward' -> 'softward' and increase step delay
    Motor2.SetMicroStep('softward', 'halfstep')
    Motor2.TurnStep(Dir='forward', steps=2048, stepdelay=0.005)  # Increased delay
    time.sleep(0.5)
    Motor2.TurnStep(Dir='backward', steps=2048, stepdelay=0.005)  # Increased delay
    Motor2.Stop()

    Motor1.Stop()
    Motor2.Stop()
    
except:
    # GPIO.cleanup()
    print("\nMotor stop")
    Motor1.Stop()
    Motor2.Stop()
    exit()