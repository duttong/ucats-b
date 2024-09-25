#!/usr/bin/env python

import serial
import threading
import time
from datetime import datetime
import random
import argparse

class Aeris:

    def __init__(self, port, baudrate=9600, timeout=1, sim_mode=False):
        """
        Initialize the Aeris TDL class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 9600.
            timeout (int, optional): Timeout in seconds for serial communication. Default is 1 second.
            sim_mode (bool, optional): If True, simulate data instead of using the real device. Default is False.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.data_buffer = []  # Buffer to store incoming data
        self.is_collecting = False
        self.lock = threading.Lock()  # For thread safety when accessing data
        self.verbose = False
        self.sim_mode = sim_mode

    def connect(self):
        """Establish the serial connection to the Aeris device or simulate connection."""
        if self.sim_mode:
            print("Running in simulate mode. Simulating data.")
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
                print(f"Connected to Aeris device on port {self.port}")
            except serial.SerialException as e:
                print(f"Error connecting to device: {e}")
                self.ser = None

    def disconnect(self):
        """Close the serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected from Aeris device.")
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
                # a full packet of data is typically around 340 bytes
                if len(data) > 300:
                    parsed_data = self.parse(data)
                    with self.lock:
                        self.data_buffer.append(parsed_data)  # Append new data to the buffer
                    if self.verbose:
                        data = data.replace('\n', '')
                        print(f"Raw data: {data}")
            except Exception as e:
                print(f"Error during data collection: {e}")
            time.sleep(0.5)  # Adjust the interval if needed

    def _simulate_test_data(self):
        """Simulate test data generation every 1 second."""
        while self.is_collecting:
            parsed_data = self.generate_test_data()
            with self.lock:
                self.data_buffer.append(parsed_data)
            if self.verbose:
                print(f"Test data: {parsed_data}")
            time.sleep(1)  # Simulate data every 1 second

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

    @staticmethod
    def parse(packet):
        """
        Parse a data packet from the Aeris analyzer and replace the datetime with the computer's
        datetime.

        Args:
            packet (str): Raw packet data from the analyzer.

        Returns:
            dict: Parsed data as a dictionary.
        """
        data = packet.replace('\r\n', '')
        data = data.split(',')

        # Replace the Aeris datatime with current system time
        current_datetime = datetime.now().replace(microsecond=0)    # round to the nearest second
        data[0] = current_datetime
            
        # Keep only the variables you need by filtering out indices ...
        #filtered_data = [value for i, value in enumerate(data) if i not in [43, 44, 45, 46]]
        filtered_variables = ['datetime', 'inlet_num', 'press_gas', 'temp_gas', 'therm1', 'therm2', 'therm3', 'therm4', 
            'laser_t', 'det_t', 'unk1', 'unk2', 'unk3', 'unk4', 'unk5', 'unk6', 'unk7', 'unk8', 'unk9', 
            'unk10', 'unk11', 'unk12', 'unk13', 'unk14', 'unk15', 'unk16', 'unk17', 'unk18', 'unk19', 
            'unk20', 'unk21', 'ramp', 'co2_1', 'co2_2', 'h2o', 'n2o_1', 'n2o_2', 'input_v', 
            'fet_t', 'tec_t1', 'tec_t2', 'tec_v', 'tec_amp', 'unk43', 'unk44', 'unk45', 'unk46']

        try:
            # Zip the filtered variables with data
            zipped_data = dict(zip(filtered_variables, data))
            
            # Filter out variables that start with 'unk'
            filtered_dict = {key: value for key, value in zipped_data.items() if not key.startswith('unk')}
            
            return filtered_dict

        except Exception as e:
            print(f'Error parsing Aeris packet: {data}, Error: {e}')

    @staticmethod
    def generate_test_data():
        """Generate simulated data excluding variables that start with 'unk'."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        inlet_num = 1
        simulated_data = {
            'datetime': timestamp,
            'inlet_num': inlet_num,
            'press_gas': round(random.uniform(900, 1100), 2),
            'temp_gas': round(random.uniform(15, 30), 2),
            'therm1': round(random.uniform(10, 20), 2),
            'therm2': round(random.uniform(10, 20), 2),
            'therm3': round(random.uniform(10, 20), 2),
            'therm4': round(random.uniform(10, 20), 2),
            'laser_t': round(random.uniform(20, 30), 2),
            'det_t': round(random.uniform(20, 30), 2),
            'ramp': round(random.uniform(0.0, 1.0), 2),
            'co2_1': round(random.uniform(350, 450), 2),
            'co2_2': round(random.uniform(350, 450), 2),
            'h2o': round(random.uniform(1000, 2000), 2),
            'n2o_1': round(random.uniform(300, 400), 2),
            'n2o_2': round(random.uniform(300, 400), 2),
            'input_v': round(random.uniform(4.5, 5.5), 2),
            'fet_t': round(random.uniform(30, 40), 2),
            'tec_t1': round(random.uniform(20, 30), 2),
            'tec_t2': round(random.uniform(20, 30), 2),
            'tec_v': round(random.uniform(12, 14), 2),
            'tec_amp': round(random.uniform(0.5, 1.5), 2)
        }
        return simulated_data


if __name__ == "__main__":
    # Argument parser to handle command-line inputs
    parser = argparse.ArgumentParser(description="Test the Aeris driver.")
    
    parser.add_argument('-p', '--port', required=False, help="Serial port to connect to (e.g., COM3 or /dev/ttyUSB0).")
    parser.add_argument('-t', '--test', type=int, help="Test mode: Number of data packets to read and then exit.")
    parser.add_argument('-s', '--simulate', action='store_true', help="Simulate mode: Number of data packets to read and then exit.")
    parser.add_argument('-v', '--verbose', action='store_true', help="Print data to screen")
    
    args = parser.parse_args()

    # Determine if we are running in test mode
    sim_mode = args.port is None

    # Create an instance of Aeris
    analyzer = Aeris(port=args.port if not sim_mode else 'test', sim_mode=sim_mode)

    # set verbose mode
    if args.verbose:
        analyzer.verbose = True
    
    # Connect to the instrument
    analyzer.connect()
    
    # Start data collection
    analyzer.start_data_collection()

    # If in test mode, wait until the specified number of packets is collected
    try:
        if args.test:
            time.sleep(args.test * 1)  # Assuming one packet every 1 second
        else:
            print("Capturing Data: Press Ctrl-C to quit")
            while True:
                time.sleep(10)  # Wait indefinitely if test mode isn't specified
    except KeyboardInterrupt:
        print("Test interrupted.")
    
    # Retrieve and print all collected data
    data = analyzer.get_all_data()  
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()