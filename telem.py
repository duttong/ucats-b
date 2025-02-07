#! /usr/bin/env python

import argparse
import sys
import time
import yaml
import socket
import pandas as pd
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
import threading
import signal

class TelemetryGUI(QWidget):
    def __init__(self, packet_type, ip, port):
        super().__init__()
        self.initUI(packet_type, ip, port)
    
    def initUI(self, packet_type, ip, port):
        self.setWindowTitle("Telemetry Data Monitor")
        self.setFixedWidth(500)
        self.layout = QVBoxLayout()
        
        self.label_packet = QLabel(f"{packet_type}")
        self.label_ip = QLabel(f"IP Address: {ip}:{port}")
        self.label_port = QLabel(f"Port: {port}")
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setLineWrapMode(QTextEdit.NoWrap)
        
        self.layout.addWidget(self.label_packet)
        self.layout.addWidget(self.label_ip)
        self.layout.addWidget(self.label_port)
        self.layout.addWidget(self.text_display)
        
        self.setLayout(self.layout)

    def update_text_display(self, message):
        text_edit = self.text_display
        scroll_bar = text_edit.verticalScrollBar()

        # Save the current scroll position
        previous_scroll_position = scroll_bar.value()
        at_bottom = previous_scroll_position == scroll_bar.maximum()

        # Append new text
        text_edit.append(message)

        # Limit the number of lines to 100
        max_lines = 100
        while text_edit.document().blockCount() > max_lines:
            cursor = text_edit.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # Remove new line

        # Restore scroll position unless the user was at the bottom
        if not at_bottom:
            scroll_bar.setValue(previous_scroll_position)
            
    def closeEvent(self, event):
        QApplication.quit()

class TelemetryWorker(QThread):
    data_signal = pyqtSignal(str)

    def __init__(self, telem):
        super().__init__()
        self.telem = telem
        self.running = True

    def run(self):
        while self.running:
            data = self.telem.load_latest_csv()
            message = self.telem.send_data(data)
            if message:
                self.data_signal.emit(message)
            time.sleep(self.telem.rate)

    def stop(self):
        self.running = False

class SABER_telem:
    def __init__(self, data_system, config_file='telem-config.yaml', gui=None):
        self.type = data_system
        self.csv_directory = Path.cwd()
        self.config = self.load_config(config_file)
        self.rate = self.config[data_system]['rate']
        self.ips = self.config[data_system]['ip']
        if not isinstance(self.ips, list):
            self.ips = [self.ips]
        self.port = self.config[data_system]['port']
        self.iwg_prefix = self.config[data_system]['iwg_prefix']
        self.selected_columns = self.config[data_system]['variables']
        self.data = pd.DataFrame()
        self.gui = gui
        self.running = True

    def load_config(self, file_path):
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
        
    def get_latest_csv(self):
        """Finds the latest CSV file in the directory."""
        csv_files = sorted(
            self.csv_directory.glob('ucatsb-*.csv'),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        return csv_files[0] if csv_files else None

    def load_latest_csv(self):
        """Loads the newest CSV file if it's different from the last loaded file."""
        latest_file = self.get_latest_csv()
        if latest_file is None:
            self.data = pd.DataFrame()
        else:
            self.data = self.load_csv_data(latest_file)
        return self.data

    def load_csv_data(self, file_path):
        # Count total rows in the file
        total_rows = sum(1 for _ in open(file_path)) - 1  # Subtract 1 for the header
        
        if total_rows < 2:
            print("Not enough data to fetch the second-to-last row.")
            return self.data

        second_last_row = total_rows - 1  # Second-to-last row index (0-based)
        
        # Read only the second-to-last row
        new_data = pd.read_csv(
            file_path, 
            skiprows=lambda x: x != 0 and x != second_last_row,  # Keep header (x=0) and second-to-last row
            delimiter=',', 
            engine='python', 
            on_bad_lines='skip'
        )

        if 'datetime' in new_data.columns:
            new_data['datetime'] = pd.to_datetime(new_data['datetime'], errors='coerce')

        if not new_data.empty:
            self.data = pd.concat([self.data, new_data], ignore_index=True)
            self.data = self.data.tail(100)

            if self.selected_columns:
                self.data = self.data.reindex(columns=self.selected_columns)

        return self.data

    def send_data(self, data):
        try:
            if data.empty:
                return

            row = data.iloc[-1]
            timestamp = row['datetime']
            if pd.isnull(timestamp):
                print("Warning: Missing datetime value, skipping send.")
                return

            timestamp = timestamp.strftime('%Y%m%dT%H%M%S')
            values = ",".join(map(str, row.drop(labels=['datetime']).values))
            message = f"{self.iwg_prefix},{timestamp},{values}"

            for ip in self.ips:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(message.encode('utf-8'), (ip, self.port))

            return message

        except Exception as e:
            print(f"Error sending data: {e}")
            return None

    def run(self):
        # used for headless running.
        while self.running:
            data = self.load_latest_csv()
            self.send_data(data)
            time.sleep(self.rate)

    def stop(self):
        self.running = False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telemetry Data Sender")
    parser.add_argument("--config", type=str, default="telem-config.yaml", help="Path to the YAML config file")
    parser.add_argument("--nogui", action="store_true", help="Run in headless mode without GUI")

    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    telemetry_instances = [SABER_telem(system, config_file=args.config) for system in config.keys()]

    def graceful_shutdown(signum, frame):
        print("Shutting down gracefully...")
        for telem in telemetry_instances:
            telem.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    if args.nogui:
        print("Running in headless mode (no GUI). Press Ctrl+C to stop.")
        threads = []
        for telem in telemetry_instances:
            thread = threading.Thread(target=telem.run)
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()
    else:
        app = QApplication(sys.argv)
        workers = []

        for telem in telemetry_instances:
            gui = TelemetryGUI(telem.type.upper(), telem.ips, telem.port)
            gui.show()
            telem.gui = gui

            worker = TelemetryWorker(telem)
            worker.data_signal.connect(gui.update_text_display)
            worker.start()
            workers.append(worker)

        sys.exit(app.exec_())
