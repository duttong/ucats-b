from o3 import O3_2Btech
import time

# Create instances for 3 instruments on different ports
instrument_1 = O3_2Btech(port="/dev/ttyUSB0")
instrument_1.verbose = True
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
        # Simulate a periodic request for data every 10 seconds
        time.sleep(10)
        
        # Fetch data from each instrument
        data_1 = instrument_1.get_all_data()
        #data_2 = instrument_2.get_all_data()
        #data_3 = instrument_3.get_all_data()

        # Print or process the data
        print("Instrument 1 Data:", data_1)
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