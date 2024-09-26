#!/bin/bash

# this script is for rebuilding the virtual environment 
# firt create a venv the install the python libraries
# pip install -r requirements.txt
# then make the symbolic link below

# Create the symbolic link to the system-installed PyQt5 in the virtual environment
ln -s /usr/lib/python3/dist-packages/PyQt5 .venv/lib/python3.11/site-packages/
