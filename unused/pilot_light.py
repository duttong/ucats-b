from pathlib import Path
import time

# Import the LabJackController class from the lj.py file
from lj import LabJackController

def pilot_light(controller: LabJackController, digital_line="FIO7"):
    """
    Toggles the specified digital line on and off every second.
    
    :param controller: LabJackController instance to control the LabJack device.
    :param digital_line: The digital line to pulse, default is 'FIO7'.
    """
    print(f"Starting PilotLight on {digital_line}. Press Ctrl+C to stop.")
    try:
        while True:
            controller._write_digital({digital_line: 1})  # Set the line high
            time.sleep(1)                             # Wait for 1 second
            controller._write_digital({digital_line: 0})  # Set the line low
            time.sleep(1)                             # Wait for 1 second
    except KeyboardInterrupt:
        print("\nPilotLight stopped.")

if __name__ == "__main__":
    # Initialize the LabJackController
    config_path = Path("config.yaml")  # Replace with your actual configuration file path if needed
    lj_controller = LabJackController()
    
    # Start the PilotLight function
    pilot_light(lj_controller)