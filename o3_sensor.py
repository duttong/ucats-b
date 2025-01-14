#! /usr/bin/env python

import serial
import threading
import time
from datetime import datetime
import argparse
import random

class O3_2Btech:

    sim_mode_count = 0     # counter for number of simulated data packets

    def __init__(self, port, baudrate=4800, timeout=1, sim_mode=False, verbose=False, prefix=None):
        """
        Initialize the 2Btech Ozone analyzer class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 4800.
            timeout (int, optional): Timeout in seconds for serial communication. Default is 1 second.
            sim_mode (bool, optional): If True, simulate data instead of using the real device. Default is False.
            verbose (bool, optional): If True, print data to stdout (the screen).
            prefix (str, optional): Add a prefix to the data variable names.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.variables = ['o3', 't', 'p', 'flow_a', 'flow_b']   # variables parsed from sensor
        self.prefix = prefix
        self.data_buffer = []  # Buffer to store incoming data
        self.is_collecting = False
        self.lock = threading.Lock()  # For thread safety when accessing data
        self.verbose = verbose
        self.sim_mode = sim_mode

    def connect(self):
        """Establish the serial connection to the 2Btech ozone analyzer or enter test mode."""
        if self.sim_mode:
            print("2Btech Ozone sensor running in simulate mode.")
        else:
            try:
                self.ser = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    timeout=self.timeout
                )
                print(f"Connected to 2Btech device on port {self.port}")
            except serial.SerialException as e:
                print(f"Error connecting to device: {e}")
                self.ser = None

    def disconnect(self):
        """Close the serial connection."""
        if self.sim_mode:
            print("O3 Test mode ended.")
        elif self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected from 2Btech device.")
        else:
            print("No active connection to disconnect.")

    def start_data_collection(self):
        """Start a background thread to collect data or simulate test data."""
        if not self.sim_mode and (not self.ser or not self.ser.is_open):
            print("Device not connected. Call connect() first.")
            return

        self.is_collecting = True
        if self.sim_mode:
            threading.Thread(target=self._simulate_test_data, daemon=True).start()
        else:
            # Flush the serial input buffer to discard any existing data
            self.ser.reset_input_buffer()
            threading.Thread(target=self._collect_data, daemon=True).start()

    def _collect_data(self):
        """Collect data continuously from the device and store it in the buffer."""
        while self.is_collecting:
            try:
                # Read a line from the analyzer
                data = self.ser.readline().decode()
                if len(data) > 10:
                    parsed_data = self.parse_o3(data)
                    with self.lock:
                        self.data_buffer.append(parsed_data)  # Append new data to the buffer
                    if self.verbose:
                        data = data.replace('\n', '')
                        print(f"O3 data: {data}")
            except Exception as e:
                print(f"Error during data collection: {e}")
            time.sleep(1.0)  # Adjust the interval if needed

    def _simulate_test_data(self):
        """Simulate test data generation every 2 seconds."""
        while self.is_collecting:
            test_packet = self.generate_test_data()
            parsed_data = self.parse_o3(test_packet)
            with self.lock:
                self.data_buffer.append(parsed_data)
            if self.verbose:
                print(f"O3 Test data: {test_packet}")
            time.sleep(2.0)  # Simulate data every 2 seconds

    def stop_data_collection(self):
        """Stop collecting data."""
        self.is_collecting = False

    def get_all_data(self):
        """
        Retrieve all collected data from the buffer.

        Returns:
            list: A list of all collected data points.
        """
        with self.lock:
            data_copy = self.data_buffer.copy()  # Return a copy to avoid modification
            self.data_buffer.clear()  # Clear the buffer after returning the data
        return data_copy

    def parse_o3(self, packet):
        """
        Parse a data packet from the 2Btech ozone analyzer and replace date/time
        with values from the computer clock.

        Args:
            packet (str): Raw packet data from the analyzer.

        Returns:
            dict: Parsed data as a dictionary.
        """
        try:
            # Get current date and time from system clock
            current_datetime = datetime.now().replace(microsecond=0)
            
            # Clean and split the raw packet data
            data = packet.replace('\r\n', '').split(',')
            
            # Filter out indices 5, 6, and 7 (NOx variables) and prepend current datetime
            filtered_data = [value for i, value in enumerate(data) if i not in [5, 6, 7]]
            filtered_data = [current_datetime] + filtered_data
            
            # Add prefix to variables if provided, otherwise use unmodified names
            filtered_variables = ['datetime'] + [f'{self.prefix or ""}{var}' for var in self.variables]
            
            # Create a dictionary by zipping variable names and corresponding data
            return dict(zip(filtered_variables, filtered_data))

        except Exception as e:
            print(f"Error parsing O3 packet. Data: {packet}. Error: {e}")
            return {}
    
    def generate_test_data(self):
        """Generate a test data packet with random values."""

        O3_2Btech.sim_mode_count += 1
        noise = random.uniform(-10, 10)

        # Determine the pressure based on the read count
        if O3_2Btech.sim_mode_count <= 10:  # First 10 reads: 1000 hPa
            p = 1000 + noise
        elif O3_2Btech.sim_mode_count <= 40:  # Next 30 reads: Ramp from 1000 to 400 hPa
            p = 1000 - (600 / 30) * (O3_2Btech.sim_mode_count - 10) + noise
        elif O3_2Btech.sim_mode_count <= 60:  # Next 20 reads: Stay at 400 hPa
            p = 400 + noise
        elif O3_2Btech.sim_mode_count <= 80:  # Next 20 reads: Ramp from 400 to 1000 hPa
            p = 400 + (600 / 20) * (O3_2Btech.sim_mode_count - 60) + noise
        else:  # Remaining reads: Stay at 1000 +/- 10 hPa
            p = 1000 + noise
        p = round(p, 2)

        # Generate random values for the variables
        test_values = {
            "o3": round(random.uniform(0.01, 0.15), 3),   # Simulate O3 in ppm
            "t": round(random.uniform(15.0, 35.0), 2),    # Simulate temperature in °C
            "p": p,                                       # Pressure in hPa
            "flow_a": round(random.uniform(0.5, 2.0), 2), # Flow A in L/min
            "flow_b": round(random.uniform(0.5, 2.0), 2), # Flow B in L/min
        }

        # Use self.variables to construct the output packet
        packet = ",".join(str(test_values[var]) for var in self.variables) + "\r\n"
        return packet

if __name__ == "__main__":
    # Argument parser to handle command-line inputs
    parser = argparse.ArgumentParser(description="Test the 2Btech Ozone Analyzer driver.")
    
    parser.add_argument('-p', '--port', required=False, help="Serial port to connect to (e.g., COM3 or /dev/ttyUSB0).")
    parser.add_argument('-v', '--verbose', action='store_true', help="Print raw data to stdout")
    parser.add_argument('-s', '--simulate', type=int, help="Simulate mode: Number of data packets to read and then exit.")
    
    args = parser.parse_args()

    # Determine if we are running in test mode
    sim_mode = args.port is None

    # Create an instance of O3_2Btech
    analyzer = O3_2Btech(port=args.port if not sim_mode else 'test', sim_mode=sim_mode)
    
    # Connect to the instrument
    analyzer.connect()
    
    # Start data collection
    analyzer.start_data_collection()

    # If in test mode, wait until the specified number of packets is collected
    try:
        if args.simulate:
            analyzer.verbose = True
            time.sleep(args.simulate * 2)  # Assuming one packet every 2 seconds
        else:
            if args.verbose:
                analyzer.verbose = True
            print("Capturing Data: Press Ctrl-C to quit")
            while True:
                time.sleep(10)  # Wait indefinitely if test mode isn't specified
    except KeyboardInterrupt:
        print("Test interrupted.")
    
    # Retrieve and print all collected data
    data = analyzer.get_all_data()
    import pandas as pd
    df = pd.DataFrame(data)
    print("Collected data:")
    print(df)
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()