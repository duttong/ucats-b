#! /usr/bin/env python

import os
import sys
import time
import logging
import logging.handlers
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
from telemetry import Telemetry

logger = logging.getLogger(__name__)


def setup_logging(verbose=False):
    """Configure root logger: rotating file at data/ucats-b.log + stdout stream."""
    log_path = "data/ucats-b.log"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=20 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)


class TDL_package(QMainWindow):
    def __init__(self, config_file='config.yaml', stream_size=100, verbose=False):
        super().__init__()
        self.verbose = verbose
        self.config_file = config_file
        self.config = self.load_config(config_file)
        self.file_path = self.create_filename()
        self.pilot_switch = 1
        self.pressure_var = ''      # determined from o3_sensor
        self.pressure = 1200.0
        self.pilot_off_event = threading.Event()
        self.alt_high_event = threading.Event()     # above high alt threshold
        self.alt_low_event = threading.Event()      # below low alt threshold
        self.alt_high = float(self.config['triggers'].get('alt_high', 700))     # default 700 if missing
        self.alt_low = float(self.config['triggers'].get('alt_low', 800))       # default 800 if missing
        self.start_time = datetime.now()
        self.telemetry = Telemetry(config_file)

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
            time.sleep(.1)   # wait a little for each device
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
        self.display_panel = DisplayPanel(self.config_file, self.devices)
        self.setCentralWidget(self.display_panel)

        # Load existing data if the CSV file already exists
        if os.path.exists(self.file_path):
            previous_data = pd.read_csv(self.file_path, parse_dates=['datetime'])
            self.last_saved_datetime = previous_data['datetime'].max()
            del previous_data  # remove from memory
        else:
            self.last_saved_datetime = None

        # Timer for periodic data collection
        self.timer = QTimer()
        self.timer.timeout.connect(self.collect_data)

        # start pilot light and pressure triggers
        self.initial_states()
        threading.Thread(target=self.pilot_fail_light, daemon=True).start()

        # Pilot-off and altitude checks run on the GUI thread via QTimer
        # so their display_panel calls don't cross thread boundaries.
        self.pilot_low_since = None
        self.pilot_timer = QTimer()
        self.pilot_timer.timeout.connect(self.check_pilot_switch)
        QTimer.singleShot(10000, self.start_pilot_timer)

        self.alt_high_count = 0
        self.alt_low_count = 0
        self.alt_timer = QTimer()
        self.alt_timer.timeout.connect(self.check_altitude)
        QTimer.singleShot(5000, lambda: self.alt_timer.start(2000))

    def load_config(self, file_path='config.yaml'):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            c = yaml.safe_load(file)
            c = self.lowercase_keys(c)
            return c
        
    def lowercase_keys(self, data):
        if isinstance(data, dict):
            return {k.lower(): self.lowercase_keys(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.lowercase_keys(i) for i in data]
        else:
            return data

    def create_filename(self, prefix="ucatsb"):
        # Get the current date and hour
        current_time = datetime.now()
        # Format the filename as "{prefix}-YYYYMMDDHH.csv"
        filename = f"data/{prefix}-{current_time.strftime('%Y%m%d%H')}.csv"
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        return filename

    def start_collection(self, run_duration=None):
        # Start data collection for all devices dynamically
        for device_name, device in self.devices.items():
            device.start_data_collection()

        # Start the timer to collect data every 1 second
        self.timer.start(950)

        if run_duration is not None:
            # Stop collection after run_duration seconds
            QTimer.singleShot(run_duration * 1000, self.stop_collection)

    def collect_data(self):
        # Fetch data and append to respective streams
        # update variables like self.pressure that are from sensors.
        for device_name, device in self.devices.items():
            try:
                data = device.get_all_data()
                self.streams[device_name] = pd.concat(
                    [self.streams[device_name], pd.DataFrame(data)], ignore_index=True
                )

                # Update the display panel with the most recent data
                self.display_panel.update_display_data(device_name, data[-1])
                self.display_panel.update_time_clocktime()

                # Handle pressure updates for the O3 sensor
                if device_name == "o3_sensor":
                    self.pressure = float(data[0].get(self.pressure_var, float("nan")))
                
                elif device_name == "labjack":
                    # pilot switch variable name with prefix from config file
                    prefix = self.config['devices']['labjack']['data_var_prefix']
                    switch = f"{prefix}pilot_power"
                    self.pilot_switch = data[0].get(switch, 1)

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
                    # No read or missing data
                    full_data = None

        if full_data is not None:
            # Remove the last N rows
            full_data = pd.DataFrame(full_data).reindex(columns=self.all_variables)
            full_data = full_data[:-len(self.streams)]

            if not full_data.empty:
                # Save new data to CSV and send most recent data to telemetry
                lastline = full_data.tail(1)
                lastline.to_csv(self.file_path, mode='a', index=False, header=not os.path.exists(self.file_path))
                self.telemetry.send_data(lastline)

        # Limit the memory footprint for each stream
        for stream_name in self.streams.keys():
            self.streams[stream_name] = self.streams[stream_name].tail(self.stream_size)

    def stop_collection(self):
        # Stop data collection and disconnect devices
        self.timer.stop()
        for device_name, device in self.devices.items():
            device.stop_data_collection()
            device.disconnect()
        logger.info("Data collection stopped.")

    def lj_digout(self, variable, state):
        """ Send a state (0 or 1) to the labjack """
        jack = self.devices['labjack']
        address = jack.get_labjack_address(variable)
        jack.write_digital({address: state})

    def initial_states(self):
        self.pilot_off_event.clear()
        self.display_panel.cal0()
        self.display_panel.pumps_off()
        self.display_panel.air()
        self.display_panel.sequence_idle()

    def pilot_fail_light(self, cycle=1):
        """ pilot fail light circuit 
        
            The fail light has three stages of logic.
            0) Start with the fail light ON.
            1) Wait 5 second, check to see if the O3 sensor is up.
               If the sensor is on. Turn the fail light OFF
            2) Keep fail light off for aeris_wait seconds waiting for the Aeris instruements.
            3) Check Aeris instruments for data. No data for max_missing_data, turn fail light ON.
        """
        aeris_wait = 180        # time (s) to wait for Aeris instruments
        max_missing_data = 5    # Maximum allowed consecutive Aeris empty readings
        
        # fail light is on
        self.lj_digout('pilot_wd', 0)
        time.sleep(5)

        # wait until the O3 sensor reports data.
        # The fail light will be on at this point
        while True:
            o3 = self.streams['o3_sensor']
            if o3.empty == False:
                logger.info('Fail Light: O3 sensor up')
                break
            time.sleep(2)

        # turn the fail light off while the Aeris sensors come up.
        logger.info('Fail Light: Waiting for Aeris instruments')
        start_time = time.time()  # Record the start time
        while time.time() - start_time < aeris_wait:
            self.lj_digout('pilot_wd', 0)
            time.sleep(cycle)
            self.lj_digout('pilot_wd', 1)
            time.sleep(cycle)

        # Monitor Aeris and O3 sensors for data. If no data is received consecutively, trigger the fail condition.
        a1_empty_count = 0
        a2_empty_count = 0
        o3_empty_count = 0
        
        logger.info('Fail Light: Monitoring Aeris now')
        while True:
            # Watchdog signal
            self.lj_digout('pilot_wd', 0)
            time.sleep(cycle)
            self.lj_digout('pilot_wd', 1)
            time.sleep(cycle)

            # Read data from sensors
            a1 = self.streams['aeris_co2']
            a2 = self.streams['aeris_co']
            o3 = self.streams['o3_sensor']

            # Update empty count for sensors
            a1_empty_count = a1_empty_count + 1 if a1.empty else 0
            a2_empty_count = a2_empty_count + 1 if a2.empty else 0
            o3_empty_count = o3_empty_count + 1 if o3.empty else 0

            # Break loop if consecutive empty readings exceed threshold
            if a1_empty_count > max_missing_data or a2_empty_count > max_missing_data:
                logger.warning(f'Fail Light: Aeris offline #1 {a1_empty_count}, #2 {a2_empty_count}')
                break
            elif o3_empty_count > max_missing_data:
                logger.warning(f'Fail Light: O3 offline {o3_empty_count}')
                break

        # This is a failed condition. Don't toggle the pilot_wd line.
        logger.warning('Fail Light: ON')
        self.lj_digout('pilot_wd', 0)

    def start_pilot_timer(self):
        logger.info(f'Initial pilot switch check: {self.pilot_switch}')
        self.pilot_timer.start(100)

    def check_pilot_switch(self):
        if self.pilot_off_event.is_set():
            self.pilot_timer.stop()
            return
        if self.pilot_switch < 0.1:
            if self.pilot_low_since is None:
                self.pilot_low_since = time.time()
            elif time.time() - self.pilot_low_since >= 1:
                self.pilot_timer.stop()
                self.display_panel.shutdown()
        else:
            self.pilot_low_since = None

    def check_altitude(self):
        if self.pressure <= self.alt_high:
            self.alt_high_count += 1
            self.alt_low_count = 0
            if self.alt_high_count >= 3 and not self.alt_high_event.is_set():
                self.at_altitude()
        else:
            self.alt_high_count = 0

        if self.pressure > self.alt_low:
            self.alt_low_count += 1
            self.alt_high_count = 0
            if self.alt_low_count >= 3 and not self.alt_low_event.is_set():
                self.below_altitude()
        else:
            self.alt_low_count = 0

    def at_altitude(self):
        logger.info("Plane has reached altitude.")
        self.alt_low_event.clear()
        self.alt_high_event.set()
        self.display_panel.sequence_start()

    def below_altitude(self):
        logger.info("Plane is descending or taxiing.")
        self.alt_high_event.clear()
        self.alt_low_event.set()
        self.display_panel.sequence_idle()
        self.display_panel.pumps_off()

    def closeEvent(self, event):
        logger.info("Application is closing...")
        if hasattr(self, 'display_panel') and self.display_panel.sequence_event:
            self.display_panel.sequence_event.set()  # Stop any running sequence
        event.accept()  # Allow the application to close

def main():
    # Create the argument parser
    parser = ArgumentParser(description="Run TDL Package for data collection.")
    parser.add_argument("--config", type=str, default='config.yaml', help="Path to the configuration YAML file. (default=config.yaml)")
    parser.add_argument('-v', '--verbose', action='store_true', help="Prints some extra info to stdout.")
    parser.add_argument('-t', '--time', type=int, help="Duration to run the data collection (in seconds).", default=None)

    # Parse the arguments
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    app = QApplication(sys.argv)

    # Create the TDL_package instance with the provided stream size
    package = TDL_package(config_file=args.config, verbose=args.verbose)
    package.show()

    # Start the data collection with the specified duration
    if args.time is not None:
        logger.info(f"Starting data collection for {args.time} seconds.")
        package.start_collection(run_duration=args.time)
    else:
        logger.info("Starting data collection without a specified time duration.")
        package.start_collection()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
