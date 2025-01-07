#!/usr/bin/env python

import serial
import threading
import time
from datetime import datetime
import random
import argparse

class Aeris:

    def __init__(self, port, baudrate=9600, timeout=1, prefix=None, sim_mode=False, verbose=False):
        """
        Initialize the Aeris TDL class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 9600.
            timeout (int, optional): Timeout in seconds for serial communication. Default is 1 second.
            prefix (str, optional): A prefix string applied to the names of all the data variable returned.
            sim_mode (bool, optional): If True, simulate data instead of using the real device. Default is False.
            verbose (bool, optional): If True, print data to stdout (the screen).
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.data_buffer = []  # Buffer to store incoming data
        self.is_collecting = False
        self.lock = threading.Lock()  # This lock is for the shared data buffer
        self.serial_lock = threading.Lock()  # This lock is specifically for serial communication
        self.verbose = verbose
        self.prefix = prefix
        self.sim_mode = sim_mode

        # variable names from the header returned by the Aeris instrument.
        self.variables = [
            "datetime", "Inlet_Number", "P_mbars", "T0_degC", "T1_degC", "T2_degC", 
            "T5_degC", "Tgas_degC", "Laser_PID_Readout", "Det_PID_Readout", "win0Fit0", 
            "win0Fit1", "win0Fit2", "win0Fit3", "win0Fit4", "win0Fit5", "win0Fit6", 
            "win0Fit7", "win0Fit8", "win0Fit9", "win1Fit0", "win1Fit1", "win1Fit2", 
            "win1Fit3", "win1Fit4", "win1Fit5", "win1Fit6", "win1Fit7", "win1Fit8", 
            "win1Fit9", "Det_Bkgd", "Ramp_Ampl", "N2O_ppm", "H2O_ppm", "CO_ppm", 
            "Power_Input_mV", "FET_T_degC", "TEC_Temp_degC", "TEC_Sink_Temp_degC", 
            "TEC_Power_W", "Wall_Code", "GPS_Time", "Latitude", "Longitude", "Alt_m"]
        
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
                # Locking only around serial port access to avoid conflicts
                with self.serial_lock:
                    # Read a line from the analyzer
                    data = self.ser.readline().decode()
                
                # Data parsing and buffer handling should be outside of serial lock
                if len(data) > 300:
                    parsed_data = self.parse(data, self.prefix)
                    # Locking around the shared buffer to protect data access
                    with self.lock:
                        self.data_buffer.append(parsed_data)
                    
                if self.verbose:
                    pass
                    #print(f"Raw data: {data.replace('\n', '')}")
            except Exception as e:
                print(f"Error during data collection: {e}")
            time.sleep(0.5)  # Adjust the interval if needed

    def _simulate_test_data(self):
        """Simulate test data generation every 1 second."""
        while self.is_collecting:
            parsed_data = self.generate_test_data(self.prefix)
            with self.lock:
                self.data_buffer.append(parsed_data)
            if self.verbose:
                pass
                #print(f"Test data: {parsed_data}")
            time.sleep(1)  # Simulate data every 1 second

    def send_command(self, command):
        """
        Send a serial command to the Aeris instrument.
        Args:
            command (str): The command to be sent to the device.
        """
        if not self.sim_mode:
            with self.serial_lock:
                self.ser.write(command.encode())
                response = self.ser.readline().decode().strip()
                self.command_response = response  # Store response
                if self.verbose:
                    print(f"Sent: {command}, Received: {response}")
                return response
        else:
            # Simulate response
            simulated_response = f"Simulated response to {command}"
            if self.verbose:
                print(f"Sent (simulated): {command}, Received: {simulated_response}")
            self.command_response = simulated_response
            return simulated_response

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

    def parse(self, packet, prefix):
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

        """    
        # Keep only the variables you need by filtering out indices ...
        #filtered_data = [value for i, value in enumerate(data) if i not in [43, 44, 45, 46]]
        filtered_variables = ['datetime', 'inlet_num', 'press_gas', 'temp_gas', 'therm1', 'therm2', 'therm3', 'therm4', 
            'laser_t', 'det_t', 'unk1', 'unk2', 'unk3', 'unk4', 'unk5', 'unk6', 'unk7', 'unk8', 'unk9', 
            'unk10', 'unk11', 'unk12', 'unk13', 'unk14', 'unk15', 'unk16', 'unk17', 'unk18', 'unk19', 
            'unk20', 'unk21', 'ramp', 'co2_1', 'co2_2', 'h2o', 'n2o_1', 'n2o_2', 'input_v', 
            'fet_t', 'tec_t1', 'tec_t2', 'tec_v', 'tec_amp', 'unk43', 'unk44', 'unk45', 'unk46']
        
        if prefix:
            filtered_variables = [f'{prefix}{v}' if v[0:3] != 'unk' else v for v in filtered_variables ]
        """

        if prefix:
            self.variables = [f'{prefix}{v}' for v in self.variables]

        try:
            # Zip the filtered variables with data
            zipped_data = dict(zip(self.variables, data))
            
            # Filter out variables that start with 'unk'
            filtered_dict = {key: value for key, value in zipped_data.items() if not key.startswith('unk')}
            
            return filtered_dict

        except Exception as e:
            print(f'Error parsing Aeris packet: {data}, Error: {e}')

    @staticmethod
    def generate_test_data(prefix):
        """Generate simulated data for all variables, excluding those that start with 'win' or 'Wall'."""
        current_time = datetime.now().replace(microsecond=0)
        inlet_num = 1

        # Generate simulated data for each variable.
        simulated_data = {
            "datetime": current_time,
            "Inlet_Number": inlet_num,
            "P_mbars": round(random.uniform(900, 1100), 2),
            "T0_degC": round(random.uniform(15, 25), 2),
            "T1_degC": round(random.uniform(15, 25), 2),
            "T2_degC": round(random.uniform(15, 25), 2),
            "T5_degC": round(random.uniform(15, 25), 2),
            "Tgas_degC": round(random.uniform(15, 25), 2),
            "Laser_PID_Readout": round(random.uniform(0, 100), 2),
            "Det_PID_Readout": round(random.uniform(0, 100), 2),
            "Det_Bkgd": round(random.uniform(0, 10), 2),
            "Ramp_Ampl": round(random.uniform(0.0, 1.0), 2),
            "N2O_ppm": round(random.uniform(300, 400), 2),
            "H2O_ppm": round(random.uniform(1000, 2000), 2),
            "CO_ppm": round(random.uniform(0, 10), 2),
            "Power_Input_mV": round(random.uniform(4.5, 5.5), 2),
            "FET_T_degC": round(random.uniform(30, 40), 2),
            "TEC_Temp_degC": round(random.uniform(20, 30), 2),
            "TEC_Sink_Temp_degC": round(random.uniform(20, 30), 2),
            "TEC_Power_W": round(random.uniform(0.5, 2.0), 2),
            "GPS_Time": current_time.time(),
            "Latitude": round(random.uniform(-90, 90), 6),
            "Longitude": round(random.uniform(-180, 180), 6),
            "Alt_m": round(random.uniform(0, 5000), 2)
        }

        # Add entries for variables starting with 'win' as random floats.
        for i in range(10):
            simulated_data[f"win0Fit{i}"] = round(random.uniform(0, 1), 3)
            simulated_data[f"win1Fit{i}"] = round(random.uniform(0, 1), 3)

        # Add Wall_Code as a random integer for simplicity.
        simulated_data["Wall_Code"] = random.randint(0, 10)

        # Add the prefix to the keys, except for 'datetime'
        if prefix:
            simulated_data = {f'{prefix}{k}' if k != 'datetime' else k: v for k, v in simulated_data.items()}
        
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
    analyzer = Aeris(port=args.port if not sim_mode else 'test', prefix='a1_', sim_mode=sim_mode)

    # set verbose mode
    if args.verbose:
        analyzer.verbose = True
    
    # Connect to the instrument
    analyzer.connect()
    
    # Start data collection
    analyzer.start_data_collection()

    # If in test mode, wait until the specified number of packets is collected
    count = 0
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
    if not  args.verbose:
        print(data)
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()