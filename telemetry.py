import logging
import time
import pandas as pd
import yaml
import socket

logger = logging.getLogger(__name__)


class Telemetry:
    # The O3 and Maycomm packets arrive at ~1/2 Hz, so at the 1 Hz tick every other
    # row is nan and neither MTS nor the ground stations can draw a usable trace. Hold
    # the last valid value across those gaps -- but only this long, so a genuinely dead
    # sensor reverts to nan instead of showing a frozen, plausible-looking number
    # forever. 6 s covers the normal 2 s cadence plus one missed packet.
    HOLD_SECONDS = 6.0

    def __init__(self, config_file):
        self.load_config(config_file)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.held = {}          # var -> (last valid value, time.monotonic() when seen)
        self.tick_count = 0     # send_data calls with a usable timestamp; drives the rate gate

    def load_config(self, config_file):
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        telem_config_file = config.get("telemetry", {}).get("config")
        if not telem_config_file:
            raise ValueError("Telemetry configuration file not found in config.yaml")
        with open(telem_config_file, 'r') as f:
            self.telem_config = yaml.safe_load(f)

        self.mts_config = self.telem_config.get("mts", {})
        self.data_config = self.telem_config.get("data", {})
        self.mts_rate = self._parse_rate(self.mts_config, "mts")
        self.data_rate = self._parse_rate(self.data_config, "data")
        # Both payloads are gap-filled, so the last-valid cache has to track every
        # variable either one sends -- the data block's list is much the longer.
        self.held_vars = list(dict.fromkeys(self.mts_config.get("variables", [])
                                            + self.data_config.get("variables", [])))

    @staticmethod
    def _parse_rate(block, label):
        """ rate is a tick divisor, not a period in seconds: 1 sends every acquisition
            tick, 2 every 2nd, 3 every 3rd. Ticks are ~950 ms (see instrument.py), so
            the wall-clock cadence is approximate and drifts slightly slower than
            rate seconds. """
        raw = block.get("rate", 1)
        try:
            rate = int(raw)
        except (TypeError, ValueError):
            rate = 0
        if rate < 1:
            logger.warning(f"[Telemetry] {label} rate {raw!r} is not a positive integer, "
                           f"sending every tick instead")
            rate = 1
        return rate

    def send_data(self, data_df):
        """ Called once per acquisition tick with the row just written to the CSV.
            Each block sends only on its own rate boundary; skipped ticks are dropped
            from telemetry, never from the CSV. What goes out is a snapshot of the most
            recent row, not an average or a backlog of the ticks in between. """
        try:
            timestamp = data_df.iloc[-1]['datetime']
            if pd.isnull(timestamp):
                return
            timestamp_str = timestamp.strftime('%Y%m%dT%H%M%S')
            self.tick_count += 1

            mts_ip = self.mts_config.get("ip")
            mts_vars = self.mts_config.get("variables", [])
            # Observe every tick, even ones we don't send. The ~1/2 Hz O3 and Maycomm
            # packets can land entirely on skipped ticks, and if the held values only
            # refreshed on send ticks those variables would expire and read nan forever.
            self._observe(self._payload(data_df, self.held_vars))
            if self._due(self.mts_rate):
                self._send(
                    ips=[mts_ip] if mts_ip else [],
                    port=self.mts_config.get("port"),
                    variables=mts_vars,
                    prefix=self.mts_config.get("iwg_prefix"),
                    df=data_df,
                    timestamp_str=timestamp_str,
                    label="MTS",
                )
            if self._due(self.data_rate):
                self._send(
                    ips=self.data_config.get("ip", []),
                    port=self.data_config.get("port"),
                    variables=self.data_config.get("variables", []),
                    prefix=self.data_config.get("iwg_prefix"),
                    df=data_df,
                    timestamp_str=timestamp_str,
                    label="data",
                )
        except Exception:
            logger.exception("[Telemetry Error] send_data failed")

    def _due(self, rate):
        return self.tick_count % rate == 0

    @staticmethod
    def _payload(df, variables):
        payload = df.reindex(columns=variables).iloc[-1]
        return payload.drop(labels=['datetime'], errors='ignore')

    def _send(self, ips, port, variables, prefix, df, timestamp_str, label):
        if not ips:
            return
        # Both payloads are gap-filled. instrument.py's to_csv runs before this, so the
        # archive on disk keeps the raw nans -- filling is a transmission concern only.
        payload = self._hold_last_valid(self._payload(df, variables))
        values = ",".join(map(str, payload.values))
        message = f"{prefix},{timestamp_str},{values}".encode('utf-8')
        for ip in ips:
            try:
                self.sock.sendto(message, (ip, port))
            except OSError as e:
                logger.error(f"[Telemetry Error] {label} sendto {ip}:{port} failed: {e}")

    def _observe(self, payload):
        """ Record the last valid value for every telemetered variable, every tick. """
        now = time.monotonic()
        for var, value in payload.items():
            if not pd.isna(value):
                self.held[var] = (value, now)

    def _hold_last_valid(self, payload):
        """ Carry the last valid value forward across nan gaps, up to HOLD_SECONDS.
            Applied to both payloads; the CSV on disk stays raw. """
        now = time.monotonic()
        filled = payload.copy()
        for var, value in payload.items():
            if not pd.isna(value):
                continue
            held = self.held.get(var)
            if held is None:
                continue                    # nothing valid seen yet, or already expired
            if now - held[1] <= self.HOLD_SECONDS:
                filled[var] = held[0]
            else:
                # Drop it so this logs once per outage rather than every tick.
                del self.held[var]
                logger.warning(f"Telemetry: {var} has no valid value for over "
                               f"{self.HOLD_SECONDS:.0f}s, sending nan")
        return filled
