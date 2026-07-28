import sys
import time
import logging
import yaml
import datetime
import subprocess
import threading
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QApplication, QMessageBox
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer

logger = logging.getLogger(__name__)

class PilotIndicator(QLabel):
    """ Pilot fail light indecator. This will flash between yellow and blue
        if the watchdog is working. """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)  # Small circular indicator
        self.setAutoFillBackground(True)
        self.update_indicator(0)  # Default to yellow

    def update_indicator(self, value):
        color = "yellow" if value == 0 else "LightSkyBlue"
        self.setStyleSheet(f"background-color: {color}; border: 1px solid black;")

class DisplayPanel(QWidget):
    CAL_DURATION_STEP = 5           # seconds per button press
    CAL_DURATION_MIN = 5
    CAL_DURATION_MAX = 120
    CAL_DURATION_LOCKOUT_LEAD = 5   # lock edits this many seconds before a cal starts

    def __init__(self, config_file, devices=None):
        super().__init__()
        self.config_file = config_file
        self.config = self.load_config(config_file)
        self.devices = devices
        # Runtime cal duration. Seeded from config here and never re-read from it, so an
        # operator's change sticks for every following cal until the app restarts.
        # -/+ edit cal_duration_pending; nothing reaches the sequence until Save, so a
        # stray button press can't change what the next cal actually runs.
        self.cal_duration = int(float(self.config['triggers'].get('cal_duration', 40)))
        self.cal_duration_pending = None
        self.cal_duration_locked = False
        logger.info(f"Cal duration initialized to {self.cal_duration}s from config")
        self.sequence_event = threading.Event()
        self.sequence_timer = QTimer()
        self.sequence_timer.timeout.connect(self._sequence_tick)
        self.sequence_step = 0
        self.sequence_remaining = 0
        self.sequence_label = ""
        self.button_font = "font-size: 16px;"
        self.start_time = datetime.datetime.now()
        self.initUI()

    def load_config(self, file_path='config.yaml'):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            config = yaml.safe_load(file)
            config = self.lowercase_keys(config)
            return config
    
    def lowercase_keys(self, data):
        if isinstance(data, dict):
            return {k.lower(): self.lowercase_keys(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.lowercase_keys(i) for i in data]
        else:
            return data

    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)  # Adjust margins
        layout.setSpacing(12)  # Spacing between sections

        self.data_labels = {}  # Store labels to update later

        # === Top Section: Date/Time & Pilot Indicator ===
        top_layout = QHBoxLayout()

        # Date/Time Label
        self.time_label = QLabel()
        self.update_time_clocktime()
        top_layout.addWidget(self.time_label, alignment=Qt.AlignLeft)

        # Pilot Indicator
        self.pilot_indicator = PilotIndicator(self)
        top_layout.addWidget(self.pilot_indicator, alignment=Qt.AlignRight)

        # Add the top section to the main layout
        layout.addLayout(top_layout)

        # === Device Grid Layout ===
        grid = QGridLayout()
        grid.setSpacing(10)  # Adjust spacing between rows

        row = [0, 0, 0, 0, 0]
        for device_name, device_info in self.config['devices'].items():
            device_name = device_name.lower()
            if not device_info.get('display_vars'):
                continue

            # set the columns in the display where the device is shown
            colinc = 0
            if device_name in ["aeris_ch4", "h2o_sensor"]:
                colinc = 2
            elif device_name in ["labjack"]:
                colinc = 4

            # Device label with larger font and bold style
            device_label = QLabel(f"{device_name}")
            device_label.setFont(QFont('Arial', 16, QFont.Bold))
            device_label.setStyleSheet("color: #2E8B57;")  # Optional: Set color
            grid.addWidget(device_label, row[colinc], colinc, 1, 2)  # Span across 2 columns
            row[colinc] += 1

            prefix = self.config['devices'][device_name]['data_var_prefix']

            # Add labels for each variable
            for var in device_info['display_vars']:
                if var == 'blank':
                    var_label = QLabel("")
                else:
                    var_label = QLabel(f"   {prefix}{var}: ")
                var_label.setFont(QFont('Arial', 14))
                grid.addWidget(var_label, row[colinc], 0+colinc, alignment=Qt.AlignLeft)

                if var == 'blank':
                    value_label = QLabel(" ")
                else:
                    value_label = QLabel("N/A")
                
                value_label.setFont(QFont('Arial', 14))
                value_label.setStyleSheet("color: #11e;")  # Optional: Blue color for value
                grid.addWidget(value_label, row[colinc], 1+colinc, alignment=Qt.AlignRight)

                self.data_labels[f"{device_name}_{prefix}{var}"] = value_label
                row[colinc] += 1

        # === Cal duration adjuster ===
        cal_dur_label = QLabel("   cal_duration: ")   # leading spaces match the var labels
        cal_dur_label.setFont(QFont('Arial', 14, QFont.Bold))
        cal_dur_label.setStyleSheet("color: black;")

        self.cal_duration_value = QLabel(f"{self.cal_duration} s")
        self.cal_duration_value.setFont(QFont('Arial', 14))
        self.cal_duration_value.setStyleSheet("color: #11e;")
        self.cal_duration_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Pre-size to the widest string this label can ever hold ("120 → 120 s"), so
        # switching between committed and pending text can't resize anything around it.
        fm = self.cal_duration_value.fontMetrics()
        advance = getattr(fm, 'horizontalAdvance', fm.width)
        self.cal_duration_value.setFixedWidth(
            advance(f"{self.CAL_DURATION_MAX} → {self.CAL_DURATION_MAX} s") + 8)

        # The :disabled rule is required -- a flat background-color overrides Qt's own
        # greyed-out rendering, so a locked button would otherwise still look pressable.
        disabled_style = "QPushButton:disabled {background-color: #E0E0E0; color: #909090;}"
        cal_dur_style = (
            f"QPushButton {{background-color: #FFCCCC; color: black;"
            f" border: 1px solid #CC9999; {self.button_font}}}{disabled_style}")
        cal_save_style = (
            f"QPushButton {{background-color: DarkSeaGreen; color: black;"
            f" border: 1px solid #CC9999; {self.button_font}}}{disabled_style}")

        cal_dur_layout = QHBoxLayout()
        self.cal_dur_minus = QPushButton("−")
        self.cal_dur_minus.setStyleSheet(cal_dur_style)
        self.cal_dur_minus.clicked.connect(
            lambda: self.adjust_cal_duration(-self.CAL_DURATION_STEP))

        self.cal_dur_plus = QPushButton("+")
        self.cal_dur_plus.setStyleSheet(cal_dur_style)
        self.cal_dur_plus.clicked.connect(
            lambda: self.adjust_cal_duration(self.CAL_DURATION_STEP))

        cal_dur_layout.addWidget(self.cal_dur_minus)
        cal_dur_layout.addWidget(self.cal_dur_plus)

        cal_commit_layout = QHBoxLayout()
        self.cal_dur_save = QPushButton("Save")
        self.cal_dur_save.setStyleSheet(cal_save_style)
        self.cal_dur_save.clicked.connect(self.save_cal_duration)

        self.cal_dur_cancel = QPushButton("Cancel")
        self.cal_dur_cancel.setStyleSheet(cal_dur_style)
        self.cal_dur_cancel.clicked.connect(self.cancel_cal_duration)

        cal_commit_layout.addWidget(self.cal_dur_save)
        cal_commit_layout.addWidget(self.cal_dur_cancel)

        self._refresh_cal_duration()   # Save/Cancel start disabled -- nothing pending yet

        # Sit in the labjack column (cols 4-5), bottom-aligned with the longest device
        # column so the three rows land beside its last variables rather than below
        # everything -- no dead space to the left of the block. max(row[4], ...) keeps
        # it clear of the labjack variables if that column ever grows.
        cal_row = max(row[4], max(row) - 3)
        grid.addWidget(cal_dur_label, cal_row, 4, alignment=Qt.AlignLeft)
        grid.addWidget(self.cal_duration_value, cal_row, 5, alignment=Qt.AlignRight)
        grid.addLayout(cal_dur_layout, cal_row + 1, 4, 1, 2)
        grid.addLayout(cal_commit_layout, cal_row + 2, 4, 1, 2)

        # Add the device grid below the date/time and pilot indicator, then let any
        # leftover height fall between the grid and the Sequence button.
        layout.addLayout(grid)
        layout.addStretch(1)

        # === Buttons Section ===
        self.sequence_button = QPushButton("Sequence Idle")
        self.sequence_button.setStyleSheet(
            f"background-color: LightGray; color: Black; border: 1px solid #999; {self.button_font}")
        self.sequence_button.setCheckable(True)
        self.sequence_button.setChecked(True)
        self.sequence_button.clicked.connect(self.sequence_run)
        layout.addWidget(self.sequence_button)

        sol_layout = QHBoxLayout()
        self.sol1 = QPushButton("Cal0/Cal1")
        self.sol1.setCheckable(True)
        self.sol1.clicked.connect(self.sol_cals)
        self.sol1.setStyleSheet(
            f"background-color: #FF9999; color: black; border: 1px solid #CC9999;{self.button_font}")

        self.sol2 = QPushButton("Air/Cal")
        self.sol2.setCheckable(True)
        self.sol2.clicked.connect(self.sol_aircal)
        self.sol2.setStyleSheet(
            f"background-color: #FF9999; color: black; border: 1px solid #CC9999; {self.button_font}")

        self.pumps_tog = QPushButton("Pumps Off")
        self.pumps_tog.setCheckable(True)
        self.pumps_tog.clicked.connect(self.pumps_onoff)
        self.pumps_tog.setStyleSheet(
            f"background-color: #FF9999; color: black; border: 1px solid #CC9999; {self.button_font}")

        sol_layout.addWidget(self.pumps_tog)
        sol_layout.addWidget(self.sol1)
        sol_layout.addWidget(self.sol2)
        layout.addLayout(sol_layout)

        cmd_layout = QHBoxLayout()
        self.co2_reboot_button = QPushButton("Aeris CO2 cmd")
        self.co2_reboot_button.clicked.connect(self.show_co2_options)
        self.co2_reboot_button.setStyleSheet(
            f"background-color: #FFCCCC; color: black; border: 1px solid #CC9999; {self.button_font}"
        )
        
        self.co_reboot_button = QPushButton("Aeris CH4 cmd")
        self.co_reboot_button.clicked.connect(self.show_co_options)
        self.co_reboot_button.setStyleSheet(
            f"background-color: #FFCCCC; color: black; border: 1px solid #CC9999; {self.button_font}"
        )

        # Shutdown Button
        self.shutdown_trigger = QPushButton("SHUTDOWN")
        self.shutdown_trigger.clicked.connect(self.shutdown_menu)
        self.shutdown_trigger.setStyleSheet(
            f"background-color: DarkRed; color: white; border: 1px solid #CC9999; {self.button_font}")

        cmd_layout.addWidget(self.co2_reboot_button)
        cmd_layout.addWidget(self.co_reboot_button)
        cmd_layout.addWidget(self.shutdown_trigger)
        layout.addLayout(cmd_layout)

        self.setLayout(layout)

    def update_time(self, data):
        """ uses datetime in the data packet """
        packet_time = data['datetime'].strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.setText(f"{packet_time}")
        self.time_label.setFont(QFont('Arial', 20, QFont.Bold))  # Bold current time display
        self.time_label.setStyleSheet("color: #000000;")  # Black color for current time

    import datetime

    def update_time_clocktime(self):
        """Uses the Pi clock time and shows elapsed time since the program started with a smaller font."""
        current_time = datetime.datetime.now()
        formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

        # Calculate elapsed time
        elapsed_time = current_time - self.start_time
        elapsed_str = str(elapsed_time).split(".")[0]  # Remove microseconds

        # Use HTML formatting for different font sizes
        display_text = (
            f"<span style='font-size: 20px; font-weight: bold; color: #000000;'>"
            f"Current Time: {formatted_time}</span><br>"
            f"<span style='font-size: 18px; color: #000000;'>Elapsed Time: {elapsed_str}</span>"
        )

        # Update label with formatted text
        self.time_label.setText(display_text)

    def update_display_data(self, device_name, data):
        """ Update the display with new data for a given device. """

        # Update pilot indicator based on pilot_wd
        if device_name == 'labjack':
            prefix = self.config['devices'][device_name]['data_var_prefix']
            pilot_wd_value = data.get(f"{prefix}pilot_wd", 0)  # Default to 0 if missing
            #pilot_wd_value = datetime.datetime.now().second % 2 == 0
            self.pilot_indicator.update_indicator(pilot_wd_value)

        for var_name, var_value in data.items():
            # Construct the key used to store labels (device name + variable name)
            label_key = f"{device_name}_{var_name}"
            if label_key in self.data_labels:
                if isinstance(var_value, float):
                    if "CH4" in var_name:
                        formatted_value = "{:7.1f}".format(var_value)
                    elif "H2O" in var_name:
                        formatted_value = "{:7.0f}".format(var_value)
                    else:
                        formatted_value = "{:7.2f}".format(var_value)
                else:
                    formatted_value = str(var_value)
                self.data_labels[label_key].setText(formatted_value)

    def show_menu(self, sensor_type):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(f"{sensor_type} Control")
        msg.setText(f"Choose an action for {sensor_type}")
        cancel_button = msg.addButton("Cancel", QMessageBox.AcceptRole)
        reboot_button = msg.addButton("Reboot", QMessageBox.RejectRole)
        shutdown_button = msg.addButton("Shutdown", QMessageBox.DestructiveRole)
        msg.exec_()

        if msg.clickedButton() == reboot_button:
            cmd = "reboot"
            if sensor_type == "Aeris CO2":
                self.aeris_command("aeris_co2", cmd)
            else:
                self.aeris_command("aeris_ch4", cmd)
        elif msg.clickedButton() == shutdown_button:
            cmd = "shutdown"
            if sensor_type == "Aeris CO2":
                self.aeris_command("aeris_co2", cmd)
            else:
                self.aeris_command("aeris_ch4", cmd)

    def show_co2_options(self):
        self.show_menu("Aeris CO2")

    def show_co_options(self):
        self.show_menu("Aeris CH4")

    # Entry function for Aeris CO2 Reboot button
    def aeris_command(self, device_name, command):
        try:
            aeris_device = self.devices.get(device_name)
        except AttributeError:
            logger.info("This is a display demo, there are no active devices.")
            return
        if aeris_device:
            aeris_device.send_command(command)
            logger.info(f"Aeris {device_name} {command} command sent!")
        else:
            logger.warning(f"Aeris {device_name} device not found!")

    def pumps_onoff(self):
        self.pumps_on() if self.pumps_tog.isChecked() else self.pumps_off()

    def pumps_on(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('pumps')
        logger.info("Pumps on")
        # keep the toggle state in sync for programmatic callers (at_altitude)
        self.pumps_tog.setChecked(True)
        self.pumps_tog.setText("Pumps On")
        self.pumps_tog.setStyleSheet(
            f"background-color: #99FF99; color: black; border: 1px solid #CC9999; {self.button_font}")  
        jack.write_digital({dig: 1})
    
    def pumps_off(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('pumps')
        logger.info("Pumps off")
        # keep the toggle state in sync for programmatic callers (below_altitude, shutdown)
        self.pumps_tog.setChecked(False)
        self.pumps_tog.setText("Pumps Off")
        self.pumps_tog.setStyleSheet(
            f"background-color: #FF9999; color: black; border: 1px solid #CC9999; {self.button_font}")  
        jack.write_digital({dig: 0})

    def adjust_cal_duration(self, delta):
        """ Step the *pending* cal duration by delta seconds, clamped to the allowed range.
            Nothing reaches the sequence until save_cal_duration(). """
        if self.cal_duration_locked:
            return
        base = self.cal_duration if self.cal_duration_pending is None else self.cal_duration_pending
        new = min(max(base + delta, self.CAL_DURATION_MIN), self.CAL_DURATION_MAX)
        if new == base:
            logger.info(f"Cal duration unchanged at {base}s "
                        f"(limit {self.CAL_DURATION_MIN}-{self.CAL_DURATION_MAX}s)")
            return
        # Stepping back onto the committed value clears the pending edit entirely.
        self.cal_duration_pending = None if new == self.cal_duration else new
        self._refresh_cal_duration()

    def save_cal_duration(self):
        """ Commit the pending cal duration. Applies to every cal that follows until
            changed again or the app restarts. """
        if self.cal_duration_pending is None:
            return
        old, new = self.cal_duration, self.cal_duration_pending
        self.cal_duration = new
        self.cal_duration_pending = None
        self._refresh_cal_duration()
        logger.info(f"Cal duration changed: {old}s -> {new}s (applies to all following cals)")

    def cancel_cal_duration(self):
        """ Discard the pending cal duration and go back to the committed value. """
        if self.cal_duration_pending is None:
            return
        logger.info(f"Cal duration edit cancelled ({self.cal_duration_pending}s discarded), "
                    f"staying at {self.cal_duration}s")
        self.cal_duration_pending = None
        self._refresh_cal_duration()

    def _refresh_cal_duration(self):
        """ Redraw the readout and set which of the four buttons are pressable. """
        pending = self.cal_duration_pending
        if pending is None:
            self.cal_duration_value.setText(f"{self.cal_duration} s")
            self.cal_duration_value.setStyleSheet("color: #11e;")
        else:
            self.cal_duration_value.setText(f"{self.cal_duration} → {pending} s")
            self.cal_duration_value.setStyleSheet("color: #d35400; font-weight: bold;")

        unlocked = not self.cal_duration_locked
        self.cal_dur_minus.setEnabled(unlocked)
        self.cal_dur_plus.setEnabled(unlocked)
        self.cal_dur_save.setEnabled(unlocked and pending is not None)
        self.cal_dur_cancel.setEnabled(unlocked and pending is not None)

    def _set_cal_duration_enabled(self, enabled, reason=""):
        """ Lock/unlock the cal duration controls. Idempotent so the per-tick calls from
            _sequence_tick don't flood the log. Locking discards any unsaved edit, so a
            value staged and forgotten can never be committed later against stale intent. """
        if self.cal_duration_locked != enabled:
            return
        self.cal_duration_locked = not enabled
        if not enabled and self.cal_duration_pending is not None:
            logger.warning(f"Unsaved cal duration change ({self.cal_duration_pending}s) discarded "
                           f"at lock; staying at {self.cal_duration}s")
            self.cal_duration_pending = None
        self._refresh_cal_duration()
        logger.info(f"Cal duration control {'unlocked' if enabled else 'locked'}{reason}")

    def sol_cals(self):
        self.cal1() if self.sol1.isChecked() else self.cal0()

    def sol_aircal(self):
        self.air() if self.sol2.isChecked() else self.cals()

    # The methods below can be called from instrument.py and will change the state of buttons.
    def cal0(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_cals')
        self.sol1.setText("Cal 0")
        self.sol1.setStyleSheet(
            f"background-color: DarkSeaGreen; color: black; border: 1px solid #CC9999; {self.button_font}")  
        self.sol1.setChecked(False)
        jack.write_digital({dig: 0})

    def cal1(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_cals')
        self.sol1.setText("Cal 1")
        self.sol1.setStyleSheet(
            f"background-color: DodgerBlue; color: White; border: 1px solid #CC9999; {self.button_font}")  
        self.sol1.setChecked(True)
        jack.write_digital({dig: 1})

    def cals(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_aircal')
        self.sol2.setText("Cal")
        self.sol2.setStyleSheet(
            f"background-color: DodgerBlue; color: White; border: 1px solid #CC9999; {self.button_font}")
        self.sol2.setChecked(False)
        self._set_cal_duration_enabled(False, " (cal gas flowing)")
        jack.write_digital({dig: 1})

    def air(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_aircal')
        self.sol2.setText("Air")
        self.sol2.setStyleSheet(
            f"background-color: DarkSeaGreen; color: black; border: 1px solid #CC9999; {self.button_font}")
        self.sol2.setChecked(True)
        self._set_cal_duration_enabled(True)
        jack.write_digital({dig: 0})

    def sequence_run(self):
        # Qt already toggled sequence_button's checked state before this handler ran.
        if self.sequence_button.isChecked():
            if self._confirm("Stop Sequence", "Stop the cal/air sequence?", "Stop"):
                self.sequence_idle()
            else:
                self.sequence_button.setChecked(False)
        else:
            if self._confirm("Start Sequence", "Start the cal/air sequence?", "Start"):
                self.sequence_start()
            else:
                self.sequence_button.setChecked(True)

    def _confirm(self, title, text, accept_label):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        accept_button = msg.addButton(accept_label, QMessageBox.AcceptRole)
        msg.exec_()
        return msg.clickedButton() == accept_button

    def sequence_start(self):
        air_s = int(float(self.config['triggers'].get('air_duration', 300)))
        logger.info(f"Cal/air sequence started (cal {self.cal_duration}s, air {air_s}s)")
        self.sequence_event.clear()
        self.sequence_button.setChecked(False)
        self.sequence_button.setStyleSheet(
            f"background-color: DarkSeaGreen; color: Black; border: 1px solid #CC9999; {self.button_font}")
        self.sequence_step = -1
        self._sequence_advance()
        self.sequence_timer.start(1000)

    def _sequence_advance(self):
        air_s = int(float(self.config['triggers'].get('air_duration', 300)))
        cal_s = self.cal_duration   # operator-adjustable, read fresh on every transition

        self.sequence_step = (self.sequence_step + 1) % 4

        if self.sequence_step == 0:
            self.cals()
            self.cal0()
            self.sequence_remaining = cal_s
            self.sequence_label = "Cal 0"
        elif self.sequence_step == 1:
            self.air()
            self.cal0()
            self.sequence_remaining = air_s
            self.sequence_label = "Air"
        elif self.sequence_step == 2:
            self.cals()
            self.cal1()
            self.sequence_remaining = cal_s
            self.sequence_label = "Cal 1"
        else:
            self.air()
            self.cal0()
            self.sequence_remaining = air_s
            self.sequence_label = "Air"

        self.sequence_button.setText(
            f"Running Sequence: {self.sequence_label} ({self.sequence_remaining}s)")
        logger.info(f"Cal/air sequence advanced to {self.sequence_label} ({self.sequence_remaining}s)")

    def _sequence_tick(self):
        if self.sequence_event.is_set():
            self.sequence_idle()
            return
        self.sequence_remaining -= 1
        if self.sequence_remaining <= 0:
            self._sequence_advance()
        else:
            # Every air step is followed by a cal step, so no "is the next step a cal?"
            # test is needed -- during a cal step this is already locked and no-ops.
            if self.sequence_remaining <= self.CAL_DURATION_LOCKOUT_LEAD:
                self._set_cal_duration_enabled(
                    False, f" (cal starts in {self.CAL_DURATION_LOCKOUT_LEAD}s)")
            self.sequence_button.setText(
                f"Running Sequence: {self.sequence_label} ({self.sequence_remaining}s)")

    def sequence_idle(self):
        logger.info("Cal/air sequence set to idle")
        self.sequence_timer.stop()
        self.sequence_event.set()
        self.air()
        self.cal0()
        self.sequence_button.setChecked(True)
        self.sequence_button.setText("Sequence Idle")
        self.sequence_button.setStyleSheet(
            f"background-color: LightGray; color: Black; border: 1px solid #999; {self.button_font}")

    def shutdown_menu(self, sensor_type):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle(f"Shutdown UCATS-B")
        msg.setText("Cancel or start Shutdown")
        cancel_button = msg.addButton("Cancel", QMessageBox.AcceptRole)
        shutdown_button = msg.addButton("Shutdown", QMessageBox.DestructiveRole)
        msg.exec_()

        if msg.clickedButton() == shutdown_button:
            self.shutdown()

    def shutdown(self):
        logger.info("Shutdown initiated")

        # tell aeris instruments to shutdown
        self.aeris_command('aeris_co2', 'shutdown')
        self.aeris_command('aeris_ch4', 'shutdown')
        time.sleep(0.1)
        # Flush all log handlers before the OS halts
        logging.shutdown()
        # shutdown Raspberry Pi
        subprocess.run(["sudo", "shutdown", "-h", "now"])


if __name__ == "__main__":

    app = QApplication(sys.argv)
    panel = DisplayPanel('config.yaml')
    panel.show()
    sys.exit(app.exec_())