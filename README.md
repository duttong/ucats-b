# UCATS-B

Airborne data acquisition for the UCATS-B atmospheric sampling instrument package. UCATS-B runs on an Ubuntu laptop in the aircraft cabin, reads the instrument suite over USB-serial and a LabJack T4, displays live values to the operator, writes a hourly-rotated CSV log, and broadcasts UDP telemetry to the aircraft's MTS and to ground stations.

## Hardware

- **Aeris TDL #1** — CH4 + H2O analyzer (`/dev/ttyUSB3`, 9600 baud)
- **Aeris TDL #2** — CO2 + N2O analyzer (`/dev/ttyUSB0`, 9600 baud)
- **2B Technologies ozone monitor** (`/dev/ttyUSB2`, 4800 baud)
- **Maycomm water vapor analyzer** (`/dev/ttyUSB1`, 115200 baud)
- **LabJack T4** — controls cal/air solenoids, pump power, and the pilot-fail watchdog; reads cal-cylinder pressures and the pilot kill-switch
- Two reference cylinders: `cal0` (100%) and `cal1` (50%) — concentrations in [cals.yaml](cals.yaml)

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./setup.sh   # symlinks system PyQt5 into the venv
```

PyQt5 is intentionally *not* a pip dependency — it's symlinked from the OS package, which is why `setup.sh` is needed after creating the venv.

## Running

```bash
./ucats                           # start the acquisition GUI (uses config.yaml)
python instrument.py --config <file> -v -t <seconds>   # alternate config / verbose / fixed run
python csv_plotter.py             # standalone plot tool (uses config-plot.yaml)
```

Set `sim_mode: true` per device in [config.yaml](config.yaml) to run without hardware — each driver generates synthetic data.

On the aircraft Ubuntu host, the launchers in [desktop/](desktop/) (`ucats-b.desktop`, `plotter.desktop`, `telem.desktop`) are symlinked to the user's Desktop.

## Operator workflow

The operator panel shows live values per instrument, a flashing pilot-fail indicator, and buttons for valve and pump state plus the running cal/air sequence.

### In flight

- The pilot-fail light comes up ON, blinks while the Aeris instruments warm up (~3 minutes), then steady-blinks while data is flowing. It will hold ON if any sensor stops reporting.
- The pilot kill-switch (cabin) cuts UCATS-B if held off for ≥1 s.
- When the cabin pressure crosses the high-altitude threshold (`triggers.alt_high` in `config.yaml`, default 500 mbar), the cal/air sequence starts automatically. It stops when pressure rises back above `triggers.alt_low` (default 700 mbar).
- The sequence cycles `Cal 0 → Air → Cal 1 → Air` with durations from `triggers.cal_duration` and `triggers.air_duration`.

### Files and post-flight cleanup

Data is written to `data/ucatsb-YYYYMMDDHH.csv`, one file per hour. After a flight or cal day:

```bash
./flightmv    # archive current data/ to data/flights/<YYYYMMDD>/
./calmv       # archive current data/ to data/cals/<YYYYMMDD>/
./cleanup     # delete data/ucatsb*.csv and data/*.log (run only after the above)
```

### Logs and diagnostics

`instrument.py` writes timestamped logs to `data/ucats-b.log` via Python's `logging` module (rotates at 20 MB, keeps 5 backups → `ucats-b.log.1`, `ucats-b.log.2`, …). Lines look like:

```
2026-04-29 14:23:45,123 [INFO] aeris: Connected to Aeris device on port /dev/ttyUSB0
2026-04-29 14:23:46,500 [WARNING] __main__: Fail Light: ON
2026-04-29 14:23:47,200 [ERROR] telemetry: [Telemetry Error] data sendto 10.16.101.145:50555 failed: ...
```

Useful greps after a flight:

- `\[ERROR\]` / `\[WARNING\]` — anything other than informational events
- `Fail Light:` — pilot-fail watchdog state transitions
- `Plane has reached altitude.` / `Plane is descending or taxiing.` — altitude-trigger events
- `aeris:` / `lj:` / `o3_sensor:` / `h2o_sensor:` / `telemetry:` — narrow to one module

Run with `-v` (`python instrument.py -v`) to enable `DEBUG` level — emits per-tick raw packets from each driver. Don't use `-v` in flight; it floods the log.

Logs are archived alongside CSVs by `flightmv` / `calmv` (the glob covers rotated files too) and removed by `cleanup`.

## Configuration

- [config.yaml](config.yaml) — devices, serial ports, prefixes, display variables; LabJack DIO/AIN mappings; altitude/sequence thresholds.
- [telem-config.yaml](telem-config.yaml) — UDP telemetry recipients and per-payload variable lists. The `mts:` block targets the aircraft MTS; the `data:` block fans out to ground stations. Lab-test, Ellington, and remote IPs are kept as inline alternates — comment/uncomment rather than editing values.
- [cals.yaml](cals.yaml) — calibration cylinder concentrations (CO2, CH4, N2O, CO).
- [config-plot.yaml](config-plot.yaml) — windows for the standalone CSV plotter.
