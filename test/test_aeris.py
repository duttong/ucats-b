import unittest
from unittest.mock import Mock, patch

from aeris import Aeris


class FakeSerial:
    def __init__(self, aeris):
        self.aeris = aeris
        self.lines = iter([
            b"partial," * 20 + b"\n",
            b"complete," * 12 + b"\n",
        ])
        self.read_count = 0

    def readline(self):
        self.read_count += 1
        line = next(self.lines)
        if self.read_count == 2:
            self.aeris.is_collecting = False
        return line


class AerisCollectionTest(unittest.TestCase):
    @patch('aeris.time.sleep', return_value=None)
    def test_first_serial_line_is_discarded(self, _sleep):
        instrument = Aeris('/dev/test', inst_num=2)
        instrument.is_collecting = True
        instrument.ser = FakeSerial(instrument)
        instrument.parse = Mock(return_value={'value': 42})

        instrument._collect_data()

        instrument.parse.assert_called_once_with("complete," * 12 + "\n")
        self.assertEqual(instrument.data_buffer, [{'value': 42}])


if __name__ == '__main__':
    unittest.main()
