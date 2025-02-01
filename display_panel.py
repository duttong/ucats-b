import sys
import time
import yaml
import datetime
import subprocess
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGridLayout, QApplication, QMessageBox
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

class DisplayPanel(QWidget):
    def __init__(self, config_file, devices=None):
        super().__init__()
        self.config_file = config_file
        self.config = self.load_config(config_file)
        self.devices = devices
        self.initUI()

    def load_config(self, file_path='config.yaml'):
        """ Load the configuration from a YAML file """
        with open(file_path, 'r') as file:
            return yaml.safe_load(file)

    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)  # Adjust margins
        layout.setSpacing(10)  # Spacing between the time and the grid

        # Display current date and time
        self.time_label = QLabel()
        layout.addWidget(self.time_label)
        self.update_time({'datetime': datetime.datetime.now()})

        self.data_labels = {}  # Store labels to update later

        grid = QGridLayout()
        grid.setSpacing(10)  # Adjust spacing between rows

        row = [0, 0, 0]
        for device_name, device_info in self.config['devices'].items():
            # Skip the device if 'display_vars' is empty or missing
            if not device_info.get('display_vars'):
                continue

            colinc = 0
            if device_name.lower() == "h2o_sensor" or device_name.lower() == "o3_sensor":
                colinc = 2

            # Device label with larger font and bold style
            device_label = QLabel(f"{device_name}")
            device_label.setFont(QFont('Arial', 16, QFont.Bold))  # Larger, bold font
            device_label.setStyleSheet("color: #2E8B57;")  # Optional: Set color
            grid.addWidget(device_label, row[colinc], colinc, 1, 2)  # Span across 2 columns
            row[colinc] += 1

            prefix = self.config['devices'][device_name]['data_var_prefix']

            # For each display variable, add a QLabel for both the name and the value
            for var in device_info['display_vars']:
                var_label = QLabel(f"   {prefix}{var}: ")
                var_label.setFont(QFont('Arial', 14))  # Smaller font for variable name
                grid.addWidget(var_label, row[colinc], 0+colinc, alignment=Qt.AlignLeft)

                # Create a label to hold the variable's value
                value_label = QLabel("N/A")
                value_label.setFont(QFont('Arial', 14))
                value_label.setStyleSheet("color: #11e;")  # Optional: Blue color for value
                grid.addWidget(value_label, row[colinc], 1+colinc, alignment=Qt.AlignRight)

                # Save the label reference to update later
                self.data_labels[f"{device_name}_{prefix}{var}"] = value_label
                row[colinc] += 1

        layout.addLayout(grid)
        self.pumps_tog = QPushButton("Pumps Off")
        self.pumps_tog.setCheckable(True)  # Makes the button toggle
        self.pumps_tog.clicked.connect(self.pumps_onoff)
        self.pumps_tog.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")  # Light red when OFF
        layout.addWidget(self.pumps_tog)

        self.co2_reboot_button = QPushButton("Aeris CO2 Reboot/Shutdown")
        self.co2_reboot_button.clicked.connect(self.show_co2_options)
        self.co2_reboot_button.setStyleSheet(
            "background-color: #FFCCCC; color: black; border: 1px solid #CC9999;"
        )
        layout.addWidget(self.co2_reboot_button)

        self.co_reboot_button = QPushButton("Aeris CO Reboot/Shutdown")
        self.co_reboot_button.clicked.connect(self.show_co_options)
        self.co_reboot_button.setStyleSheet(
            "background-color: #FFCCCC; color: black; border: 1px solid #CC9999;"
        )
        layout.addWidget(self.co_reboot_button)
        self.setLayout(layout)

        # received a off signal from pilot
        self.shutdown_trigger = QPushButton("SHUTDOWN")
        self.shutdown_trigger.clicked.connect(self.shutdown)
        self.shutdown_trigger.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")  # Light red when OFF
        layout.addWidget(self.shutdown_trigger)

    def update_time(self, data):
        packet_time = data['datetime'].strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.setText(f"Recent Data Time:\n   {packet_time}")
        self.time_label.setFont(QFont('Arial', 18, QFont.Bold))  # Bold current time display
        self.time_label.setStyleSheet("color: #000000;")  # Black color for current time

    def update_display_data(self, device_name, data):
        """ Update the display with new data for a given device. """
        for var_name, var_value in data.items():
            # Construct the key used to store labels (device name + variable name)
            label_key = f"{device_name}_{var_name}"
            if label_key in self.data_labels:
                self.data_labels[label_key].setText(str(var_value))

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
            if sensor_type == "Aeris CO2":
                self.aeris_co2_command("reboot")
            else:
                self.aeris_co_command("reboot")
        elif msg.clickedButton() == shutdown_button:
            if sensor_type == "Aeris CO2":
                self.aeris_co2_command("shutdown")
            else:
                self.aeris_co_command("shutdown")

    def show_co2_options(self):
        self.show_menu("Aeris CO2")

    def show_co_options(self):
        self.show_menu("Aeris CO")

    # Entry function for Aeris CO2 Reboot button
    def aeris_co2_command(self, command):
        try:
            aeris_device = self.devices.get('Aeris_CO2')
        except AttributeError:
            print("This is a display demo, there are no active devices.")
            return
        if aeris_device:
            aeris_device.send_command(command)
            print(f"Aeris CO2 {command} command sent!")
        else:
            print("Aeris CO2 device not found!")

    # Entry function for Aeris CO Reboot button
    def aeris_co_command(self, command):
        try:
            aeris_device = self.devices.get('Aeris_CO')
        except AttributeError:
            print("This is a display demo, there are no active devices.")
            return
        if aeris_device:
            aeris_device.send_command(command)
            print(f"Aeris CO {command} command sent!")
        else:
            print("Aeris CO device not found!")

    def pumps_onoff(self):
        jack = self.devices.get('Labjack')
        dig = jack.get_labjack_address('pumps')
        if self.pumps_tog.isChecked():
            self.pumps_tog.setText("Pumps On")
            self.pumps_tog.setStyleSheet("background-color: #99FF99; color: black; border: 1px solid #CC9999;")  
            jack.write_digital({dig: 1})
        else:
            self.pumps_tog.setText("Pumps Off")
            self.pumps_tog.setStyleSheet("background-color: #FF9999; color: black; border: 1px solid #CC9999;")  
            jack.write_digital({dig: 0})

    def shutdown(self):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("shutdown.txt", "a") as file:
            file.write(f"{current_time} - Shutdown initiated\n")

        # tell aeris instruments to shutdown
        self.aeris_co2_command('shutdown')
        self.aeris_co_command('shutdown')
        time.sleep(1)
        # shutdown Raspberry Pi
        subprocess.run(["sudo", "shutdown", "-h", "now"])


if __name__ == "__main__":

    app = QApplication(sys.argv)
    panel = DisplayPanel('config.yaml')
    panel.show()
    sys.exit(app.exec_())