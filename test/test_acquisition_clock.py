import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from instrument import AcquisitionClock, TDL_package


class FakeClock:
    def __init__(self, observations):
        self.observations = iter(observations)

    def observe(self):
        return next(self.observations)


class FakeDevice:
    def __init__(self, packets):
        self.packets = iter(packets)

    def get_all_data(self):
        return next(self.packets)


class FakeDisplay:
    def update_display_data(self, device_name, data):
        pass

    def update_time_clocktime(self):
        pass


class FakeTelemetry:
    def __init__(self):
        self.rows = []

    def send_data(self, data):
        self.rows.append(data.copy())


class AcquisitionClockTest(unittest.TestCase):
    def test_normal_delays_do_not_change_epoch(self):
        clock = AcquisitionClock(jump_threshold_seconds=5.0)
        start = datetime(2026, 8, 1, 15, 0, 0)

        first = clock.observe(start, 1_000_000_000)
        second = clock.observe(start + timedelta(seconds=0.95), 1_950_000_000)
        delayed = clock.observe(start + timedelta(seconds=10.95), 11_950_000_000)

        self.assertEqual([first['sample_id'], second['sample_id'], delayed['sample_id']], [0, 1, 2])
        self.assertEqual(delayed['clock_epoch'], 0)
        self.assertIsNone(delayed['clock_jump_s'])

    def test_forward_and_backward_steps_create_epochs(self):
        clock = AcquisitionClock(jump_threshold_seconds=5.0)
        start = datetime(2026, 8, 1, 17, 6, 1)
        clock.observe(start, 1_000_000_000)

        forward = clock.observe(
            start + timedelta(seconds=1, minutes=76, milliseconds=16000),
            2_000_000_000,
        )
        backward = clock.observe(
            start + timedelta(minutes=36, seconds=48),
            2_209_000_000_000,
        )

        self.assertEqual(forward['clock_epoch'], 1)
        self.assertAlmostEqual(forward['clock_jump_s'], 4576.0)
        self.assertEqual(backward['clock_epoch'], 2)
        self.assertLess(backward['clock_jump_s'], -4000)

    def test_final_output_uses_new_packets_after_clock_step(self):
        metadata = ['datetime', 'sample_id', 'monotonic_ns', 'clock_epoch', 'clock_jump_s']
        old_time = datetime(2026, 8, 1, 18, 55, 51)
        corrected_time = datetime(2026, 8, 1, 17, 42, 49)

        package = type('Package', (), {})()
        package.acquisition_clock = FakeClock([{
            'datetime': corrected_time,
            'sample_id': 100,
            'monotonic_ns': 123_000_000_000,
            'clock_epoch': 2,
            'clock_jump_s': -4576.0,
        }])
        package.devices = {
            'test_sensor': FakeDevice([[
                {'datetime': corrected_time, 'test_value': 42.0}
            ]])
        }
        package.streams = {
            'test_sensor': pd.DataFrame([
                {'datetime': old_time, 'test_value': 999.0}
            ])
        }
        package.display_panel = FakeDisplay()
        package.telemetry = FakeTelemetry()
        package.all_variables = metadata + ['test_value']
        package.stream_size = 100

        with TemporaryDirectory() as directory:
            package.file_path = str(Path(directory) / 'output.csv')
            TDL_package.collect_data(package)
            output = pd.read_csv(package.file_path)

        self.assertEqual(output.loc[0, 'sample_id'], 100)
        self.assertEqual(output.loc[0, 'clock_epoch'], 2)
        self.assertEqual(output.loc[0, 'test_value'], 42.0)
        self.assertNotEqual(output.loc[0, 'test_value'], 999.0)
        self.assertEqual(len(package.telemetry.rows), 1)


if __name__ == '__main__':
    unittest.main()
