import logging
import time
import pandas as pd
import yaml
import socket

logger = logging.getLogger(__name__)


class Telemetry:
    # The O3 and Maycomm packets arrive at ~1/2 Hz, so at the 1 Hz tick every other
    # MTS row is nan and the MTS display can't draw a usable trace. Hold the last valid
    # value across those gaps -- but only this long, so a genuinely dead sensor reverts
    # to nan instead of showing a frozen, plausible-looking number forever. 6 s covers
    # the normal 2 s cadence plus one missed packet.
    MTS_HOLD_SECONDS = 6.0

    def __init__(self, config_file):
        self.load_config(config_file)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mts_held = {}      # var -> (last valid value, time.monotonic() when seen)

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

    def send_data(self, data_df):
        try:
            timestamp = data_df.iloc[-1]['datetime']
            if pd.isnull(timestamp):
                return
            timestamp_str = timestamp.strftime('%Y%m%dT%H%M%S')

            mts_ip = self.mts_config.get("ip")
            self._send(
                ips=[mts_ip] if mts_ip else [],
                port=self.mts_config.get("port"),
                variables=self.mts_config.get("variables", []),
                prefix=self.mts_config.get("iwg_prefix"),
                df=data_df,
                timestamp_str=timestamp_str,
                label="MTS",
                fill_gaps=True,
            )
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

    def _send(self, ips, port, variables, prefix, df, timestamp_str, label, fill_gaps=False):
        if not ips:
            return
        payload = df.reindex(columns=variables).iloc[-1]
        payload = payload.drop(labels=['datetime'], errors='ignore')
        if fill_gaps:
            payload = self._hold_last_valid(payload)
        values = ",".join(map(str, payload.values))
        message = f"{prefix},{timestamp_str},{values}".encode('utf-8')
        for ip in ips:
            try:
                self.sock.sendto(message, (ip, port))
            except OSError as e:
                logger.error(f"[Telemetry Error] {label} sendto {ip}:{port} failed: {e}")

    def _hold_last_valid(self, payload):
        """ Carry the last valid value forward across nan gaps, up to MTS_HOLD_SECONDS.
            MTS only -- the ground station payload stays raw. """
        now = time.monotonic()
        filled = payload.copy()
        for var, value in payload.items():
            if not pd.isna(value):
                self.mts_held[var] = (value, now)
                continue
            held = self.mts_held.get(var)
            if held is None:
                continue                    # nothing valid seen yet, or already expired
            if now - held[1] <= self.MTS_HOLD_SECONDS:
                filled[var] = held[0]
            else:
                # Drop it so this logs once per outage rather than every tick.
                del self.mts_held[var]
                logger.warning(f"MTS telemetry: {var} has no valid value for over "
                               f"{self.MTS_HOLD_SECONDS:.0f}s, sending nan")
        return filled
