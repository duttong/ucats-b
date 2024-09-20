import pandas as pd
from datetime import datetime

from o3 import O3_2Btech
from aeris import Aeris
import time

# Initialize an empty DataFrame to store the data
columns = ['datetime', 'inlet_num', 'press_gas', 'temp_gas', 'therm1', 'therm2', 
           'therm3', 'therm4', 'laser_t', 'det_t', 'ramp', 'co2_1', 'co2_2', 
           'h2o', 'n2o_1', 'n2o_2', 'input_v', 'fet_t', 'tec_t1', 'tec_t2', 
           'tec_v', 'tec_amp']
dtypes = {
    'datetime': 'datetime64[ns]',
    'inlet_num': 'str',
    'press_gas': 'float64',
    'temp_gas': 'float64',
    'therm1': 'float64',
    'therm2': 'float64',
    'therm3': 'float64',
    'therm4': 'float64',
    'laser_t': 'int64',
    'det_t': 'int64',
    'ramp': 'float64',
    'co2_1': 'float64',
    'co2_2': 'float64',
    'h2o': 'float64',
    'n2o_1': 'float64',
    'n2o_2': 'float64',
    'input_v': 'int64',
    'fet_t': 'float64',
    'tec_t1': 'float64',
    'tec_t2': 'float64',
    'tec_v': 'float64',
    'tec_amp': 'float64'
}

# Initialize the DataFrame with the correct column names and dtypes
data_df = pd.DataFrame(columns=columns).astype(dtypes)

# Function to convert the datetime string to a pandas datetime object
def parse_datetime(data_entry):
    return pd.to_datetime(data_entry['datetime'], format='%m/%d/%Y %H:%M:%S.%f')

# Create instances for sensors on different ports
#instrument_1 = O3_2Btech(port="/dev/ttyUSB0")
instrument_1 = Aeris(port="/dev/ttyUSB0")
instrument_1.verbose = False
#instrument_2 = O3_2Btech(port="COM4")
#instrument_3 = O3_2Btech(port="COM5")

# Connect to each instrument
instrument_1.connect()
#instrument_2.connect()
#instrument_3.connect()

# Start data collection for each instrument
instrument_1.start_data_collection()
#instrument_2.start_data_collection()
#instrument_3.start_data_collection()

try:
    while True:
        # Simulate a periodic request for data every 2 seconds
        time.sleep(2)
        
        # Fetch data from each instrument
        data_1 = instrument_1.get_all_data()
        new_data_1 = pd.DataFrame(data_1)
        #data_2 = instrument_2.get_all_data()
        #data_3 = instrument_3.get_all_data()

        new_data_1['datetime'] = pd.to_datetime(new_data_1['datetime'], format='%m/%d/%Y %H:%M:%S.%f')

        # Append new data to the existing DataFrame
        data_df = pd.concat([data_df, new_data_1], ignore_index=True)
        
        """ This works if all of the clocks are synced 
        # Get the current time
        current_time = datetime.now()
        # Remove rows older than 20 seconds
        data_df = data_df[data_df['datetime'] > (current_time - pd.Timedelta(seconds=20))]
        """
        data_df = data_df.tail(5)
        print(data_df)
        
        # Print or process the data
        #print("Instrument 1 Data:", data_df)
        #print("Instrument 2 Data:", data_2)
        #print("Instrument 3 Data:", data_3)

except KeyboardInterrupt:
    print("Stopping data collection.")

finally:
    # Stop data collection and disconnect all instruments
    instrument_1.stop_data_collection()
    #instrument_2.stop_data_collection()
    #instrument_3.stop_data_collection()
    
    instrument_1.disconnect()
    #instrument_2.disconnect()
    #instrument_3.disconnect()