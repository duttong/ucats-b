#!/bin/bash
echo "telem.pyu starting at $(date)" >> /home/ucats/code/telem.log

source /home/ucats/code/.venv/bin/activate

cd /home/ucats/code

sleep 30

# start instrument
/home/ucats/code/.venv/bin/python /home/ucats/code/telem.py >> /home/ucats/code/telem.log 2>&1
