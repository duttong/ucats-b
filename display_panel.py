import sys
import time
import yaml
import datetime
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout, QApplication
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt

class DisplayPanel(QWidget):
    def __init__(self, config_file):
        super().__init__()
        self.config_file = config_file
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)  # Adjust margins
        layout.setSpacing(10)  # Spacing between the time and the grid

        # Display current date and time
        self.time_label = QLabel()
        layout.addWidget(self.time_label)
        self.update_time({'datetime': datetime.datetime.now()})

        # Load and display variables from the config file
        with open(self.config_file, 'r') as file:
            config = yaml.safe_load(file)

        self.data_labels = {}  # Store labels to update later

        grid = QGridLayout()
        grid.setSpacing(10)  # Adjust spacing between rows

        row = 0
        for device_name, device_info in config['devices'].items():
            # Skip the device if 'display_vars' is empty or missing
            if not device_info.get('display_vars'):
                continue

            # Device label with larger font and bold style
            device_label = QLabel(f"Device: {device_name}")
            device_label.setFont(QFont('Arial', 16, QFont.Bold))  # Larger, bold font
            device_label.setStyleSheet("color: #2E8B57;")  # Optional: Set color
            grid.addWidget(device_label, row, 0, 1, 2)  # Span across 2 columns
            row += 1

            prefix = config['devices'][device_name]['data_var_prefix']

            # For each display variable, add a QLabel for both the name and the value
            for var in device_info['display_vars']:
                var_label = QLabel(f"   {prefix}{var}: ")
                var_label.setFont(QFont('Arial', 14))  # Smaller font for variable name
                grid.addWidget(var_label, row, 0, alignment=Qt.AlignLeft)

                # Create a label to hold the variable's value
                value_label = QLabel("N/A")
                value_label.setFont(QFont('Arial', 14))
                value_label.setStyleSheet("color: #11e;")  # Optional: Blue color for value
                grid.addWidget(value_label, row, 1, alignment=Qt.AlignRight)

                # Save the label reference to update later
                self.data_labels[f"{device_name}_{prefix}{var}"] = value_label
                row += 1

        layout.addLayout(grid)
        self.setLayout(layout)

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

if __name__ == "__main__":

    app = QApplication(sys.argv)
    panel = DisplayPanel('config.yaml')
    panel.show()
    sys.exit(app.exec_())