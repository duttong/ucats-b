#! /usr/bin/env python

import argparse
import time
from datetime import datetime
import numpy as np
import yaml
import threading
import random
from labjack import ljm


class LabJackController:
    def __init__(self, config_file=None, prefix=None, sim_mode=False, verbose=False):
        self.prefix = prefix
        self.sim_mode = sim_mode
        self.freq = 1       # read every second
        self.verbose = verbose
        self.variables = []
        if config_file is not None:
            self.config = self._load_config(config_file)
            self.variables = self.extract_labjack_variables()
        self.handle = self.initialize_labjack()
        self.is_collecting = False
        self.lock = threading.Lock()
        self.data_buffer = []  # Buffer to store incoming data

    @staticmethod
    def _load_config(file_path):
        # loads only the labjack section
        if file_path:
            with open(file_path, 'r') as file:
                return yaml.safe_load(file)['devices']['Labjack']

    def extract_labjack_variables(self):
        """
        Extracts all variable names from the Labjack section in the YAML configuration file.
        
        Args:
            file_path (str): Path to the YAML configuration file.
        
        Returns:
            list: A list of all variable names in the Labjack section.
        """
        variables = []
        
        # Extract variables from digouts
        variables.extend(self.config.get('digouts', {}).values())
        
        # Extract variables from digins
        try:
            variables.extend(self.config.get('digins', {}).values())
        except AttributeError:
            pass
        
        # Extract variables from analog section
        for analog in self.config.get('analog', {}).values():
            var_name = analog.get('var')
            if var_name:
                variables.append(var_name)
        
        return variables

    def get_labjack_address(self, variable_name):
        # Search in analog inputs
        for key, value in self.config.get("analog", {}).items():
            if isinstance(value, dict) and value.get("var") == variable_name:
                return key  # Return the analog input address (e.g., "AIN1")

        # Search in digital inputs
        for key, value in self.config.get("digins", {}).items():
            if value == variable_name:
                return key  # Return the digital input address (e.g., "CIO0")

        # Search in digital outputs
        for key, value in self.config.get("digouts", {}).items():
            if value == variable_name:
                return key  # Return the digital output address (e.g., "FIO6")

        return None  # Variable not found
   
    def connect(self):
        # entry point for instrument.py
        self.initialize_labjack()

    def initialize_labjack(self):
        if self.sim_mode:
            print("Simulating Labjack communications.")
        else:
            self.handle = ljm.openS("T4", "ANY", "ANY")  # Replace "T4" with the specific model, if different.
            self.initialize_digital_lines()
            print(f"LabJack initialized with handle: {self.handle}")
            return self.handle

    def initialize_digital_lines(self):
        """ Initialize all digital lines on the LabJack T4 to LOW (0) state. """
        
        # LabJack T4 digital lines: FIO0-7, EIO0-7, CIO0-2 (DIO0-DIO18)
        digital_lines = [f"DIO{i}" for i in range(19)]  # DIO0 to DIO18
        
        # Disable extended features only on supported lines (FIO0-7 and EIO0-7)
        for i in range(11):  # Skip DIO16-DIO18 (CIO0-2) to avoid errors
            ljm.eWriteName(self.handle, f"DIO{i}_EF_ENABLE", 0)

        # Set all lines as digital outputs and initialize them to LOW (0)
        for dio in digital_lines:
            ljm.eWriteName(self.handle, dio, 0)

        self.set_digital_in()

    def set_digital_in(self):
        # LabJack T4 digital lines: FIO0-7 (DIO0-7), EIO0-7 (DIO8-15), CIO0-2 (DIO16-DIO18)
        # TODO: use explicit address in the config file.

        # CIO lines are dedicated input and don't need to be coded.
        #ljm.eWriteName(self.handle, "DIO1_DIRECTION", 0)  # 0 = Input, 1 = Output
        return

    def read_analog(self):
        analog_readings = {}
        for channel, meta in (self.config.get("analog") or {}).items():
            var, cal = meta['var'], meta['cal']
            if self.prefix:
                var = f'{self.prefix}{var}'
            value = ljm.eReadName(self.handle, f"{channel}")
            if cal:
                # Ensure cal is a list of numbers and apply as a polynomial
                if isinstance(cal, list) and all(isinstance(c, (int, float)) for c in cal):
                    value = np.polyval(cal[::-1], value)  # Reverse cal to use with np.polyval
                else:
                    print(f"Invalid calibration for channel {channel}: {cal}. Skipping calibration.")
            analog_readings[var] = round(value, 3)
        return analog_readings

    def read_digital(self, address=None):
        """ Reads digital channels defined in config.yaml or
            reads one address defined in the input """
        if address:
            value = ljm.eReadName(self.handle, address)
            return value

        digital_readings = {}
        for address, var in (self.config.get("digins") or {}).items():
            if self.prefix:
                var = f'{self.prefix}{var}'
            value = ljm.eReadName(self.handle, address)
            digital_readings[var] = value
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
            
            if not self.sim_mode:
                with self.lock:
                    # Write the specified value to the digital line
                    #print(f'{line} = {value}')
                    ljm.eWriteName(self.handle, line, value)

    def _collect_data(self):
        while self.is_collecting:
            try:
                with self.lock:
                    current_datetime = {'datetime': datetime.now().replace(microsecond=0)}
                    analog_readings = self.read_analog()
                    digital_readings = self.read_digital()
                    # add DAC
                    data = current_datetime | analog_readings | digital_readings
                    self.data_buffer.append(data)
                    if self.verbose:
                        print(data)

                time.sleep(self.freq)
            except Exception as e:
                print(f"Error during data collection in lj.py: {e}")

    def _simulate_test_data(self):
         while self.is_collecting:
            current_datetime = {'datetime': datetime.now().replace(microsecond=0)}
            pumpspeed = round(random.uniform(500, 520), 1)
            #p = round(random.uniform(950, 1050), 1)
            t = round(random.uniform(20, 30), 1)
            analog = {f'{self.prefix}pump_speed': pumpspeed, f'{self.prefix}temp1': t}
            data = current_datetime | analog
            self.data_buffer.append(data)
            if self.verbose:
                print(data)
            time.sleep(1.0)

    def start_data_collection(self):
        """Start data collection in a separate thread."""
        if self.is_collecting:
            print("Data collection is already running.")
            return

        self.is_collecting = True
        if self.sim_mode:
            threading.Thread(target=self._simulate_test_data, daemon=True).start()
        else:
            threading.Thread(target=self._collect_data, daemon=True).start()

    def stop_data_collection(self):
        """Stop the data collection."""
        self.is_collecting = False

    def get_all_data(self):
        """
        Retrieve all collected data from the buffer.

        Returns:
            list: A dictionary of all collected data points.
        """
        with self.lock:
            data_copy = self.data_buffer.copy()  # Return a copy to avoid modification
            self.data_buffer.clear()  # Clear the buffer after returning the data
        return data_copy

    def disconnect(self):
        self.stop_data_collection()
        if self.sim_mode:
            print("Labjack simulation stopped.")
        else:
            ljm.close(self.handle)
            print("LabJack connection closed.")

    def toggle_digital(self, line):
        """Toggle a digital line high for one second, then low."""
        print(f"Toggling digital line {line} HIGH for 1 second...")
        ljm.eWriteName(self.handle, line, 1)  # Set the line HIGH
        time.sleep(5)
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
            self.disconnect()


def main():
    parser = argparse.ArgumentParser(description="LabJack Controller with Data Collection and Test Options")
    parser.add_argument("--config", type=str, help="Path to the configuration YAML file")
    parser.add_argument('-v', '--verbose', action='store_true', help="Print raw data to stdout")
    parser.add_argument("--digin", type=str, help="Read a digital line (e.g., CIO0)")
    parser.add_argument("--tog", type=str, help="Toggle a digital line (e.g., EIO0)")
    parser.add_argument("--high", type=str, help="Sets a digital line high/on.")
    parser.add_argument("--low", type=str, help="Sets a digital line low/off.")
    args = parser.parse_args()

    jack = LabJackController(args.config, verbose=args.verbose)

    if args.tog:
        jack.toggle_digital(args.tog)
    elif args.digin:
        value = jack.read_digital(args.digin)
        print(f"Dig {args.digin} is {value}")
    elif args.high:
        jack.write_digital({f"{args.high}": 1})
        print(f"Dig {args.high} set HIGH")
    elif args.low:
        jack.write_digital({f"{args.low}": 0})
        print(f"Dig {args.low} set LOW")
    elif args.config:
        jack.run()


if __name__ == "__main__":
    main()