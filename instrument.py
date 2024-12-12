#! /usr/bin/env python

import os
import sys
from argparse import ArgumentParser
from datetime import datetime
import pandas as pd
import yaml

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow

from lj import LabJackController
from aeris import Aeris
from display_panel import DisplayPanel
from h2o_sensor import Maycomm
from o3_sensor import O3_2Btech


class TDL_package(QMainWindow):
    def __init__(self, config_file='config.yaml', stream_size=100):
        super().__init__()
        self.config = self.load_config(config_file)
        self.file_path = self.create_filename()

        # Initialize the display panel
        self.setWindowTitle("UCATS-B")
        self.setGeometry(100, 100, 250, 350)
        self.display_panel = DisplayPanel(config_file)
        self.setCentralWidget(self.display_panel)

        # Stream size (number of rows to keep) and initialize empty streams
        self.stream_size = stream_size
        self.streams = {}  # Dictionary to store streams
        self.devices = {}  # Dictionary to store devices

        # Create instances for sensors on different ports (as in the original code)
        # Initialize devices dynamically from config
        for device_name, device_config in self.config['devices'].items():
            if device_name.lower().startswith('aeris'):
                device = Aeris(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode']
                )
            elif device_name.lower() == 'o3_sensor':
                device = O3_2Btech(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode']
                )
            elif device_name.lower() == 'h2o_sensor':
                device = Maycomm(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode']
                )
            elif device_name.lower() == 'labjack':
                device = LabJackController(
                    config_file=device_config['table'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode']
                )
            else:
                raise ValueError(f"Unknown device type: {device_name}")
            
            # Connect device and initialize stream
            device.connect()
            self.devices[device_name] = device
            self.streams[device_name] = pd.DataFrame()
        
        # Timer for periodic data collection
        self.timer = QTimer()
        self.timer.timeout.connect(self.collect_data)

        # Load existing data if the CSV file already exists
        if os.path.exists(self.file_path):
            previous_data = pd.read_csv(self.file_path, parse_dates=['datetime'])
            self.last_saved_datetime = previous_data['datetime'].max()
            del previous_data  # remove from memory
        else:
            self.last_saved_datetime = None

    def load_config(self, file_path='config.yaml'):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)
    
    def create_filename(self, prefix="tdl"):
        # Get the current date and hour
        current_time = datetime.now()
        # Format the filename as "{prefix}-YYYYMMDDHH.csv"
        filename = f"{prefix}-{current_time.strftime('%Y%m%d%H')}.csv"
        return filename

    def start_collection(self, run_duration=None):
        # Start data collection for all devices dynamically
        for device_name, device in self.devices.items():
            device.start_data_collection()

        # Start the timer to collect data every 1 second
        self.timer.start(1000)

        if run_duration is not None:
            # Stop collection after run_duration seconds
            QTimer.singleShot(run_duration * 1000, self.stop_collection)

    def collect_data(self):
        # Fetch data and append to respective streams
        for device_name, device in self.devices.items():
            try:
                data = device.get_all_data()
                self.streams[device_name] = pd.concat(
                    [self.streams[device_name], pd.DataFrame(data)], ignore_index=True
                )

                # Update the display panel with the latest data
                self.display_panel.update_display_data(device_name, data[-1])
            except IndexError:
                pass

        # Merge all streams into a single DataFrame
        full_data = None
        for stream_name, stream in self.streams.items():
            if full_data is None:
                full_data = stream
            else:
                full_data = pd.merge(full_data, stream, on='datetime', how='outer')

        if full_data is not None:
            # Remove the last N rows
            full_data = full_data[:-len(self.streams)]

            # Filter new data
            if self.last_saved_datetime is not None:
                full_data = full_data[full_data['datetime'] > self.last_saved_datetime]

            # Save new data to CSV
            if not full_data.empty:
                full_data.to_csv(self.file_path, mode='a', index=False, header=not os.path.exists(self.file_path))
                self.last_saved_datetime = full_data['datetime'].max()

            # Limit the memory footprint for each stream
            for stream_name in self.streams.keys():
                self.streams[stream_name] = self.streams[stream_name].tail(self.stream_size)

    def stop_collection(self):
        # Stop data collection and disconnect devices
        self.timer.stop()
        for device_name, device in self.devices.items():
            device.stop_data_collection()
            device.disconnect()
        print("Data collection stopped.")

def main():
    # Create the argument parser
    parser = ArgumentParser(description="Run TDL Package for data collection.")
    parser.add_argument("--config", type=str, default='config.yaml', help="Path to the configuration YAML file. (default=config.yaml)")
    parser.add_argument('-t', '--time', type=int, help="Duration to run the data collection (in seconds).", default=None)

    # Parse the arguments
    args = parser.parse_args()

    app = QApplication(sys.argv)

    # Create the TDL_package instance with the provided stream size
    package = TDL_package(config_file=args.config)
    package.show()

     # Start the data collection with the specified duration
    if args.time is not None:
        print(f"Starting data collection for {args.time} seconds.")
        package.start_collection(run_duration=args.time)
    else:
        print("Starting data collection without a specified time duration.")
        package.start_collection()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()