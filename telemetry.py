import pandas as pd
import yaml
import socket
import time
import threading

class Telemetry:
    def __init__(self, config_file):
        self.load_config(config_file)
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def load_config(self, config_file):
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Load telemetry config
        telem_config_file = config.get("telemetry", {}).get("config")
        if telem_config_file:
            with open(telem_config_file, 'r') as f:
                self.telem_config = yaml.safe_load(f)
        else:
            raise ValueError("Telemetry configuration file not found in config.yaml")
        
        self.mts_config = self.telem_config.get("mts", {})
        self.data_config = self.telem_config.get("data", {})
    
    def _send_data_thread(self, data_df):
        """Threaded method to send data to telemetery system """
        try:

            row = data_df.iloc[-1]
            timestamp = row['datetime']

            if pd.isnull(timestamp):
                #print("Warning: Missing datetime value, skipping send.")
                return

            # Convert timestamp to string
            timestamp_str = timestamp.strftime('%Y%m%dT%H%M%S')

            # Send MTS data to a single IP
            mts_ip = self.mts_config.get("ip")
            mts_port = self.mts_config.get("port")
            mts_vars = self.mts_config.get("variables", [])
            mts_pre = self.mts_config.get("iwg_prefix")
            mts_payload = data_df.reindex(columns=mts_vars)
            mts_payload = mts_payload.iloc[-1]
            try:
                values = ",".join(map(str, mts_payload.drop(labels=['datetime']).values))
                mts_message = f"{mts_pre},{timestamp_str},{values}".encode('utf-8')
                self.sock.sendto(mts_message, (mts_ip, mts_port))
                time.sleep(0.1)
            except Exception as e:
                #print(f"Error sending MTS data: {e}")
                pass
            
            # Send data packets to multiple IPs
            data_ips = self.data_config.get("ip", [])
            data_port = self.data_config.get("port")
            data_vars = self.data_config.get("variables", [])
            data_pre = self.data_config.get("iwg_prefix")
            data_payload = data_df.reindex(columns=data_vars)
            data_payload = data_payload.iloc[-1]
            try:
                values = ",".join(map(str, data_payload.drop(labels=['datetime']).values))
                data_message = f"{data_pre},{timestamp_str},{values}".encode('utf-8')
                for ip in data_ips:
                    self.sock.sendto(data_message, (ip, data_port))
                    time.sleep(0.1)
            except Exception as e:
                #print(f"Error sending data: {e}")
                return None
        
        except socket.error as e:
            print(f"[Telemetry Error] Failed to send data: {e}")

    def send_data(self, data):
        """Start a new thread to send telemetry data."""
        thread = threading.Thread(target=self._send_data_thread, args=(data,))
        thread.start()
