#!/usr/bin/env python

import logging
import serial
import threading
import time
from datetime import datetime
import random
import argparse

logger = logging.getLogger(__name__)

class Aeris:
    def __init__(self, port, baudrate=9600, timeout=1, prefix=None, sim_mode=False, verbose=False, inst_num=1):
        """
        Initialize the Aeris TDL class with the device port and serial configuration.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyUSB0').
            baudrate (int, optional): Baud rate for serial communication. Default is 9600.
            timeout (int, optional): Timeout in seconds for serial communication. Default is 1 second.
            prefix (str, optional): A prefix string applied to the names of all the data variable returned.
            sim_mode (bool, optional): If True, simulate data instead of using the real device. Default is False.
            verbose (bool, optional): If True, print data to stdout (the screen).
            inst_num (int, optional): Distinguishes between instruments (1 = CO, 2 = CO2, 3 = CH4).
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.running = False    # keeps track if serial is up and running
        self.ser = None
        self.data_buffer = []  # Buffer to store incoming data
        self.is_collecting = False
        self.lock = threading.Lock()  # This lock is for the shared data buffer
        self.serial_lock = threading.Lock()  # This lock is specifically for serial communication
        self.verbose = verbose
        self.prefix = '' if prefix is None else prefix
        self.sim_mode = sim_mode
        self.inst_num = inst_num

        # variable names from the header returned by the Aeris instrument.
        # NOTE: The order of these variables is important since they line up with the raw data.
        if inst_num == 1:
            # CO instrument
            self.variables_org = [
                "Unused_0", "P_mbars", "T_gas", "T_ambient", "Unused_1", "Unused_2",
                "N2O_ppb", "H2O_ppm", "CO_ppb", "T_TEC_Sink", "Unused_3"]
            self.variables = self.variables_org + ['COc_ppb', 'N2Oc_ppb']

        elif inst_num == 3:
            # CH4 instrument
            self.variables_org = [
                "Unused_0", "P_mbars", "T_gas", "T_ambient", "T_TEC", "Unused_1",
                "Unused_2", "CH4_ppb", "H2O_ppm", "T_TEC_Sink", "Unused_3"]
            self.variables = self.variables_org + ['CH4c_ppb', 'H2Oc_ppm']

        else:
            self.variables_org = [
                "Unused_0", "P_mbars", "T_gas", "Unused_1", "T_ambient", "Unused_2", "Unused_3", 
                "Laser_PID", "Det_PID", "Unused_4", "Unused_5", "Unused_6",
                "Unused_7", "Unused_8", "Unused_9", "Unused_10", "Unused_11", "Unused_12", 
                "Unused_13", "Unused_14", "Unused_15", "Unused_16", "Unused_17", "Unused_18", 
                "Unused_19", "Unused_20", "Unused_21", "Unused_22", "Unused_23", "Unused_24", 
                "Ramp_Ampl", "Unused_25", "CO2_ppm", "H2O_ppm", "Unused_26", "N2O_ppb", 
                "Power_Input_mV", "T_FET", "T_TEC", "T_TEC_Sink", 
                "TEC_Power", "Unused_27"]
            self.variables = self.variables_org + ['CO2c_ppm', 'N2Oc_ppb']
            
        
    def connect(self):
        """Establish the serial connection to the Aeris device or simulate connection."""
        if self.sim_mode:
            logger.info("Running in simulate mode. Simulating data.")
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
                self.running = True
                logger.info(f"Connected to Aeris device on port {self.port}")
            except serial.SerialException as e:
                logger.error(f"Error connecting to Aeris device on {self.port}: {e}")
                self.running = False
                self.ser = None

    def disconnect(self):
        """Close the serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            logger.info("Disconnected from Aeris device.")
        else:
            logger.info("No active Aeris connection to disconnect.")

    def start_data_collection(self):
        """Start a background thread to collect data or simulate test data."""
        if self.is_collecting:
            logger.info("Aeris data collection is already running.")
            return
        if not self.sim_mode and (not self.ser or not self.ser.is_open):
            logger.warning("Aeris device not connected. Call connect() first.")
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

                logger.debug(f"Raw data char length({len(data)}): {data.replace(chr(10), '')}")

                # Data parsing and buffer handling should be outside of serial lock
                if len(data) > 80:
                    parsed_data = self.parse(data)
                    # Locking around the shared buffer to protect data access
                    with self.lock:
                        self.data_buffer.append(parsed_data)

            except Exception:
                logger.exception("Error during Aeris data collection")
            time.sleep(0.5)  # Adjust the interval if needed

    def _simulate_test_data(self):
        """Simulate test data generation every 1 second."""
        while self.is_collecting:
            parsed_data = self.generate_test_data()
            parsed_data = self.parse(parsed_data)
            with self.lock:
                self.data_buffer.append(parsed_data)
            logger.debug(f"Test data: {parsed_data}")
            time.sleep(1)  # Simulate data every 1 second

    def send_command(self, command):
        """
        Send a serial command to the Aeris instrument.
        Args:
            command (str): The command to be sent to the device.
        """
        if not self.sim_mode:
            with self.serial_lock:
                if self.running:
                    self.ser.write(command.encode())
                    response = self.ser.readline().decode().strip()
                    logger.debug(f"Sent: {command}, Received: {response}")
                else:
                    response = 'Aeris offline'
                return response
        else:
            simulated_response = f"Simulated response to {command}"
            logger.debug(f"Sent (simulated): {command}, Received: {simulated_response}")
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

    def parse(self, packet):
        """
        Parse a data packet from the Aeris analyzer and replace the datetime with the computer's
        datetime. Also, drop variables demed 'Unused'.

        Args:
            packet (str): Raw packet data from the analyzer.

        Returns:
            dict: Parsed data as a dictionary.

        Raises:
            ValueError: If the packet data doesn't match the expected number of variables.
        """
        # Clean and split the incoming packet
        data = packet.replace('\r\n', '').split(',')

        # Replace the Aeris datetime with the current system time (rounded to the nearest second)
        current_datetime = datetime.now().replace(microsecond=0)
        data[0] = current_datetime

        # Apply prefix if provided
        variables = ['datetime'] + [f'{self.prefix or ""}{var}' for var in self.variables_org]
        
        # Check if the data length matches the expected number of variables
        if len(data) != len(variables):
            raise ValueError(f"Data length ({len(data)}) does not match expected variables ({len(variables)}).")

        # Combine variables and data into a dictionary
        parsed_data = dict(zip(variables, data))

        # add calibrated data
        parsed_data = self.calibrated(parsed_data)

        # Convert values to float and round based on variable name
        for key in parsed_data.keys():
            try:
                if "ppm" in key:
                    parsed_data[key] = round(float(parsed_data[key]), 2)  # Round
                elif "ppb" in key:
                    parsed_data[key] = round(float(parsed_data[key]) * 1000, 2)  # Convert ppm to ppb
                elif "T_" in key:
                    parsed_data[key] = round(float(parsed_data[key]), 2)  # Round temperature values
                elif "mbar" in key:
                    parsed_data[key] = round(float(parsed_data[key]), 2)  # Round pressure values
                elif "Power" in key:
                    parsed_data[key] = round(float(parsed_data[key]), 2)  # Round power values
            except ValueError as e:
                raise ValueError(f"Cannot convert value of '{key}' to float: {parsed_data[key]}") from e
                            
        # Drop items that contain "Unused" in the key
        parsed_data = {key: value for key, value in parsed_data.items() if "Unused" not in key}
        return parsed_data
    
    def calibrated(self, data_dict):

        # calibrations from 20250208
        if self.inst_num == 1:
            # old inst
            n2o = float(data_dict.get(f'{self.prefix}N2O_ppb', float('nan')))
            n2o_corr = (n2o*1.0363*1000 - 6.2)/1000
            co = float(data_dict.get(f'{self.prefix}CO_ppb', float('nan')))
            co_corr = (co*1.179*1000 - 12.7)/1000
            data_dict[f'{self.prefix}N2Oc_ppb'] = n2o_corr
            data_dict[f'{self.prefix}COc_ppb'] = co_corr
        elif self.inst_num == 3:
            # CH4 instrument — calibration TBD, identity for now
            ch4 = float(data_dict.get(f'{self.prefix}CH4_ppb', float('nan')))
            data_dict[f'{self.prefix}CH4c_ppb'] = ch4
            # H2O calibration TBD, identity for now
            h2o = float(data_dict.get(f'{self.prefix}H2O_ppm', float('nan')))
            data_dict[f'{self.prefix}H2Oc_ppm'] = h2o
        else:
            # new inst
            n2o = float(data_dict.get(f'{self.prefix}N2O_ppb', float('nan')))
            n2o_corr = (n2o*1.0088*1000 - 14.0)/1000
            co2 = float(data_dict.get(f'{self.prefix}CO2_ppm', float('nan')))
            co2_corr = co2*1.029 - 3.9
            data_dict[f'{self.prefix}N2Oc_ppb'] = n2o_corr
            data_dict[f'{self.prefix}CO2c_ppm'] = co2_corr
        return data_dict

    def generate_test_data(self):
        """
        Generate simulated data for all variables.

        Returns:
            str: Simulated data as a comma-delimited string.
        """
        simulated_data = []

        for var in self.variables_org:
            if var == "P_mbars":
                simulated_data.append(f"{round(random.uniform(900, 1100), 2):.2f}")
            elif var in ["T_FET", "T_TEC", "T_TEC_Sink"]:
                simulated_data.append(f"{round(random.uniform(20, 40), 2):.2f}")
            elif var.startswith("T"):
                simulated_data.append(f"{round(random.uniform(15, 25), 2):.2f}")
            elif var in ["Laser_PID", "Det_PID"]:
                simulated_data.append(f"{round(random.uniform(0, 100), 2):.2f}")
            elif var == "Ramp_Ampl":
                simulated_data.append(f"{round(random.uniform(0.0, 1.0), 2):.2f}")
            elif var == "CH4_ppb":
                simulated_data.append(f"{round(random.uniform(1.8, 2.0), 4):.4f}")
            elif var == "N2O_ppb":
                simulated_data.append(f"{round(random.uniform(.300, .400), 2):.2f}")
            elif var == "CO_ppb":
                simulated_data.append(f"{round(random.uniform(.100, .200), 2):.3f}")
            elif var == "CO2_ppm":
                simulated_data.append(f"{round(random.uniform(200, 400), 2):.2f}")
            elif var == "H2O_ppm":
                simulated_data.append(f"{round(random.uniform(.1000, .2000), 2):.2f}")
            elif var == "Power_Input_mV":
                simulated_data.append(f"{round(random.uniform(4.5, 5.5), 2):.2f}")
            elif var == "TEC_Power":
                simulated_data.append(f"{round(random.uniform(0.5, 2.0), 2):.2f}")
            else:
                simulated_data.append("-99")

        packet = "0000," + ",".join(simulated_data) + "\r\n"
        return packet
    

if __name__ == "__main__":
    # Argument parser to handle command-line inputs
    parser = argparse.ArgumentParser(description="Test the Aeris driver.")
    
    parser.add_argument('-p', '--port', required=False, help="Serial port to connect to (e.g., COM3 or /dev/ttyUSB0).")
    parser.add_argument('-i', '--inst', type=int, default=1, help="Instrument number (1 = CO, 2 = CO2, 3 = CH4)")
    parser.add_argument('-t', '--test', type=int, help="Test mode: Number of data packets to read and then exit.")
    parser.add_argument('-s', '--simulate', action='store_true', help="Simulate mode: Number of data packets to read and then exit.")
    parser.add_argument('-v', '--verbose', action='store_true', help="Print data to screen")
    
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    # Determine if we are running in test mode
    sim_mode = args.port is None

    # Create an instance of Aeris
    analyzer = Aeris(port=args.port if not sim_mode else 'test', prefix='a1_', sim_mode=sim_mode, inst_num=args.inst)

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
    if not args.verbose:
        print(data)
    
    # Stop data collection and disconnect
    analyzer.stop_data_collection()
    analyzer.disconnect()