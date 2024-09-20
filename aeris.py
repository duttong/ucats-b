#!/usr/bin/env python

import serial
import threading
import time
import argparse

class Aeris:

    def __init__(self, port, baudrate=9600, timeout=1):
        """
        Initialize the Aeris TDL class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 9600.
            timeout (int, optional): Timeout in seconds for serial communication. Default is 1 second.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.data_buffer = []  # Buffer to store incoming data
        self.is_collecting = False
        self.lock = threading.Lock()  # For thread safety when accessing data
        self.verbose = False

    def connect(self):
        """Establish the serial connection to the 2Btech ozone analyzer."""
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
        """Start a background thread to collect data."""
        if not self.ser or not self.ser.is_open:
            print("Device not connected. Call connect() first.")
            return

        # Flush the serial input buffer to discard any existing data
        time.sleep(1)
        self.ser.reset_input_buffer()

        self.is_collecting = True
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
        Parse a data packet from the 2Btech ozone analyzer.

        Args:
            packet (str): Raw packet data from the analyzer.

        Returns:
            dict: Parsed data as a dictionary.
        """
        data = packet.replace('\r\n', '')
        data = data.split(',')
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


if __name__ == "__main__":
    # Argument parser to handle command-line inputs
    parser = argparse.ArgumentParser(description="Test the 2Btech Ozone Analyzer driver.")
    
    parser.add_argument('-p', '--port', required=True, help="Serial port to connect to (e.g., COM3 or /dev/ttyUSB0).")
    parser.add_argument('-t', '--test', type=int, help="Test mode: Number of data packets to read and then exit.")
    
    args = parser.parse_args()

    # Create an instance of Aeris
    analyzer = Aeris(port=args.port)
    
    # Connect to the instrument
    analyzer.connect()
    
    # Start data collection
    analyzer.start_data_collection()

    # If in test mode, wait until the specified number of packets is collected
    try:
        if args.test:
            analyzer.verbose = True
            time.sleep(args.test * 1)  # Assuming one packet every 1 second
        else:
            print("Capturing Data: Press Ctrl-C to quit")
            while True:
                time.sleep(10)  # Wait indefinitely if test mode isn't specified
    except KeyboardInterrupt:
        print("Test interrupted.")
    
    # Retrieve and print all collected data
    data = analyzer.get_all_data()
    import pandas as pd
    df = pd.DataFrame(data)
    print(df)
    df.to_csv('raw.csv', index=None)
    
    #import matplotlib.pyplot as plt
    #print(df[['datetime', 'inlet_num', 'press_gas', 'temp_gas', 'therm1', 'therm2', 'therm3', 'therm4', 'laser_t', 'det_t', 'ramp', 'co2_1', 'co2_2', 'h2o', 'n2o_1', 'n2o_2']])
    #df = df.set_index('datetime')
    #plt.plot(df.co2_1)
    #plt.plot(df.co2_2)
    #plt.show()
    
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()