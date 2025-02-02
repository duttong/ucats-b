#! /usr/bin/env python

import argparse
import sys
from pathlib import Path
import pandas as pd
import yaml
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QGridLayout,
    QComboBox, QFileDialog, QHBoxLayout, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.dates as mdates


class CSVPlotter(QMainWindow):
    def __init__(self, win_name=None, left_y_vars=None, right_y_vars=None, offset=0):
        super().__init__()
        self.open_windows = []  # List to store references to open windows
        self.win_name = win_name  # CSVPlotter window name text
        self.left_y_vars = left_y_vars or []  # Variables for the left Y-axis
        self.right_y_vars = right_y_vars or []  # Variables for the right Y-axis
        self.offset = offset
        self.data = None

        # background colors
        self.c_background = "oldlace"
        self.c_loadbutton = "khaki"
        self.c_plotbutton = "lightgreen"
        self.c_statsline = "mistyrose"
        self.c_toolbar = "goldenrod"
        self.c_filetext = "dimgrey"

        self.setWindowTitle(self.win_name)
        self.setGeometry(50+self.offset, 50+self.offset, 900, 700)    # upper left coord. then w and h
        self.setStyleSheet(f"font-size: 14px; background-color: {self.c_background};")

        # Main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)

        # Fixed-size widget for controls
        self.controls_widget = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_widget)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)  # Remove extra margins

        self.ax = None  # Placeholder for the matplotlib axes

        # Dropdowns and labels for variable selection
        pad_one = "1px"
        self.variable_label_1 = QLabel("Left-Axis Variable 1:")
        self.variable_combo_1 = QComboBox()
        self.variable_combo_1.setStyleSheet(f"padding: {pad_one};")

        self.variable_label_2 = QLabel("Left-Axis Variable 2:")
        self.variable_combo_2 = QComboBox()
        self.variable_combo_2.setStyleSheet(f"padding: {pad_one};")

        self.variable_label_3 = QLabel("Right-Axis Variable 1:")
        self.variable_combo_3 = QComboBox()
        self.variable_combo_3.setStyleSheet(f"padding: {pad_one};")

        self.variable_label_4 = QLabel("Right-Axis Variable 2:")
        self.variable_combo_4 = QComboBox()
        self.variable_combo_4.setStyleSheet(f"padding: {pad_one};")

        # Buttons for loading data and plotting
        self.load_button = QPushButton("Load CSV")
        self.load_button.setStyleSheet(f"padding: 8px; margin-right: 5px; background-color: {self.c_loadbutton}; ")
        self.plot_button = QPushButton("Refresh Plot")
        self.plot_button.setStyleSheet(f"padding: 8px; background-color: {self.c_plotbutton}")
        self.new_plot_button = QPushButton("New Plot", self)
        self.new_plot_button.setStyleSheet(f"padding: 8px; background-color: {self.c_loadbutton}")

        # Create a label to display the loaded CSV file name
        self.csv_file_label = QLabel("No file loaded")
        self.csv_file_label.setStyleSheet(f"padding: 5px; color: {self.c_filetext};")

        # Create a horizontal layout for the load button and the file name display
        load_layout = QHBoxLayout()
        load_layout.addWidget(self.load_button)
        load_layout.addWidget(self.csv_file_label)
        load_layout.addWidget(self.new_plot_button)
        load_layout.setSpacing(10)

        # Add the horizontal layout to the controls layout
        self.controls_layout.addLayout(load_layout)

        controls_layout = QGridLayout()
        # Add the first column
        controls_layout.addWidget(self.variable_label_1, 0, 0)
        controls_layout.addWidget(self.variable_combo_1, 1, 0)
        controls_layout.addWidget(self.variable_label_2, 2, 0)
        controls_layout.addWidget(self.variable_combo_2, 3, 0)

        # Add the second column
        controls_layout.addWidget(self.variable_label_3, 0, 1)
        controls_layout.addWidget(self.variable_combo_3, 1, 1)
        controls_layout.addWidget(self.variable_label_4, 2, 1)
        controls_layout.addWidget(self.variable_combo_4, 3, 1)

        # Add the plot button in the third column
        controls_layout.addWidget(self.plot_button, 1, 2)

        # Set spacing and margins as needed
        controls_layout.setSpacing(10)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Add the controls layout to the fixed-size widget
        self.controls_layout.addLayout(controls_layout)

        # Label to display statistics of the visible data
        self.statistics_label = QLabel("Window Stats: ")
        self.statistics_label.setStyleSheet(f"padding: 5px; background-color: {self.c_statsline};")
        self.controls_layout.addWidget(self.statistics_label)

        # Add the fixed-size controls widget to the main layout
        self.layout.addWidget(self.controls_widget)
        
        # Matplotlib figure and canvas for displaying the plot
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet(f"background-color: #efe; background-color: {self.c_toolbar}")

        # Set size policies to make the canvas expand
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Add the toolbar and canvas to the main layout
        self.layout.addWidget(self.canvas, 1)
        self.layout.addWidget(self.toolbar)

        # Event handlers
        self.new_csv_file = False
        self.load_button.clicked.connect(self.select_new_file)
        self.plot_button.clicked.connect(self.plot_data)
        self.new_plot_button.clicked.connect(lambda: self.open_new_plot_window([self.left_y_vars[0]]))
        
        # Timer for periodic updates
        self.update_interval = 1000  # Update every 1000 milliseconds (1 seconds)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_data)
        self.timer.start(self.update_interval)

        self.canvas.mpl_connect('draw_event', self.update_statistics)

        # Automatically load the most recent ucatsb-*.csv file on startup
        self.load_csv_data()

        # Plot variables passed to the instance
        variable_1 = self.left_y_vars[0] if len(self.left_y_vars) > 0 else ""
        variable_2 = self.left_y_vars[1] if len(self.left_y_vars) > 1 else ""
        variable_3 = self.right_y_vars[0] if len(self.right_y_vars) > 0 else ""
        variable_4 = self.right_y_vars[1] if len(self.right_y_vars) > 1 else ""

        # Set variables in pull downs
        self.variable_combo_1.setCurrentText(variable_1)
        self.variable_combo_2.setCurrentText(variable_2)
        self.variable_combo_3.setCurrentText(variable_3)
        self.variable_combo_4.setCurrentText(variable_4)

        self.plot_data()

    def open_new_plot_window(self, left_y=None):
        # Open a new plot window instance
        new_window = CSVPlotter(left_y_vars=left_y)
        new_window.show()
        self.open_windows.append(new_window)  # Keep a reference to prevent garbage collection

    def update_data(self):
        """
        Periodically load new data from the CSV file and update the plot.
        """
        if self.data is not None and not self.csv_file_label.text().endswith("No recent 'tdl-' CSV file found."):
            # Store the current x and y limits for both axes
            xlim = self.ax.get_xlim()
            ylim_left = self.ax.get_ylim()
            ylim_right = self.ax2.get_ylim() if self.ax2 else None

            # Store the current selections for variables
            variable_1 = self.variable_combo_1.currentText()
            variable_2 = self.variable_combo_2.currentText()
            variable_3 = self.variable_combo_3.currentText()
            variable_4 = self.variable_combo_4.currentText()

            # Reload data (consider loading only new rows if possible)
            self.load_csv_data(self.current_file_path)

            # Restore the selected variables after reloading the data
            self.variable_combo_1.setCurrentText(variable_1)
            self.variable_combo_2.setCurrentText(variable_2)
            self.variable_combo_3.setCurrentText(variable_3)
            self.variable_combo_4.setCurrentText(variable_4)

            # Update the plot with new data but maintain the same scales
            self.plot_data()

            # Restore x and y limits to maintain the zoom level
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim_left)
            if ylim_right is not None:
                self.ax2.set_ylim(ylim_right)

            # Redraw the canvas to reflect changes
            self.canvas.draw()
            
    def update_statistics(self, event=None):
        """
        Update the mean, standard deviation, and count (N) based on the visible data within the x-axis and y-axis limits.
        """
        if self.data is None or 'datetime' not in self.data.columns or self.ax is None:
            return

        # Get the current x-axis and y-axis limits
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        # Convert x-axis limits to pandas.Timestamp and ensure they are tz-naive
        start_time = pd.Timestamp(mdates.num2date(xlim[0])).tz_localize(None)
        end_time = pd.Timestamp(mdates.num2date(xlim[1])).tz_localize(None)

        # Ensure 'datetime' column is datetime64[ns] and tz-naive
        self.data['datetime'] = pd.to_datetime(self.data['datetime'], errors='coerce').dt.tz_localize(None)

        # Filter data within the visible range of x-axis (time)
        time_mask = (self.data['datetime'] >= start_time) & (self.data['datetime'] <= end_time)

        # Get selected variables
        variable_1 = self.variable_combo_1.currentText()
        variable_2 = self.variable_combo_2.currentText()

        # Calculate statistics for each variable, considering the y-axis range
        stats = []

        if variable_1 in self.data.columns:
            # Further filter based on y-axis limits for variable_1
            y_mask_1 = (self.data[variable_1] >= ylim[0]) & (self.data[variable_1] <= ylim[1])
            variable_1_mask = time_mask & y_mask_1
            visible_data_1 = self.data.loc[variable_1_mask, variable_1]

            if not visible_data_1.empty:
                mean_1 = visible_data_1.mean()
                std_1 = visible_data_1.std()
                count_1 = visible_data_1.count()
                stats.append(f"Window Stats: <b>{variable_1}</b>: {mean_1:.2f} ± {std_1:.2f}, N = {count_1}")
            else:
                stats.append("Window Stats: ")
                #stats.append(f"<b>{variable_1}</b>: Mean = NaN, Std Dev = NaN, N = 0")

        if variable_2 in self.data.columns:
            # Further filter based on y-axis limits for variable_2
            y_mask_2 = (self.data[variable_2] >= ylim[0]) & (self.data[variable_2] <= ylim[1])
            variable_2_mask = time_mask & y_mask_2
            visible_data_2 = self.data.loc[variable_2_mask, variable_2]

            if not visible_data_2.empty:
                mean_2 = visible_data_2.mean()
                std_2 = visible_data_2.std()
                count_2 = visible_data_2.count()
                stats.append(f"<b>{variable_2}</b>: {mean_2:.2f} ± {std_2:.2f}, N = {count_2}")
            else:
                stats.append("")
                #stats.append(f"<b>{variable_2}</b>: Mean = NaN, Std Dev = NaN, N = 0")

        self.statistics_label.setText(" &nbsp;&nbsp;&nbsp;&nbsp; ".join(stats) if stats else "No data in view")   

    def select_new_file(self):
        # Open file dialog for user to select a new file
        new_file, _ = QFileDialog.getOpenFileName(self, "Select CSV File", "", "CSV Files (*.csv)")
        if new_file:
            self.data = None
            self.new_csv_file = True
            self.load_csv_data(new_file)  # Load the new data
            self.plot_data()

    def load_csv_data(self, file_path=None):
        if file_path is None:
            csv_files = sorted(
                Path('.').glob('ucatsb-*.csv'), 
                key=lambda x: x.stat().st_mtime, 
                reverse=True
            )
            if csv_files:
                file_path = csv_files[0]
            else:
                self.csv_file_label.setText("No recent 'tdl-' CSV file found.")
                return

        self.current_file_path = file_path
        
        # Check if data is already loaded
        if hasattr(self, 'data') and self.data is not None:
            last_row_count = len(self.data)
        else:
            last_row_count = 0
            self.data = pd.DataFrame()

        # Load new rows only
        new_data = pd.read_csv(file_path, skiprows=range(1, last_row_count + 1), delimiter=',', engine='python', on_bad_lines='skip')
        if 'datetime' in new_data.columns:
            new_data['datetime'] = pd.to_datetime(new_data['datetime'], errors='coerce')

        # Append new data
        if not new_data.empty:
            self.data = pd.concat([self.data, new_data], ignore_index=True)
            self.data['datetime'] = pd.to_datetime(self.data['datetime'], errors='coerce')

            # Update combo boxes if needed
            if (last_row_count == 0 or set(new_data.columns) != set(self.data.columns)) and self.new_csv_file == False:
                self.variable_combo_1.clear()
                self.variable_combo_2.clear()
                self.variable_combo_3.clear()
                self.variable_combo_4.clear()
                columns = [col for col in self.data.columns if col.lower() != 'datetime']
                self.variable_combo_1.addItems([""] + columns)
                self.variable_combo_2.addItems([""] + columns)
                self.variable_combo_3.addItems([""] + columns)
                self.variable_combo_4.addItems([""] + columns)

            self.csv_file_label.setText(f"Loaded file: {Path(file_path).name} - {len(self.data)} rows")
        else:
            pass
            #print("No new rows to load.")

    def plot_data(self):
        if self.data is None:
            return

        # Variables for left and right axes
        variable_1 = self.variable_combo_1.currentText()
        variable_2 = self.variable_combo_2.currentText()
        variable_3 = self.variable_combo_3.currentText()
        variable_4 = self.variable_combo_4.currentText()

        # Only create the axes if they don't exist to avoid recreating or clearing them incorrectly
        if self.ax is None:
            self.ax = self.figure.add_subplot(111)  # Primary (left) y-axis
            self.ax2 = self.ax.twinx()  # Secondary (right) y-axis

        # Clear plot data but keep axis properties
        self.ax.clear()
        self.ax2.clear()

        # Set colors for each variable
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']
        has_data = False

        # Initialize empty lists for lines and labels
        lines = []
        labels = []

        # Plot data for the left y-axis
        if variable_1 and variable_1 in self.data.columns:
            # Drop rows where variable_1 or 'datetime' has NaN values
            plot_data = self.data[['datetime', variable_1]].dropna()

            # Check if there's any data left
            if not plot_data.empty:
                line1, = self.ax.plot(plot_data['datetime'], plot_data[variable_1], label=variable_1, color=colors[0])
                lines.append(line1)
                labels.append(variable_1)
                has_data = True
            else:
                print(f"No valid data to plot for {variable_1}.")

        if variable_2 and variable_2 != variable_1 and variable_2 in self.data.columns:
            # Drop rows where variable_2 or 'datetime' has NaN values
            plot_data = self.data[['datetime', variable_2]].dropna()

            # Check if there's any data left
            if not plot_data.empty:
                line2, = self.ax.plot(plot_data['datetime'], plot_data[variable_2], label=variable_2, color=colors[1])
                lines.append(line2)
                labels.append(variable_2)
                has_data = True
            else:
                print(f"No valid data to plot for {variable_2}.")

        # Plot data for the right y-axis if there’s data for variable_3 or variable_4
        if variable_3 and variable_3 in self.data.columns:
            # Drop rows where variable_3 or 'datetime' has NaN values
            plot_data = self.data[['datetime', variable_3]].dropna()

            # Check if there's any data left
            if not plot_data.empty:
                line3, = self.ax2.plot(plot_data['datetime'], plot_data[variable_3], label=variable_3, color=colors[2])
                lines.append(line3)
                labels.append(variable_3)
                has_data = True
            else:
                print(f"No valid data to plot for {variable_3}.")

        if variable_4 and variable_4 != variable_3 and variable_4 in self.data.columns:
            # Drop rows where variable_4 or 'datetime' has NaN values
            plot_data = self.data[['datetime', variable_4]].dropna()

            # Check if there's any data left
            if not plot_data.empty:
                line4, = self.ax2.plot(plot_data['datetime'], plot_data[variable_4], label=variable_4, color=colors[3])
                lines.append(line4)
                labels.append(variable_4)
                has_data = True
            else:
                print(f"No valid data to plot for {variable_4}.")

        # Set labels for both y-axes
        self.ax.set_ylabel('Value (Left Axis)')
        self.ax2.set_ylabel('Value (Right Axis)')  # This should ensure it appears on the right
        self.ax2.yaxis.set_label_position("right")  # Explicitly set label position to the right
        self.ax2.yaxis.tick_right()  # Ensure ticks appear on the right

        # Format x-axis and labels
        xtick_locator = mdates.AutoDateLocator()
        self.ax.xaxis.set_major_locator(xtick_locator)
        xtick_formatter = mdates.DateFormatter('%H:%M:%S')
        self.ax.xaxis.set_major_formatter(xtick_formatter)

        if not self.data['datetime'].empty:
            date_str = self.data['datetime'].iloc[0].strftime('%Y-%m-%d')
            self.ax.set_xlabel(f'Date: {date_str}')

        for label in self.ax.get_xticklabels():
            label.set_rotation(45)
            label.set_horizontalalignment('right')

        # Legend
        if has_data and lines:  # Only add legend if there's data and lines to show
            self.ax.legend(lines, labels, loc="best")
        else:
            self.ax.legend().set_visible(False)

        # Update the statistics after plotting
        self.update_statistics()

        self.figure.tight_layout()
        self.canvas.draw()
        
    @classmethod
    def load_config(cls, config_path):
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)

    @classmethod
    def from_config(cls, config_path):
        config = cls.load_config(config_path)
        
        app = QApplication(sys.argv)
        windows = []

        for index, (win_key, win_config) in enumerate(config.get('windows', {}).items()):
            name = win_config.get('name')
            left_y_vars = win_config.get('left_y', [])
            right_y_vars = win_config.get('right_y', [])

            window = cls(
                win_name=name,
                left_y_vars=left_y_vars,
                right_y_vars=right_y_vars,
                offset=index * 20  # Slight offset for window positioning
            )
            window.show()
            windows.append(window)  # Keep references to prevent garbage collection
        
        sys.exit(app.exec_())
        return windows
            

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="CSV Plotter Application")
    parser.add_argument(
        "-c", "--config",
        type=str,
        default="config-plot.yaml",
        help="Path to the configuration file (default: config-plot.yaml)"
    )
    args = parser.parse_args()

    # Load the configuration file
    try:
        with open(args.config, 'r') as file:
            config = yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Configuration file not found: {args.config}")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Open windows as defined in the config
    windows = []
    for index, (win_key, win_config) in enumerate(config.get('windows', {}).items()):
        name = win_config.get('name')
        left_y_vars = win_config.get('left_y', [])
        right_y_vars = win_config.get('right_y', [])
        window = CSVPlotter(
            win_name=name,
            left_y_vars=left_y_vars,
            right_y_vars=right_y_vars,
            offset=index * 20
        )
        window.show()
        windows.append(window)  # Keep references to prevent garbage collection

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()