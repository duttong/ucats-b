#! /usr/bin/env python

from time import sleep
import argparse
from labjack import ljm


class TSeriesLabJack:
    """ A simple class for interfacing with T4, T7, and T8 Labjack devices. """
    def __init__(self):
        self.handle = self.connect_labjack()

    def connect(self):
        """Connects to a LabJack T-Series device."""
        try:
            handle = ljm.open(ljm.constants.dtANY, ljm.constants.ctANY, "ANY")
        except ljm.LJMError as e:
            print(f"Failed to connect to LabJack: {e}")
            quit()
        info = ljm.getHandleInfo(handle)
        print(f"Opened LabJack - Device Type: {info[0]}, Connection Type: {info[1]}, Serial: {info[2]}")
        return handle

    def read_analog(self, address: int) -> float:
        """Reads an analog value from a given channel."""
        return ljm.eReadName(self.handle, f'AIN{address}')

    def read_digital(self, address: int) -> float:
        """Reads a digital value from a given channel."""
        return ljm.eReadName(self.handle, f'FIO{address}')

    def write_digital(self, address: int, state: int) -> None:
        """Sets a digital state (0 or 1) for a given channel."""
        ljm.eWriteName(self.handle, f'FIO{address}', state)

    def disconnect(self):
        """Closes the LabJack connection."""
        ljm.close(self.handle)


if __name__ == '__main__':
    TOGGLE_DELAY = 0.05
    TOGGLE_DURATION = 1

    parser = argparse.ArgumentParser(description='Basic control of a T-Series LabJack')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--high', type=int, metavar='ADD', help='Set digital address to high (1)')
    group.add_argument('--low', type=int, metavar='ADD', help='Set digital address to low (0)')
    group.add_argument('--tog', type=int, metavar='ADD', help='Toggle digital address from low to high and back')

    args = parser.parse_args()

    jack = TSeriesLabJack()
    try:
        if args.high is not None:
            jack.write_digital(args.high, 1)
        elif args.low is not None:
            jack.write_digital(args.low, 0)
        elif args.tog is not None:
            jack.write_digital(args.tog, 0)
            sleep(TOGGLE_DELAY)
            jack.write_digital(args.tog, 1)
            sleep(TOGGLE_DURATION)
            jack.write_digital(args.tog, 0)
    finally:
        jack.disconnect()