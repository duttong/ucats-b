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


class AcquisitionClock:
    """Describe when each final data row was acquired, even if NTP changes time.

    The computer supplies two different measures of time:

    * Wall time is the familiar date and time written in ``datetime``. NTP or
      GPS synchronization can move this clock forward or backward.
    * Monotonic time behaves like a stopwatch. It advances steadily while the
      computer is running and is not adjusted by NTP. Its zero point is
      arbitrary, so only differences between ``monotonic_ns`` values have
      physical meaning.

    For each final CSV row, :meth:`observe` records both clocks and a sequential
    ``sample_id``. It compares the elapsed wall time with the elapsed monotonic
    time. If they differ by at least ``jump_threshold_seconds`` (5 seconds by
    default), the row starts a new ``clock_epoch`` and ``clock_jump_s`` records
    the signed discrepancy. A positive discrepancy means wall time jumped
    forward; a negative discrepancy means it jumped backward.

    The class detects and describes a clock change; it does not decide which
    clock epoch has the correct UTC time. During post-flight processing, a row
    with trusted UTC can be used as an anchor. Times for other rows in the same
    uninterrupted computer run can then be reconstructed from their difference
    in ``monotonic_ns``. A computer reboot resets the monotonic clock, so a
    program restart is deliberately assigned a new epoch when an existing CSV
    is resumed.

    ``next_sample_id`` and ``clock_epoch`` allow acquisition to continue an
    existing compatible CSV without repeating identifiers.
    """

    def __init__(self, jump_threshold_seconds=5.0, next_sample_id=0, clock_epoch=0):
        self.jump_threshold_seconds = jump_threshold_seconds
        self.next_sample_id = next_sample_id
        self.clock_epoch = clock_epoch
        self.previous_wall_time = None
        self.previous_monotonic_ns = None

    def observe(self, wall_time=None, monotonic_ns=None):
        """Return timing metadata for one final data row.

        Supplying ``wall_time`` and ``monotonic_ns`` is useful for testing.
        Normal acquisition leaves them unspecified and reads both clocks here,
        at the beginning of the final-data collection cycle.
        """
        wall_time = wall_time or datetime.now()
        monotonic_ns = monotonic_ns if monotonic_ns is not None else time.monotonic_ns()
        clock_jump_seconds = None

        if self.previous_wall_time is not None:
            wall_elapsed = (wall_time - self.previous_wall_time).total_seconds()
            monotonic_elapsed = (monotonic_ns - self.previous_monotonic_ns) / 1_000_000_000
            clock_error = wall_elapsed - monotonic_elapsed
            if abs(clock_error) >= self.jump_threshold_seconds:
                self.clock_epoch += 1
                clock_jump_seconds = clock_error

        observation = {
            'datetime': wall_time,
            'sample_id': self.next_sample_id,
            'monotonic_ns': monotonic_ns,
            'clock_epoch': self.clock_epoch,
            'clock_jump_s': clock_jump_seconds,
        }
        self.next_sample_id += 1
        self.previous_wall_time = wall_time
        self.previous_monotonic_ns = monotonic_ns
        return observation


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

        # Final-output metadata precedes the instrument variables in the CSV.
        self.output_metadata = [
            'datetime', 'sample_id', 'monotonic_ns', 'clock_epoch', 'clock_jump_s'
        ]
        self.all_variables = self.output_metadata + sorted(self.all_variables)

        # Initialize the display panel
        self.display_panel = DisplayPanel(self.config_file, self.devices)
        self.setCentralWidget(self.display_panel)

        next_sample_id = 0
        clock_epoch = 0

        # Resume sequence metadata when restarting into a compatible CSV. Start a
        # new part if an older file has a different schema, rather than corrupting it.
        if os.path.exists(self.file_path):
            existing_columns = list(pd.read_csv(self.file_path, nrows=0).columns)
            if existing_columns != self.all_variables:
                previous_path = self.file_path
                self.file_path = self.next_part_filename(self.file_path)
                logger.warning(
                    f"Output schema differs from {previous_path}; writing {self.file_path}"
                )
                self.last_saved_datetime = None
            else:
                previous_data = pd.read_csv(
                    self.file_path,
                    usecols=['datetime', 'sample_id', 'clock_epoch'],
                    parse_dates=['datetime'],
                )
                self.last_saved_datetime = previous_data['datetime'].max()
                if not previous_data.empty:
                    next_sample_id = int(previous_data['sample_id'].max()) + 1
                    # A process restart begins a new correction segment because
                    # there is no continuous wall/monotonic comparison across it.
                    clock_epoch = int(previous_data['clock_epoch'].max()) + 1
                del previous_data
        else:
            self.last_saved_datetime = None

        self.acquisition_clock = AcquisitionClock(
            next_sample_id=next_sample_id,
            clock_epoch=clock_epoch,
        )

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

    def next_part_filename(self, file_path):
        root, extension = os.path.splitext(file_path)
        part = 2
        while os.path.exists(f"{root}-part{part}{extension}"):
            part += 1
        return f"{root}-part{part}{extension}"

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
        clock_observation = self.acquisition_clock.observe()
        if clock_observation['clock_jump_s'] is not None:
            logger.warning(
                "System clock step detected: %+.3f s; starting clock epoch %d",
                clock_observation['clock_jump_s'],
                clock_observation['clock_epoch'],
            )

        # Fetch data and append to respective streams
        # update variables like self.pressure that are from sensors.
        latest_data = {}
        for device_name, device in self.devices.items():
            try:
                data = device.get_all_data()
                self.streams[device_name] = pd.concat(
                    [self.streams[device_name], pd.DataFrame(data)], ignore_index=True
                )

                # Update the display panel with the most recent data
                self.display_panel.update_display_data(device_name, data[-1])
                self.display_panel.update_time_clocktime()
                latest_data.update({
                    key: value for key, value in data[-1].items() if key != 'datetime'
                })

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

        # Write one final snapshot per acquisition tick. Instrument packet times
        # remain available in the rolling streams, but cannot control output order.
        output_row = clock_observation | latest_data
        lastline = pd.DataFrame([output_row]).reindex(columns=self.all_variables)
        lastline.to_csv(
            self.file_path,
            mode='a',
            index=False,
            header=not os.path.exists(self.file_path),
        )
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
            a2 = self.streams['aeris_ch4']
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
        self.display_panel.pumps_on()
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
    logger.info("UCATS-B starting")

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
