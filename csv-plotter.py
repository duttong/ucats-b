#! /usr/bin/env python

import sys
from pathlib import Path
import pandas as pd
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel,
    QComboBox, QFileDialog, QHBoxLayout, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.dates as mdates

class CSVPlotter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSV Plotter")
        self.setGeometry(200, 150, 900, 600)
        self.setStyleSheet("font-size: 14px; background-color: #efe;")

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
        self.variable_label_1 = QLabel("Select Variable 1:")
        self.variable_combo_1 = QComboBox()
        self.variable_combo_1.setStyleSheet("padding: 5px;")

        self.variable_label_2 = QLabel("Select Variable 2:")
        self.variable_combo_2 = QComboBox()
        self.variable_combo_2.setStyleSheet("padding: 5px;")

        # Buttons for loading data and plotting
        self.load_button = QPushButton("Load CSV")
        self.load_button.setStyleSheet("padding: 8px; margin-right: 5px;")
        self.plot_button = QPushButton("Plot Data")
        self.plot_button.setStyleSheet("padding: 8px;")

        # Create a label to display the loaded CSV file name
        self.csv_file_label = QLabel("No file loaded")
        self.csv_file_label.setStyleSheet("padding: 5px; color: #555;")

        # Create a horizontal layout for the load button and the file name display
        load_layout = QHBoxLayout()
        load_layout.addWidget(self.load_button)
        load_layout.addWidget(self.csv_file_label)
        load_layout.setSpacing(10)

        # Add the horizontal layout to the controls layout
        self.controls_layout.addLayout(load_layout)

        # Layout arrangement for the top controls
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.variable_label_1)
        controls_layout.addWidget(self.variable_combo_1)
        controls_layout.addWidget(self.variable_label_2)
        controls_layout.addWidget(self.variable_combo_2)
        controls_layout.addWidget(self.plot_button)
        controls_layout.setSpacing(10)
        self.controls_layout.addLayout(controls_layout)
        #self.controls_layout.setStyleSheet("background-color: #efe;")

        # Label to display statistics of the visible data
        self.statistics_label = QLabel("Mean: N/A, Std Dev: N/A")
        self.statistics_label.setStyleSheet("padding: 5px; color: #333;")
        self.controls_layout.addWidget(self.statistics_label)

        # Add the controls layout to the fixed-size widget
        self.controls_layout.addLayout(controls_layout)

        # Add the fixed-size controls widget to the main layout
        self.layout.addWidget(self.controls_widget)
        
        # Matplotlib figure and canvas for displaying the plot
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet("background-color: #efe;")

        # Set size policies to make the canvas expand
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Add the toolbar and canvas to the main layout
        self.layout.addWidget(self.canvas, 1)
        self.layout.addWidget(self.toolbar)

        # Event handlers
        self.load_button.clicked.connect(self.manual_load_csv)
        self.plot_button.clicked.connect(self.plot_data)

        # Timer for periodic updates
        self.update_interval = 1000  # Update every 1000 milliseconds (1 seconds)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_data)
        self.timer.start(self.update_interval)

        self.canvas.mpl_connect('draw_event', self.update_statistics)

        # Automatically load the most recent tdl-*.csv file on startup
        self.load_csv()

    def update_data(self):
        """
        Periodically load the new data from the CSV file and update the plot.
        """
        if self.data is not None and not self.csv_file_label.text().endswith("No recent 'tdl-' CSV file found."):
            # Store the current x and y limits and selected variables
            ax = self.figure.gca()
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            variable_1 = self.variable_combo_1.currentText()
            variable_2 = self.variable_combo_2.currentText()

            # Reload data (you might want to load only new rows if possible)
            self.load_csv(self.current_file_path)

            # Restore the selected variables after reloading the data
            self.variable_combo_1.setCurrentText(variable_1)
            self.variable_combo_2.setCurrentText(variable_2)

            # Update the plot with new data but maintain the same scales
            self.plot_data()

            # Restore the x and y limits to maintain zoom level
            ax = self.figure.gca()  # Get the new axis after updating the plot
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
            
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
                stats.append(f"<b>{variable_1}</b>: {mean_1:.2f} ± {std_1:.2f}, N = {count_1}")
            else:
                stats.append(f"<b>{variable_1}</b>: Mean = NaN, Std Dev = NaN, N = 0")

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
                stats.append(f"<b>{variable_2}</b>: Mean = NaN, Std Dev = NaN, N = 0")

        self.statistics_label.setText(" &nbsp;&nbsp;&nbsp;&nbsp; ".join(stats) if stats else "No data in view")   

    def load_csv(self, file_path=None):
        if file_path is None:
            csv_files = sorted(
                Path('.').glob('tdl-*.csv'), 
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
        new_data = pd.read_csv(file_path, skiprows=range(1, last_row_count + 1))
        if 'datetime' in new_data.columns:
            new_data['datetime'] = pd.to_datetime(new_data['datetime'], errors='coerce')

        # Append new data
        if not new_data.empty:
            self.data = pd.concat([self.data, new_data], ignore_index=True)
            self.data['datetime'] = pd.to_datetime(self.data['datetime'], errors='coerce')

            # Update combo boxes if needed
            if last_row_count == 0 or set(new_data.columns) != set(self.data.columns):
                self.variable_combo_1.clear()
                self.variable_combo_2.clear()
                columns = [col for col in self.data.columns if col.lower() != 'datetime']
                self.variable_combo_1.addItems([""] + columns)
                self.variable_combo_2.addItems([""] + columns)

                # Automatically select the first variable if available
                if columns:
                    self.variable_combo_1.setCurrentIndex(1)  # Index 1 because index 0 is an empty string

            self.csv_file_label.setText(f"Loaded file: {Path(file_path).name} - {len(self.data)} rows")
        else:
            pass
            #print("No new rows to load.")

    def manual_load_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open CSV File", "", "CSV Files (*.csv);;All Files (*)")
        if file_path:
            self.load_csv(file_path)

    def plot_data(self):
        if self.data is None:
            return

        variable_1 = self.variable_combo_1.currentText()
        variable_2 = self.variable_combo_2.currentText()

        # Clear the previous plot, but only create the axes if they don't exist
        if self.ax is None:
            self.figure.clear()
            self.ax = self.figure.add_subplot(111)

        self.ax.clear()  # Clear the existing plot without resetting the axes object

        has_data = False

        if variable_1 and variable_1 in self.data.columns:
            self.ax.plot(self.data['datetime'], self.data[variable_1], label=variable_1)
            has_data = True

        if variable_2 and variable_2 != variable_1 and variable_2 in self.data.columns:
            self.ax.plot(self.data['datetime'], self.data[variable_2], label=variable_2)
            has_data = True

        xtick_locator = mdates.AutoDateLocator()
        self.ax.xaxis.set_major_locator(xtick_locator)
        xtick_formatter = mdates.DateFormatter('%H:%M:%S')
        self.ax.xaxis.set_major_formatter(xtick_formatter)

        if not self.data['datetime'].empty:
            date_str = self.data['datetime'].iloc[0].strftime('%Y-%m-%d')
            self.ax.set_xlabel(f'Datetime (Date: {date_str})')

        for label in self.ax.get_xticklabels():
            label.set_rotation(45)
            label.set_horizontalalignment('right')

        self.ax.set_ylabel('Value')

        if has_data:
            self.ax.legend()
        else:
            self.ax.legend().set_visible(False)

        # Update the statistics right after plotting
        self.update_statistics()

        self.ax.set_title('CSV Data Plot')
        self.figure.tight_layout(pad=2.0)
        self.canvas.draw()

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = CSVPlotter()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()