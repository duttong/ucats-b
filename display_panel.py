import os
import sys
import time
import yaml
import datetime
import subprocess
import threading
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QApplication, QMessageBox
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtCore import Qt

class PilotIndicator(QLabel):
    """ Pilot fail light indecator. This will flash between yellow and blue
        if the watchdog is working. """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)  # Small circular indicator
        self.setAutoFillBackground(True)
        self.update_indicator(0)  # Default to yellow

    def update_indicator(self, value):
        color = QColor("yellow") if value == 0 else QColor("LightSkyBlue")
        palette = self.palette()
        palette.setColor(QPalette.Window, color)
        self.setPalette(palette)

class DisplayPanel(QWidget):
    def __init__(self, config_file, devices=None):
        super().__init__()
        self.config_file = config_file
        self.config = self.load_config(config_file)
        self.devices = devices
        self.sequence_event = threading.Event()
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

        row = [0, 0, 0]
        for device_name, device_info in self.config['devices'].items():
            device_name = device_name.lower()
            if not device_info.get('display_vars'):
                continue

            colinc = 0
            if device_name in ["aeris_co", "h2o_sensor"]:
                colinc = 2

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

        # Add the device grid below the date/time and pilot indicator
        layout.addLayout(grid)

        # === Buttons Section ===
        self.sequence_button = QPushButton("Idle")
        self.sequence_button.setCheckable(True)
        self.sequence_button.clicked.connect(self.sequence_run)
        layout.addWidget(self.sequence_button)

        sol_layout = QHBoxLayout()
        self.sol1 = QPushButton("Sol: Cal0/Cal1")
        self.sol1.setCheckable(True)
        self.sol1.clicked.connect(self.sol_cals)
        self.sol1.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")

        self.sol2 = QPushButton("Sol: Air/Cal")
        self.sol2.setCheckable(True)
        self.sol2.clicked.connect(self.sol_aircal)
        self.sol2.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")

        sol_layout.addWidget(self.sol1)
        sol_layout.addWidget(self.sol2)
        layout.addLayout(sol_layout)

        self.pumps_tog = QPushButton("Pumps Off")
        self.pumps_tog.setCheckable(True)
        self.pumps_tog.clicked.connect(self.pumps_onoff)
        self.pumps_tog.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")
        layout.addWidget(self.pumps_tog)

        aeris_layout = QHBoxLayout()
        self.co2_reboot_button = QPushButton("Aeris CO2 cmd")
        self.co2_reboot_button.clicked.connect(self.show_co2_options)
        self.co2_reboot_button.setStyleSheet(
            "background-color: #FFCCCC; color: black; border: 1px solid #CC9999;"
        )
        
        self.co_reboot_button = QPushButton("Aeris CO cmd")
        self.co_reboot_button.clicked.connect(self.show_co_options)
        self.co_reboot_button.setStyleSheet(
            "background-color: #FFCCCC; color: black; border: 1px solid #CC9999;"
        )
        aeris_layout.addWidget(self.co2_reboot_button)
        aeris_layout.addWidget(self.co_reboot_button)
        layout.addLayout(aeris_layout)
        
        # Shutdown Button
        self.shutdown_trigger = QPushButton("SHUTDOWN")
        self.shutdown_trigger.clicked.connect(self.shutdown_menu)
        self.shutdown_trigger.setStyleSheet("background-color: DarkRed; color: white; border: 1px solid #CC9999;")
        layout.addWidget(self.shutdown_trigger)

        self.setLayout(layout)

    def update_time(self, data):
        """ uses datetime in the data packet """
        packet_time = data['datetime'].strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.setText(f"{packet_time}")
        self.time_label.setFont(QFont('Arial', 20, QFont.Bold))  # Bold current time display
        self.time_label.setStyleSheet("color: #000000;")  # Black color for current time

    def update_time_clocktime(self):
        """ uses the Pi clock time """
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.setText(f"{current_time}")
        self.time_label.setFont(QFont('Arial', 20, QFont.Bold))  # Bold current time display
        self.time_label.setStyleSheet("color: #000000;")  # Black color for current time

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
                # Format float numbers as XXXX.XX
                if isinstance(var_value, float):
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
                self.aeris_command("aeris_co", cmd)
        elif msg.clickedButton() == shutdown_button:
            cmd = "shutdown"
            if sensor_type == "Aeris CO2":
                self.aeris_command("aeris_co2", cmd)
            else:
                self.aeris_command("aeris_co", cmd)

    def show_co2_options(self):
        self.show_menu("Aeris CO2")

    def show_co_options(self):
        self.show_menu("Aeris CO")

    # Entry function for Aeris CO2 Reboot button
    def aeris_command(self, device_name, command):
        try:
            aeris_device = self.devices.get(device_name)
        except AttributeError:
            print("This is a display demo, there are no active devices.")
            return
        if aeris_device:
            aeris_device.send_command(command)
            print(f"Aeris {device_name} {command} command sent!")
        else:
            print(f"Aeris {device_name} device not found!")

    def pumps_onoff(self):
        self.pumps_on() if self.pumps_tog.isChecked() else self.pumps_off()

    def pumps_on(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('pumps')
        self.pumps_tog.setText("Pumps On")
        self.pumps_tog.setStyleSheet("background-color: #99FF99; color: black; border: 1px solid #CC9999;")  
        jack.write_digital({dig: 1})
    
    def pumps_off(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('pumps')
        self.pumps_tog.setText("Pumps Off")
        self.pumps_tog.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")  
        jack.write_digital({dig: 0})

    def sol_cals(self):
        self.cal1() if self.sol1.isChecked() else self.cal0()

    def sol_aircal(self):
        self.air() if self.sol2.isChecked() else self.cals()

    # The methods below can be called from instrument.py and will change the state of buttons.
    def cal0(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_cals')
        self.sol1.setText("Cal 0")
        self.sol1.setStyleSheet("background-color: DarkSeaGreen; color: black; border: 1px solid #CC9999;")  
        self.sol1.setChecked(False)
        jack.write_digital({dig: 0})

    def cal1(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_cals')
        self.sol1.setText("Cal 1")
        self.sol1.setStyleSheet("background-color: DodgerBlue; color: White; border: 1px solid #CC9999;")  
        self.sol1.setChecked(True)
        jack.write_digital({dig: 1})

    def cals(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_aircal')
        self.sol2.setText("Cal")
        self.sol2.setStyleSheet("background-color: DodgerBlue; color: White; border: 1px solid #CC9999;")  
        self.sol2.setChecked(False)
        jack.write_digital({dig: 1})

    def air(self):
        jack = self.devices.get('labjack')
        dig = jack.get_labjack_address('sol_aircal')
        self.sol2.setText("Air")
        self.sol2.setStyleSheet("background-color: DarkSeaGreen; color: black; border: 1px solid #CC9999;")  
        self.sol2.setChecked(True)
        jack.write_digital({dig: 0})

    def sequence_run(self):
        self.sequence_idle() if self.sequence_button.isChecked() else self.sequence_start()

    def sequence_start(self):
        self.sequence_event.clear()  # Prepare to start the sequence
        self.sequence_button.setChecked(False)
        self.sequence_button.setStyleSheet("background-color: DarkSeaGreen; color: Black; border: 1px solid #CC9999;")  
        
        air_s = float(self.config['triggers'].get('air_duration', 300))  # default 300
        cal_s = float(self.config['triggers'].get('cal_duration', 20))   # default 20

        def countdown(duration, label):
            update_interval = 0.2  # Faster loop interval (0.2 seconds)
            remaining_time = duration
            last_displayed_time = int(remaining_time)  # To avoid frequent unnecessary updates

            while remaining_time > 0:
                if self.sequence_event.is_set():  # Check if stop was requested
                    return True

                # Update UI only when the integer part of the remaining time changes
                current_display_time = int(remaining_time)
                if current_display_time != last_displayed_time:
                    self.sequence_button.setText(f"Running Sequence: {label} ({current_display_time}s)")
                    QApplication.processEvents()  # Update UI
                    last_displayed_time = current_display_time

                # Wait for 0.1 seconds, checking if stop was requested
                if self.sequence_event.wait(update_interval):
                    return True

                remaining_time -= update_interval

            return False  # Countdown finished normally
        
        while not self.sequence_event.is_set():
            # Cal 0
            self.cals()
            self.cal0()
            if countdown(cal_s, "Cal 0"):
                break

            # Air
            self.air()
            self.cal0()
            if countdown(air_s, "Air"):
                break

            # Cal 1
            self.cals()
            self.cal1()
            if countdown(cal_s, "Cal 1"):
                break

            # Air
            self.air()
            self.cal0()
            if countdown(air_s, "Air"):
                break


    # Add Stop Function to Reset UI and Stop the Sequence
    def sequence_idle(self):
        self.sequence_event.set()  # Signal to stop the sequence
        self.sequence_button.setChecked(True)
        self.sequence_button.setText("Sequence Idle")
        self.sequence_button.setStyleSheet("background-color: LightGray; color: Black; border: 1px solid #999;")
        QApplication.processEvents()  # Refresh UI

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
        log_file = "data/shutdown.log"
        # Ensure the directory exists
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a") as file:
            file.write(f"{current_time} - Shutdown initiated\n")

        # tell aeris instruments to shutdown
        self.aeris_command('aeris_co2', 'shutdown')
        self.aeris_command('aeris_co', 'shutdown')
        time.sleep(0.1)
        # shutdown Raspberry Pi
        subprocess.run(["sudo", "shutdown", "-h", "now"])


if __name__ == "__main__":

    app = QApplication(sys.argv)
    panel = DisplayPanel('config.yaml')
    panel.show()
    sys.exit(app.exec_())