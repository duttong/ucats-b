#! /usr/bin/env python

import time
import argparse
from pathlib import Path
import yaml
import threading
import random

from labjack import ljm


class TSeriesLabJack:
    """ A simple class for interfacing with T4, T7, and T8 Labjack devices. """
    def __init__(self, config_file='config-labjack.yaml', prefix=None, sim_mode=False):
        if Path(config_file).exists():
            self.config_file = self.load_config(config_file)
        else:
            print(f'Missing labjack config file {config_file}')
            return
        self.prefix = prefix
        self.sim_mode = sim_mode
        self.handle = self.connect()

    def load_config(self, file_path):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def connect(self):
        """Connects to a LabJack T-Series device."""
        if self.sim_mode:
            print("Labjack running in simulate mode.")
        else:
            try:
                handle = ljm.open(ljm.constants.dtANY, ljm.constants.ctANY, "ANY")
            except ljm.LJMError as e:
                print(f"Failed to connect to LabJack: {e}")
                quit()
            info = ljm.getHandleInfo(handle)
            print(f"Opened LabJack - Device Type: {info[0]}, Connection Type: {info[1]}, Serial: {info[2]}")
            return handle

    def disconnect(self):
        """Closes the LabJack connection."""
        ljm.close(self.handle)

    def start_data_collection(self):
        """Start a background thread to collect data or simulate test data."""
        if not self.sim_mode:
            print("Labjack is not connected. Call connect() first.")
            return

        self.is_collecting = True
        if self.sim_mode:
            threading.Thread(target=self._simulate_test_data, daemon=True).start()
        else:
            threading.Thread(target=self._collect_data, daemon=True).start()

    def _collect_data(self):
        """Collect data continuously from the device and store it in the buffer."""
        while self.is_collecting:
            try:
                # Read analog channels
                data = self.ser.readline().decode()
                if len(data) > 10:
                    parsed_data = self.parse_o3(data, self.prefix)
                    with self.lock:
                        self.data_buffer.append(parsed_data)  # Append new data to the buffer
                    if self.verbose:
                        data = data.replace('\n', '')
                        print(f"Raw data: {data}")
            except Exception as e:
                print(f"Error during data collection: {e}")
            time.sleep(1.0)  # Adjust the interval if needed

    def _simulate_test_data(self):
        """Simulate test data generation every 2 seconds."""
        while self.is_collecting:
            test_packet = self.generate_test_data()
            parsed_data = self.parse_o3(test_packet, self.prefix)
            with self.lock:
                self.data_buffer.append(parsed_data)
            if self.verbose:
                print(f"Test data: {test_packet}")
            time.sleep(2.0)  # Simulate data every 2 seconds

    def read_analog(self, address: int) -> float:
        """Reads an analog value from a given channel."""
        return ljm.eReadName(self.handle, f'AIN{address}')
    
    def read_all_analogs(self) -> list:
        """ Reads all four channels on the T4 """
        cmds = [f'AIN{add}' for add in [0, 1, 2, 3]]
        return ljm.eReadNames(self.handle, len(cmds), cmds)

    def read_digital(self, address: int) -> float:
        """Reads a digital value from a given channel."""
        return ljm.eReadName(self.handle, f'FIO{address}')

    def write_digital(self, address: int, state: int) -> None:
        """Sets a digital state (0 or 1) for a given channel."""
        ljm.eWriteName(self.handle, f'FIO{address}', state)



if __name__ == '__main__':
    TOGGLE_DELAY = 0.05
    TOGGLE_DURATION = 1

    parser = argparse.ArgumentParser(description='Basic control of a T-Series LabJack')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--config', metavar='FILE', default='labjack.yaml', help='Configuration and timing file.')
    group.add_argument('--high', type=int, metavar='ADD', help='Set digital address to high (1)')
    group.add_argument('--low', type=int, metavar='ADD', help='Set digital address to low (0)')
    group.add_argument('--tog', type=int, metavar='ADD', help='Toggle digital address from low to high and back')

    args = parser.parse_args()

    jack = TSeriesLabJack(config_file=args.config)
    try:
        if args.high is not None:
            jack.write_digital(args.high, 1)
        elif args.low is not None:
            jack.write_digital(args.low, 0)
        elif args.tog is not None:
            jack.write_digital(args.tog, 0)
            time.sleep(TOGGLE_DELAY)
            jack.write_digital(args.tog, 1)
            time.sleep(TOGGLE_DURATION)
            jack.write_digital(args.tog, 0)
    finally:
        jack.disconnect()