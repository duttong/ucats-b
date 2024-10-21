#! /usr/bin/env python

import pandas as pd
from datetime import datetime
import time
import os
from pathlib import Path
from argparse import ArgumentParser
import yaml
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QTimer

from display_panel import DisplayPanel
from aeris import Aeris
from o3_sensor import O3_2Btech
from h2o_sensor import Maycomm
config_file = Path('config.yaml')

def load_config(file_path='config.yaml'):
    """ Load the configuration from a YAML file """
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

class TDL_package(QMainWindow):
    def __init__(self, stream_size=100):
        super().__init__()
        self.config = load_config(config_file)
        self.file_path = self.create_filename()

        # Stream size (number of rows to keep) and initialize empty streams
        self.stream_size = stream_size
        self.stream1 = pd.DataFrame()
        self.stream2 = pd.DataFrame()
        self.stream3 = pd.DataFrame()
        self.stream4 = pd.DataFrame()

        # Initialize the display panel
        self.setWindowTitle("UCATS-B")
        self.setGeometry(100, 100, 250, 350)
        self.display_panel = DisplayPanel(config_file)
        self.setCentralWidget(self.display_panel)

        # Create instances for sensors on different ports (as in the original code)
        devices = self.config['devices']
        self.device_1 = Aeris(
            port=devices['aeris1']['serial_port'],
            prefix=devices['aeris1']['data_var_prefix'],
            sim_mode=devices['aeris1']['sim_mode']
        )
        
        self.device_2 = Aeris(
            port=devices['aeris2']['serial_port'],
            prefix=devices['aeris2']['data_var_prefix'],
            sim_mode=devices['aeris2']['sim_mode']
        )

        self.device_3 = O3_2Btech(
            port=devices['ozone']['serial_port'],
            prefix=devices['ozone']['data_var_prefix'],
            sim_mode=devices['ozone']['sim_mode']
        )

        self.device_4 = Maycomm(
            port=devices['h2o']['serial_port'],
            prefix=devices['h2o']['data_var_prefix'],
            sim_mode=devices['h2o']['sim_mode']
        )
        
        # Connect to each device
        self.device_1.connect()
        self.device_2.connect()
        self.device_3.connect()
        self.device_4.connect()

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

    def create_filename(self, prefix="tdl"):
        # Get the current date and hour
        current_time = datetime.now()
        # Format the filename as "{prefix}-YYYYMMDDHH.csv"
        filename = f"{prefix}-{current_time.strftime('%Y%m%d%H')}.csv"
        return filename

    def start_collection(self, run_duration=None):
        # Start data collection
        self.device_1.start_data_collection()
        self.device_2.start_data_collection()
        self.device_3.start_data_collection()
        self.device_4.start_data_collection()

        # Start the timer to collect data every 1 seconds
        self.timer.start(1000)

        if run_duration is not None:
            # Stop collection after run_duration
            QTimer.singleShot(run_duration * 1000, self.stop_collection)

    def collect_data(self):
        # Fetch data from devices
        data_1 = self.device_1.get_all_data()
        data_2 = self.device_2.get_all_data()
        data_3 = self.device_3.get_all_data()
        data_4 = self.device_4.get_all_data()

        # Append new data to streams
        self.stream1 = pd.concat([self.stream1, pd.DataFrame(data_1)], ignore_index=True)
        self.stream2 = pd.concat([self.stream2, pd.DataFrame(data_2)], ignore_index=True)
        self.stream3 = pd.concat([self.stream3, pd.DataFrame(data_3)], ignore_index=True)
        self.stream4 = pd.concat([self.stream4, pd.DataFrame(data_4)], ignore_index=True)

        # Update the display panel with the latest data
        try:
            self.display_panel.update_time(data_1[-1])
            self.display_panel.update_display_data('aeris1', data_1[-1])
        except IndexError:
            pass
        try:
            self.display_panel.update_display_data('aeris2', data_2[-1])
        except IndexError:
            pass
        try:
            self.display_panel.update_display_data('ozone', data_3[-1])
        except IndexError:
            pass
        try:
            self.display_panel.update_display_data('h2o', data_4[-1])
        except IndexError:
            pass


        # Merge the data streams and save to CSV
        if not self.stream1.empty and not self.stream2.empty:
            full_data = pd.merge(self.stream1, self.stream2, on='datetime', how='outer')
            full_data = pd.merge(full_data, self.stream3, on='datetime', how='outer')
            full_data = pd.merge(full_data, self.stream4, on='datetime', how='outer')

            # Remove the last 4 lines
            full_data = full_data[:-4]

            # Filter and save new data
            if self.last_saved_datetime is not None:
                full_data = full_data[full_data['datetime'] > self.last_saved_datetime]

            if not full_data.empty:
                full_data.to_csv(self.file_path, mode='a', index=False, header=not os.path.exists(self.file_path))
                self.last_saved_datetime = full_data['datetime'].max()

            # Limit the memory footprint
            self.stream1 = self.stream1.tail(self.stream_size)
            self.stream2 = self.stream2.tail(self.stream_size)
            self.stream3 = self.stream3.tail(self.stream_size)
            self.stream4 = self.stream4.tail(self.stream_size)

            # Print last 5 rows
            #print(full_data[['datetime', 'd1_N2O_ppm', 'd2_N2O_ppm', 'oz_o3']].tail(5).to_string(header=False))

    def stop_collection(self):
        # Stop data collection and disconnect devices
        self.timer.stop()
        self.device_1.stop_data_collection()
        self.device_2.stop_data_collection()
        self.device_3.stop_data_collection()
        self.device_4.stop_data_collection()
        self.device_1.disconnect()
        self.device_2.disconnect()
        self.device_3.disconnect()
        self.device_4.disconnect()
        print("Data collection stopped.")

def main():
    # Create the argument parser
    parser = ArgumentParser(description="Run TDL Package for data collection.")
    parser.add_argument('-t', '--time', type=int, help="Duration to run the data collection (in seconds).", default=None)

    # Parse the arguments
    args = parser.parse_args()

    app = QApplication(sys.argv)

    # Create the TDL_package instance with the provided stream size
    package = TDL_package()
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