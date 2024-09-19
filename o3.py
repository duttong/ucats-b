import serial
import threading
import time
import argparse

class O3_2Btech:

    def __init__(self, port, baudrate=4800, timeout=1):
        """
        Initialize the 2Btech Ozone analyzer class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 4800.
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
            print(f"Connected to 2Btech device on port {self.port}")
        except serial.SerialException as e:
            print(f"Error connecting to device: {e}")
            self.ser = None

    def disconnect(self):
        """Close the serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected from 2Btech device.")
        else:
            print("No active connection to disconnect.")

    def start_data_collection(self):
        """Start a background thread to collect data."""
        if not self.ser or not self.ser.is_open:
            print("Device not connected. Call connect() first.")
            return

        # Flush the serial input buffer to discard any existing data
        self.ser.reset_input_buffer()

        self.is_collecting = True
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
                        print(f"Raw data: {data}")
            except Exception as e:
                print(f"Error during data collection: {e}")
            time.sleep(1.0)  # Adjust the interval if needed

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
    def parse_o3(packet):
        """
        Parse a data packet from the 2Btech ozone analyzer.

        Args:
            packet (str): Raw packet data from the analyzer.

        Returns:
            dict: Parsed data as a dictionary.
        """
        data = packet.replace('\r\n', '')
        data = data.split(',')
        # Keep only the variables you need by filtering out indices 5, 6, and 7 (these are the NOx variables)
        filtered_data = [value for i, value in enumerate(data) if i not in [5, 6, 7]]
        filtered_variables = ['o3', 't', 'p', 'flow_a', 'flow_b', 'date', 'time']
            
        try:
            # Zip the filtered data with the filtered variable names
            return dict(zip(filtered_variables, filtered_data))

        except Exception as e:
            print(f'Error parsing O3 packet: {data}, Error: {e}')


if __name__ == "__main__":
    # Argument parser to handle command-line inputs
    parser = argparse.ArgumentParser(description="Test the 2Btech Ozone Analyzer driver.")
    
    parser.add_argument('-p', '--port', required=True, help="Serial port to connect to (e.g., COM3 or /dev/ttyUSB0).")
    parser.add_argument('-t', '--test', type=int, help="Test mode: Number of data packets to read and then exit.")
    
    args = parser.parse_args()

    # Create an instance of O3_2Btech
    analyzer = O3_2Btech(port=args.port)
    
    # Connect to the instrument
    analyzer.connect()
    
    # Start data collection
    analyzer.start_data_collection()

    # If in test mode, wait until the specified number of packets is collected
    try:
        if args.test:
            analyzer.verbose = True
            time.sleep(args.test * 2)  # Assuming one packet every 2 seconds
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
    print("Collected data:")
    print(df)
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()