#! /usr/bin/env python

import pandas as pd
from datetime import datetime
import time
import os
from argparse import ArgumentParser

import config as cfg
from aeris import Aeris
from o3 import O3_2Btech

class TDL_package:
    def __init__(self, stream_size=100):
        # Path to save the CSV file
        self.file_path = self.create_filename()
        print(self.file_path)

        # Stream size and initialize empty streams
        self.stream_size = stream_size
        self.stream1 = pd.DataFrame()
        self.stream2 = pd.DataFrame()
        self.stream3 = pd.DataFrame()

        # Create instances for sensors on different ports (as in the original code)
        self.device_1 = Aeris(port=cfg.devices['aeris1'], 
                              prefix=cfg.data_var_prefix['aeris1'],
                              sim_mode=cfg.sim_mode['aeris1'])
        self.device_2 = O3_2Btech(port=cfg.devices['ozone'],
                                  prefix=cfg.data_var_prefix['ozone'],
                                  sim_mode=cfg.sim_mode['ozone'])
        self.device_3 = Aeris(port=cfg.devices['aeris2'],
                              prefix=cfg.data_var_prefix['aeris2'],
                              sim_mode=cfg.sim_mode['aeris2'])
        
        # Connect to each device
        self.device_1.connect()
        self.device_2.connect()
        self.device_3.connect()

        # Load existing data if the CSV already exists
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
        # Start data collection for each instrument
        self.device_1.start_data_collection()
        self.device_2.start_data_collection()
        self.device_3.start_data_collection()
        time.sleep(1)

        try:
            start_time = time.time()
            while run_duration is None or (time.time() - start_time) < run_duration:
                # Simulate a periodic request for data every 2 seconds
                time.sleep(2)

                # Fetch data from each analyzer
                data_1 = pd.DataFrame(self.device_1.get_all_data())
                data_2 = pd.DataFrame(self.device_2.get_all_data())
                data_3 = pd.DataFrame(self.device_3.get_all_data())

                # Append new data to the existing streams
                self.stream1 = pd.concat([self.stream1, data_1], ignore_index=True)
                self.stream2 = pd.concat([self.stream2, data_2], ignore_index=True)
                self.stream3 = pd.concat([self.stream3, data_3], ignore_index=True)

                if len(self.stream1) == 0 and len(self.stream2) == 0:
                    pass
                else:
                    # Merge the data streams on 'datetime'
                    full_data = pd.merge(self.stream1, self.stream2, on='datetime', how='outer')
                    full_data = pd.merge(full_data, self.stream3, on='datetime', how='outer')
                    # remove the last 4 lines. This is to insure all of the data streams have been read for data 4 seconds ago and older.
                    full_data = full_data[:-4]

                    # If a previous max datetime exists, filter new data
                    if self.last_saved_datetime is not None:
                        full_data = full_data[full_data['datetime'] > self.last_saved_datetime]

                    # Only append new data to the CSV file
                    if not full_data.empty:
                        full_data.to_csv(self.file_path, mode='a', index=False, header=not os.path.exists(self.file_path))
                        self.last_saved_datetime = full_data['datetime'].max()  # Update last saved datetime

                    # Keep only the last 'stream_size' rows of data in memory for both streams to limit memory requirements of the program.
                    self.stream1 = self.stream1.tail(self.stream_size)
                    self.stream2 = self.stream2.tail(self.stream_size)
                    self.stream3 = self.stream3.tail(self.stream_size)

                    # Print the last 5 rows for reference
                    print(full_data[['datetime', 'd1_co2_2', 'd2_n2o_2', 'oz_o3']].tail(5))

        except KeyboardInterrupt:
            print("Stopping data collection.")
        
        finally:
            # Stop data collection and disconnect all instruments
            self.device_1.stop_data_collection()
            self.device_2.stop_data_collection()
            self.device_1.disconnect()
            self.device_2.disconnect()

def main():
    # Create the argument parser
    parser = ArgumentParser(description="Run TDL Package for data collection.")
    parser.add_argument('-t', '--time', type=int, help="Duration to run the data collection (in seconds).", default=None)

    # Parse the arguments
    args = parser.parse_args()

    # Create the TDL_package instance with the provided stream size
    package = TDL_package()

    # Start the data collection with the specified duration
    package.start_collection(run_duration=args.time)

if __name__ == "__main__":
    main()