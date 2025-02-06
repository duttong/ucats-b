#!/bin/bash
echo "UCATS-B starting at $(date)" >> /home/ucats/code/ucats-b.log

source /home/ucats/code/.venv/bin/activate

cd /home/ucats/code

# start telem (comment out if not needed)
/home/ucats/code/.venv/bin/python /home/ucats/code/telem.py &

# start instrument
/home/ucats/code/.venv/bin/python /home/ucats/code/instrument.py >> /home/ucats/code/ucats-b.log 2>&1
