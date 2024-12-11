#! /usr/bin/env python

import argparse
from pathlib import Path
import time
import numpy as np
import yaml
import threading
from labjack import ljm


class LabJackController:
    def __init__(self, config_path=None):
        if config_path is not None:
            self.config = self._load_config(config_path)
            self.freq = self.config["report"]["freq"]
            self.addresses = self.config["report"]["addresses"]
        self.handle = self._initialize_labjack()
        self.is_collecting = False
        self.lock = threading.Lock()

    def _load_config(self, file_path):
        if file_path:
            with open(file_path, 'r') as file:
                return yaml.safe_load(file)
            
    def connect(self):
        # entry point for instrument.py
        self._initialize_labjack()

    def _initialize_labjack(self):
        handle = ljm.openS("T4", "ANY", "ANY")  # Replace "T4" with the specific model, if different.
        self._set_states(handle)
        print(f"LabJack initialized with handle: {handle}")
        return handle
    
    def _set_states(self, handle):
        """ Initialization of the labjack state. """
        # Disable any extended features on FIO7 and FIO6
        ljm.eWriteName(handle, "DIO7_EF_ENABLE", 0)  # Disable extended features for FIO7
        ljm.eWriteName(handle, "DIO6_EF_ENABLE", 0)  # Disable extended features for FIO6

        # Set FIO7 and FIO6 as digital outputs and initial state to LOW
        ljm.eWriteName(handle, "FIO7", 0)
        ljm.eWriteName(handle, "FIO6", 0)

    def read_analog(self):
        analog_readings = {}
        for channel, cal in self.addresses.get("analog", {}).items():
            cal = cal['cal']
            value = ljm.eReadName(self.handle, f"AIN{channel}")
            if cal:
                # Ensure cal is a list of numbers and apply as a polynomial
                if isinstance(cal, list) and all(isinstance(c, (int, float)) for c in cal):
                    value = np.polyval(cal[::-1], value)  # Reverse cal to use with np.polyval
                else:
                    print(f"Invalid calibration for channel {channel}: {cal}. Skipping calibration.")
            analog_readings[f"AIN{channel}"] = value
        return analog_readings

    def read_digital(self):
        digital_readings = {}
        for line in self.addresses.get("digital", {}):
            value = ljm.eReadName(self.handle, line)
            digital_readings[line] = value
        return digital_readings
    
    def write_digital(self, digital_writes):
        """
        Writes to the digital pins specified in the digital_writes dictionary.
        
        Args:
            digital_writes (dict): A dictionary where keys are pin names (e.g., "FIO0") 
                                and values are 0 (LOW) or 1 (HIGH).
        """
        for line, value in digital_writes.items():
            if value not in [0, 1]:
                raise ValueError(f"Invalid value for digital write on {line}: {value}. Must be 0 or 1.")
            
            # Write the specified value to the digital line
            ljm.eWriteName(self.handle, line, value)

    def _collect_data(self):
        while self.is_collecting:
            try:
                analog_readings = self.read_analog()
                digital_readings = self.read_digital()

                with self.lock:
                    print("Analog:", analog_readings)
                    print("Digital:", digital_readings)

                time.sleep(self.freq)
            except Exception as e:
                print(f"Error during data collection: {e}")

    def start_data_collection(self):
        """Start data collection in a separate thread."""
        if self.is_collecting:
            print("Data collection is already running.")
            return

        self.is_collecting = True
        threading.Thread(target=self._collect_data, daemon=True).start()

    def stop_data_collection(self):
        """Stop the data collection."""
        self.is_collecting = False

    def _cleanup(self):
        self.stop_data_collection()
        ljm.close(self.handle)
        print("LabJack connection closed.")

    def disconnect(self):
        # used by instrument.py
        self._cleanup()

    def toggle_digital(self, line):
        """Toggle a digital line high for one second, then low."""
        print(f"Toggling digital line {line} HIGH for 1 second...")
        ljm.eWriteName(self.handle, line, 1)  # Set the line HIGH
        time.sleep(2)
        ljm.eWriteName(self.handle, line, 0)  # Set the line LOW
        print(f"Digital line {line} toggled LOW.")

    def run(self):
        """Wrapper to start and stop data collection."""
        try:
            print("Starting data collection...")
            self.start_data_collection()
            while True:
                time.sleep(1)  # Keep the main thread alive
        except KeyboardInterrupt:
            print("Data collection interrupted by user.")
        finally:
            self._cleanup()


def main():
    parser = argparse.ArgumentParser(description="LabJack Controller with Data Collection and Test Options")
    parser.add_argument("--config", type=str, help="Path to the configuration YAML file")
    parser.add_argument("--tog", type=str, help="Toggle a digital line (e.g., EIO0)")
    args = parser.parse_args()

    labjack_controller = LabJackController(args.config)

    if args.tog:
        labjack_controller.toggle_digital(args.tog)
    elif args.config:
        labjack_controller.run()


if __name__ == "__main__":
    main()