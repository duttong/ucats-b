#! /usr/bin/env python

import pandas as pd
import time
import os

from aeris import Aeris
from o3 import O3_2Btech

# Function to convert the datetime string to a pandas datetime object
def parse_datetime(data_entry):
    return pd.to_datetime(data_entry['datetime'], format='%m/%d/%Y %H:%M:%S.%f')

# Path to save the CSV file
file_path = 'merged_data.csv'

# Initialize empty streams
stream1 = pd.DataFrame()
stream2 = pd.DataFrame()

# Create instances for sensors on different ports (as in the original code)
instrument_1 = Aeris(port="/dev/ttyUSB0")
instrument_1.verbose = False
instrument_2 = O3_2Btech(port="unknown", sim_mode=True)

# Connect to each instrument
instrument_1.connect()
instrument_2.connect()

# Start data collection for each instrument
instrument_1.start_data_collection()
instrument_2.start_data_collection()

# Load existing data if the CSV already exists
if os.path.exists(file_path):
    previous_data = pd.read_csv(file_path, parse_dates=['datetime'])
    last_saved_datetime = previous_data['datetime'].max()
    del previous_data   # remove from memory
else:
    last_saved_datetime = None

try:
    while True:
        # Simulate a periodic request for data every 2 seconds
        time.sleep(2)
        
        # Fetch data from each analyzer
        data_1 = pd.DataFrame(instrument_1.get_all_data())
        data_2 = pd.DataFrame(instrument_2.get_all_data())

        # Append new data to the existing streams
        stream1 = pd.concat([stream1, data_1], ignore_index=True)
        stream2 = pd.concat([stream2, data_2], ignore_index=True)

        # Merge the data streams on 'datetime'
        full_data = pd.merge(stream1, stream2, on='datetime', how='outer')
        full_data = full_data[:-4]

        # If a previous max datetime exists, filter new data
        if last_saved_datetime is not None:
            full_data = full_data[full_data['datetime'] > last_saved_datetime]
        
        # Only append new data to the CSV file
        if not full_data.empty:
            full_data.to_csv(file_path, mode='a', index=False, header=not os.path.exists(file_path))
            last_saved_datetime = full_data['datetime'].max()  # Update last saved datetime

        # Keep only the last 100 rows of data in memory for both streams
        stream1 = stream1.tail(100)
        stream2 = stream2.tail(100)

        # Print the last 5 rows for reference
        print(full_data[['datetime', 'co2_2', 'n2o_2', 'o3']].tail(5))

except KeyboardInterrupt:
    print("Stopping data collection.")

finally:
    # Stop data collection and disconnect all instruments
    instrument_1.stop_data_collection()
    instrument_2.stop_data_collection()
    
    instrument_1.disconnect()
    instrument_2.disconnect()