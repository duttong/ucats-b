import logging
import pandas as pd
import yaml
import socket

logger = logging.getLogger(__name__)


class Telemetry:
    def __init__(self, config_file):
        self.load_config(config_file)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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

    def _send(self, ips, port, variables, prefix, df, timestamp_str, label):
        if not ips:
            return
        payload = df.reindex(columns=variables).iloc[-1]
        values = ",".join(map(str, payload.drop(labels=['datetime'], errors='ignore').values))
        message = f"{prefix},{timestamp_str},{values}".encode('utf-8')
        for ip in ips:
            try:
                self.sock.sendto(message, (ip, port))
            except OSError as e:
                logger.error(f"[Telemetry Error] {label} sendto {ip}:{port} failed: {e}")
