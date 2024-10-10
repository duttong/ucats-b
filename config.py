# list of devices and their serial port names
devices = {
    'aeris1': '/dev/ttyUSB0',
    'aeris2': '/dev/ttyUSB2',
    'ozone': '/dev/ttyUSB1'
}

# Set to True to use simulated data.
# Set to False to read serial port for data.
sim_mode = {
    'aeris1': True,
    'aeris2': True,
    'ozone': True   
}

# Prefix used to label the data variables returned from each device.
# Set to None for no prefix
data_var_prefix = {
    'aeris1': 'd1_',
    'aeris2': 'd2_',
    'ozone': 'oz_'
}

