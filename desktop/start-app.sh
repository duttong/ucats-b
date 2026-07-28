#!/bin/bash
# Console output goes to its own file. data/ucats-b.log is owned exclusively by
# the RotatingFileHandler in instrument.py:setup_logging() -- appending to it
# from the shell duplicated every record and kept writing into the renamed
# backup after a rotation.
echo "UCATS-B starting at $(date)" >> /home/ucats/code/data/console.log

source /home/ucats/code/.venv/bin/activate

cd /home/ucats/code

sleep 1

# start instrument
/home/ucats/code/.venv/bin/python /home/ucats/code/instrument.py >> /home/ucats/code/data/console.log 2>&1
