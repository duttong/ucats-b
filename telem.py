#! /usr/bin/env python

import argparse
import sys
import time
import yaml
import socket
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit
from PyQt5.QtCore import QTimer

class TelemetryGUI(QWidget):
    def __init__(self, ip, port):
        super().__init__()
        self.initUI(ip, port)
    
    def initUI(self, ip, port):
        self.setWindowTitle("Telemetry Data Monitor")
        self.setFixedWidth(500)  # Set window width to 500 pixels
        self.layout = QVBoxLayout()
        
        self.label_ip = QLabel(f"IP Address: {ip}")
        self.label_port = QLabel(f"Port: {port}")
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        
        self.layout.addWidget(self.label_ip)
        self.layout.addWidget(self.label_port)
        self.layout.addWidget(self.text_display)
        
        self.setLayout(self.layout)
    
    def update_text_display(self, message):
        text = self.text_display.toPlainText().split('\n')
        text.append(message)
        if len(text) > 100:
            text = text[-100:]  # Keep only the last 100 lines
        self.text_display.setPlainText('\n'.join(text))
        self.text_display.verticalScrollBar().setValue(self.text_display.verticalScrollBar().maximum())

class SABER_telem:
    def __init__(self, rate=None, ip=None, port=None, config_file="telem-config.yaml", gui=None):
        self.rate = rate  # Interval for checking new data (seconds)
        self.ip = ip
        self.port = port
        self.data = pd.DataFrame()
        self.config_file = config_file
        if rate is None:
            self.rate = self.load_config("rate")
        else:
            self.rate = rate
        if ip is None:
            self.ip = self.load_config("ip")
        else:
            self.ip = ip
        if port is None:
            self.port = self.load_config("port")
        else:
            self.port = port
        self.iwg_prefix = self.load_config("iwg_prefix") or "UCB"
        self.selected_columns = self.load_config("variables") or []

        self.current_file_path = None
        self.gui = gui

        if self.gui:
            self.gui.label_ip.setText(f"IP Address: {self.ip}")
            self.gui.label_port.setText(f"Port: {self.port}")

        # Automatically load the most recent CSV file on startup
        self.load_csv_data()

    def load_config(self, parameter):
        """Loads the YAML config file and returns the selected columns."""
        try:
            with open(self.config_file, 'r') as file:
                config = yaml.safe_load(file)
                return config.get(parameter, [])  # Expecting a "variables" key with a list of column names
        except Exception as e:
            print(f"Warning: Could not load config file {self.config_file}: {e}")
            return []

    def load_csv_data(self):
        """Loads new data from the most recent CSV file."""
        csv_files = sorted(
            Path('.').glob('ucatsb-*.csv'), 
            key=lambda x: x.stat().st_mtime, 
            reverse=True
        )
        
        if csv_files:
            file_path = csv_files[0]
            self.current_file_path = file_path
        else:
            print("No recent 'ucatsb-' CSV file found.")
            return
        
        # Check if data is already loaded
        last_row_count = len(self.data) if self.data is not None else 0
        
        # Load new rows only
        new_data = pd.read_csv(
            file_path, 
            skiprows=range(1, last_row_count + 1), 
            delimiter=',', 
            engine='python', 
            on_bad_lines='skip'
        )
        
        if 'datetime' in new_data.columns:
            new_data['datetime'] = pd.to_datetime(new_data['datetime'], errors='coerce')
        
        # Apply column filter from config
        if self.selected_columns:
            new_data = new_data[self.selected_columns]
        
        if not new_data.empty:
            self.data = pd.concat([self.data, new_data], ignore_index=True)
            self.data = self.data.tail(100)  # Keep only the last 100 rows in memory
            self.send_data(new_data.tail(1))

    def send_data(self, data):
        """Sends the latest data row to the specified IP and port using IWG1 format."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                if data.empty:
                    return  # No data to send
                
                # Get the last row directly (as a Series)
                row = data.iloc[-1]  
                
                # Extract timestamp from the 'datetime' column
                timestamp = row['datetime']
                if pd.isnull(timestamp):  # Handle missing or invalid timestamps
                    print("Warning: Missing datetime value, skipping send.")
                    return
                
                # Convert to ISO 8601 format (ensure string format with 'Z' suffix)
                timestamp = timestamp.isoformat() + "Z"

                # Convert all values (except datetime) to string
                values = ",".join(map(str, row.drop(labels=['datetime']).values))

                # Construct the IWG1 message using self.iwg_prefix
                message = f"{self.iwg_prefix},{timestamp},{values}"
                
                sock.sendto(message.encode('utf-8'), (self.ip, self.port))
                
                # Print for debugging (optional)
                #print(f"Sent: {message}")
                
                # Update the GUI if available
                if self.gui:
                    self.gui.update_text_display(message)
                        
        except Exception as e:
            print(f"Error sending data: {e}")

    def run(self):
        """Continuously checks for new data and sends it."""
        while True:
            self.load_csv_data()
            time.sleep(self.rate)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telemetry Data Sender")
    parser.add_argument("--ip", type=str, help="Destination IP address - override assigned value in config file.")
    parser.add_argument("--port", type=int, help="Destination port number - override assigned value in config file.")
    parser.add_argument("--rate", type=int, help="Polling rate in seconds - override assigned value in config file.")
    parser.add_argument("--config", type=str, default="telem-config.yaml", help="Path to the YAML config file")
    parser.add_argument("--nogui", action="store_true", help="Run in headless mode without GUI")

    args = parser.parse_args()

    # Initialize telemetry system
    telem = SABER_telem(rate=args.rate, ip=args.ip, port=args.port, config_file=args.config, gui=None)

    if args.nogui:
        # Headless mode: Use the infinite loop in run()
        print("Running in headless mode (no GUI). Press Ctrl+C to stop.")
        telem.run()
    else:
        # GUI Mode: Start the GUI and use QTimer for updates
        app = QApplication(sys.argv)
        gui = TelemetryGUI(args.ip, args.port)
        gui.show()

        # Re-assign GUI to telemetry system
        telem.gui = gui

        timer = QTimer()
        timer.timeout.connect(telem.load_csv_data)
        timer.start(telem.rate * 1000)

        sys.exit(app.exec_())