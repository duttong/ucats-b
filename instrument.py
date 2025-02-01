#! /usr/bin/env python

import os
import sys
import time
from argparse import ArgumentParser
from datetime import datetime
import threading
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
    def __init__(self, config_file='config.yaml', stream_size=100, verbose=False):
        super().__init__()
        self.verbose = verbose
        self.config_file = config_file
        self.config = self.load_config(config_file)
        self.file_path = self.create_filename()
        self.pilot_switch = False
        self.pressure_var = ''      # determined from o3_sensor
        self.pressure = 1200.0
        self.alt_high_event = threading.Event()     # above high alt threshold
        self.alt_low_event = threading.Event()      # below low alt threshold
        self.alt_high = 0       # mbar (these values are loaded from config.yaml)
        self.alt_low = 5000     # mbar
        self.start_time = datetime.now()
        #self.extra_vars = {'sol_cal': self.sol_cal}       # extra variables for the .csv file.\
        self.extra_vars = {}

        self.setWindowTitle("UCATS-B")
        self.setGeometry(100, 100, 250, 350)

        # Stream size (number of rows to keep) and initialize empty streams
        self.stream_size = stream_size
        self.streams = {}  # Dictionary to store streams
        self.devices = {}  # Dictionary to store devices
        self.vars = {}
        self.all_variables = set()  # Unified list of all variables across devices

        # Create instances for sensors on different ports (as in the original code)
        # Initialize devices dynamically from config
        for device_name, device_config in self.config['devices'].items():
            device_name = device_name.lower()
            if 'aeris' in device_name:
                device = Aeris(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode'],
                    inst_num=device_config['inst_num'],
                    verbose=self.verbose
                )
            elif device_name == 'o3_sensor':
                device = O3_2Btech(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode'],
                    verbose=self.verbose
                )
                self.pressure_var = f'{device_config["data_var_prefix"]}p'
            elif device_name == 'h2o_sensor':
                device = Maycomm(
                    port=device_config['serial_port'],
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode'],
                    verbose=self.verbose
                )
            elif device_name == 'labjack':
                device = LabJackController(
                    config_file=self.config_file,
                    prefix=device_config['data_var_prefix'],
                    sim_mode=device_config['sim_mode']
                )
            else:
                raise ValueError(f"Unknown device type: {device_name}")
            
            # Connect device and initialize stream
            device.connect()
            self.devices[device_name] = device
            self.streams[device_name] = pd.DataFrame()

            # Store prefixed variables in self.all_variables instead of modifying the device instance
            self.vars[device_name] = [
                f"{device_config['data_var_prefix']}{v}" for v in device.variables if "unused" not in v.lower()
            ]
            self.all_variables.update(self.vars[device_name])

        # Convert the set of variables to a sorted list for consistency
        self.all_variables = ['datetime'] + sorted(self.all_variables)

        # Initialize the display panel
        self.display_panel = DisplayPanel(config_file, self.devices)
        self.setCentralWidget(self.display_panel)

        # load pressure trigger points
        for event, value in self.config['triggers'].items():
            if event == 'alt_high':
                self.alt_high = value
            elif event == 'alt_low':
                self.alt_low = value
        
        # Load existing data if the CSV file already exists
        if os.path.exists(self.file_path):
            previous_data = pd.read_csv(self.file_path, parse_dates=['datetime'])
            self.last_saved_datetime = previous_data['datetime'].max()
            del previous_data  # remove from memory
        else:
            self.last_saved_datetime = None

        time.sleep(2)
        
        # Timer for periodic data collection
        self.timer = QTimer()
        self.timer.timeout.connect(self.collect_data)

        # start pilot light and pressure triggers
        threading.Thread(target=self.pilot_light, daemon=True).start()
        threading.Thread(target=self.pilot_off_switch, daemon=True).start()
        threading.Thread(target=self.altitude_monitor, daemon=True).start()

    def load_config(self, file_path='config.yaml'):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def create_filename(self, prefix="ucatsb"):
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
        # update variables like self.pressure that are from sensors.
        for device_name, device in self.devices.items():
            try:
                data = device.get_all_data()
                #print(device_name, data)
                self.streams[device_name] = pd.concat(
                    [self.streams[device_name], pd.DataFrame(data)], ignore_index=True
                )

                # Update the display panel with the latest data
                self.display_panel.update_display_data(device_name, data[-1])
                if device_name == 'aeris_co2':
                    self.display_panel.update_time(data[-1])

                # Handle pressure updates for the O3 sensor
                if device_name == "o3_sensor":
                    self.pressure = float(data[0].get(self.pressure_var, float("nan")))
                    if self.pressure > self.alt_high:
                        self.alt_high_event.set()
                        #print(f"Pressure of {self.pressure} mbar indicates descent or taxiing.")
                
                elif device_name == "labjack":
                    # pilot switch variable name with prefix from config file
                    switch = f"{self.config['devices']['Labjack']['data_var_prefix']}pilot_power"
                    self.pilot_switch = data[0].get(switch, float("nan"))

            except IndexError:
                pass

        # Merge all streams into a single DataFrame
        full_data = None
        for stream_name, stream in self.streams.items():
            if full_data is None:
                full_data = stream
            else:
                try:
                    full_data = pd.merge(full_data, stream, on='datetime', how='outer')
                except KeyError:
                    # no read or missing data
                    pass

        if full_data is not None:
            # Remove the last N rows
            full_data = pd.DataFrame(full_data).reindex(columns=self.all_variables)
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

    def pilot_light(self, cycle=1):
        # pilot fail light circuit
        # TODO: add more logic to handle the state of the sensors
        jack = self.devices["labjack"]
        pilot_wd_add = jack.get_labjack_address('pilot_wd')

        while True:
            jack.write_digital({pilot_wd_add: 0})
            time.sleep(cycle)
            jack.write_digital({pilot_wd_add: 1})
            time.sleep(cycle)

    def pilot_off_switch(self):
        """ If the pilot turns the switch to ucats-b off. Quickly shutdown.
            Start checking after the program has been running for 10 seconds or more.
        """
        elapsed_time = (datetime.now() - self.start_time).total_seconds()
        if elapsed_time < 10:
            return
        
        if self.pilot_switch == 0:
            # TODO: Should this value be 0 for more than 1 second?
            self.display_panel.shutdown()

    # pressure checks
    def altitude_monitor(self):
        time.sleep(5)   # wait a little to let everything startup
        while True:
            if self.pressure <= self.alt_high:  # Takeoff or ascending condition
                if not self.alt_high_event.is_set():
                    self.at_altitude()
            
            if self.pressure > self.alt_low:  # Landing or descending condition
                if not self.alt_low_event.is_set():
                    self.below_altitude()
            
            time.sleep(2)  # Polling interval

    def at_altitude(self):
        print("Plane has reached altitude.")
        jack = self.devices["labjack"]
        self.alt_low_event.clear()
        sol_cal_add = jack.get_labjack_address('sol_cal')
        sol_calair_add = jack.get_labjack_address('sol_aircal')

        while True:  # Stay in the loop until the plane descends
            # Solenoid cycling logic
            jack.write_digital({sol_cal_add: 1})
            print('sol cal/air high')
            self.extra_vars['sol_cal'] = 1
            if self.alt_high_event.wait(10):
                break
            jack.write_digital({sol_cal_add: 0})
            self.extra_vars['sol_cal'] = 0
            print('sol cal/air low')
            if self.alt_high_event.wait(10):
                break

        print("Exiting cruising altitude actions.")
        self.alt_high_event.clear()  # Clear the high-altitude event

    def below_altitude(self):
        print("Plane is descending or taxiing.")
        jack = self.devices["labjack"]
        sol_cal_add = jack.get_labjack_address('sol_cal')
        self.alt_high_event.clear()
        self.alt_low_event.set()
        # Perform actions during descent or post-landing
        jack.write_digital({sol_cal_add: 0})
        self.extra_vars['sol_cal'] = 0

def main():
    # Create the argument parser
    parser = ArgumentParser(description="Run TDL Package for data collection.")
    parser.add_argument("--config", type=str, default='config.yaml', help="Path to the configuration YAML file. (default=config.yaml)")
    parser.add_argument('-v', '--verbose', action='store_true', help="Prints some extra info to stdout.")
    parser.add_argument('-t', '--time', type=int, help="Duration to run the data collection (in seconds).", default=None)

    # Parse the arguments
    args = parser.parse_args()

    app = QApplication(sys.argv)

    # Create the TDL_package instance with the provided stream size
    package = TDL_package(config_file=args.config, verbose=args.verbose)
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
