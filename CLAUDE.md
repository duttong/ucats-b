# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

UCATS-B is the airborne data acquisition system for the UCATS-B instrument package: two Aeris TDL analyzers (CO2/N2O and CO/N2O), a 2BTech ozone monitor, a Maycomm water vapor analyzer, and a LabJack T4 for digital/analog I/O (cal solenoids, pump control, pilot watchdog, pressure transducers). Target host is an Ubuntu laptop on a research aircraft; the GUI runs full-screen during flight and the desktop launchers in `desktop/` are installed as `.desktop` files on that machine.

## Running

The runtime venv is `.venv/` and PyQt5 is *not* installed via pip — it is symlinked from the system package by `setup.sh` after `pip install -r requirements.txt`. Recreating the venv requires re-running `setup.sh` so the symlink exists.

- `./ucats` or `python instrument.py` — start the main acquisition GUI (loads `config.yaml`)
- `python instrument.py --config <file> -v -t <seconds>` — alternate config / verbose / fixed-duration run
- `python csv_plotter.py` — standalone CSV plot GUI (uses `config-plot.yaml`)
- `./calmv` — copy current `data/*.csv` and `data/*.log` into `data/cals/<YYYYMMDD>/`
- `./flightmv` — same, into `data/flights/<YYYYMMDD>/`
- `./cleanup` — delete `data/ucatsb*.csv` and `data/*.log` (run *only* after `calmv`/`flightmv`)

There is no test suite, lint config, or CI in this repo. Devices can be exercised without hardware by setting `sim_mode: true` in `config.yaml` per device — each device class generates synthetic data in that mode.

## Architecture

`instrument.py` is the orchestrator. `TDL_package` (a `QMainWindow`) reads `config.yaml`, instantiates one device object per entry under `devices:`, and runs a 950 ms `QTimer` that calls `collect_data` on every tick.

Each device class (`Aeris` in [aeris.py](aeris.py), `O3_2Btech` in [o3_sensor.py](o3_sensor.py), `Maycomm` in [h2o_sensor.py](h2o_sensor.py), `LabJackController` in [lj.py](lj.py)) follows the same shape:

- `connect()` opens the serial port (or no-ops in `sim_mode`)
- A background thread reads the device and pushes dicts onto an internal buffer behind a lock
- `start_data_collection()` / `stop_data_collection()` toggle that thread
- `get_all_data()` drains the buffer and returns a list of dict rows
- `variables` lists the column names the device produces

Each tick `collect_data` drains every device, concatenates rows into `self.streams[device_name]` (a per-device DataFrame), merges all streams on `datetime` (outer join), and appends only the *last* completed row to `data/ucatsb-YYYYMMDDHH.csv`. The same row is fanned out to UDP via `Telemetry.send_data` (which spawns a thread per send). Hourly file rotation is implicit in `create_filename()`'s `%Y%m%d%H` pattern.

### Variable prefixing

Device output column names are prefixed at runtime by the device's `data_var_prefix` from `config.yaml` (`d1_`, `d2_`, `oz_`, `w_`, `j_`). The prefix is applied where streams are merged and where telemetry/display look up variables — `telem-config.yaml`, `config-plot.yaml`, and `display_vars:` in `config.yaml` all reference the prefixed names. Variables in a device's `variables_org` list whose names contain `unused` are filtered out.

### LabJack mapping

The LabJack's I/O assignment is data-driven from `config.yaml`'s `Labjack` section: `digouts:` maps FIO/EIO/CIO addresses to logical names (e.g. `FIO4: sol_cals`), `digins:` maps inputs read each second, and `analog:` maps AIN channels with a polynomial calibration `[intercept, slope, ...]`. Calling `package.lj_digout('sol_cals', 1)` resolves the name back to the FIO address through `LabJackController.get_labjack_address`.

### Pilot watchdog, kill switch, and altitude trigger

Three concurrent monitors run alongside the main `collect_data` timer:

- **`pilot_fail_light`** — `threading.Thread` daemon. Toggles the LabJack `pilot_wd` line as a heartbeat to the external pilot-fail indicator. Holds the fail light ON until the O3 sensor reports data, blinks during a 180 s warmup window for the Aeris instruments, then trips back to fail if either Aeris or the O3 sensor produces no data for >5 consecutive ticks. Stays as a thread because it does only LabJack I/O (no Qt access) and benefits from blocking I/O staying off the GUI thread.
- **`check_pilot_switch`** — `QTimer` on the GUI thread, 100 ms tick (after a 10 s startup delay). Watches `j_pilot_power`; if it stays below 0.1 for ≥1 s, calls `display_panel.shutdown()`. Originally a worker thread but converted to a QTimer because `display_panel.shutdown()` mutates Qt widgets — calling that from a worker thread caused instability.
- **`check_altitude`** — `QTimer` on the GUI thread, 2 s tick (after a 5 s startup delay). When pressure crosses `triggers.alt_high` for 3 consecutive ticks, calls `at_altitude()` which kicks off `display_panel.sequence_start()`. When pressure crosses `triggers.alt_low` for 3 consecutive ticks, calls `below_altitude()` which calls `display_panel.sequence_idle()` + `pumps_off()`. Same QTimer rationale as above — both downstream methods touch widgets.

The `pilot_off_event`, `alt_high_event`, and `alt_low_event` `threading.Event` instances on `TDL_package` are kept for state-machine bookkeeping and (in the case of `pilot_off_event`) cooperative cancellation by `closeEvent`.

### Telemetry

`Telemetry` ([telemetry.py](telemetry.py)) sends two UDP payloads per tick using the variable lists in `telem-config.yaml`:

- `mts:` — single IP (the aircraft MTS box), prefixed `UCB,...`
- `data:` — list of ground-station IPs, prefixed `UCBdata,...`

Both payloads are CSV rows starting with the `iwg_prefix` and an ISO-like timestamp. The IP blocks in `telem-config.yaml` carry inline comments distinguishing lab-test vs. flight vs. Ellington configurations — when changing IPs, swap the active line rather than editing values, so the alternates stay documented.

### GUI and the cal/air sequence

[display_panel.py](display_panel.py) builds the operator panel: per-device value readouts (driven by `display_vars:` in `config.yaml`), the pilot indicator, and buttons for `cal0`/`cal1`/`air`, pump on/off, and the cal/air sampling sequence.

`sequence_start` is a non-blocking state machine driven by `sequence_timer` (1 Hz `QTimer`). State is held in `sequence_step` (0–3, cycling `Cal 0 → Air → Cal 1 → Air`), `sequence_remaining` (countdown in seconds), and `sequence_label`. `_sequence_advance` sets the next step's solenoid state and label; `_sequence_tick` decrements the countdown each tick and calls `_sequence_advance` at 0. `sequence_idle` stops the timer, sets `sequence_event` (for `closeEvent` compatibility), and resets the UI. Call from anywhere on the GUI thread — e.g. the sequence button, or `at_altitude` from `check_altitude`. Don't call from a worker thread; the whole point of the state machine is to stay on the GUI thread.

The earlier blocking implementation called `time.sleep` / `Event.wait` and `QApplication.processEvents()` in a `while` loop. That was deliberately avoided because mixing it with worker-thread invocations from `at_altitude` made the app unstable.

## Conventions worth knowing

- `config.yaml` keys are lowercased recursively on load (`lowercase_keys`), so code that looks up devices uses lowercase names (`aeris_co2`, `o3_sensor`, etc.) regardless of the YAML casing.
- Data files in `data/` are gitignored; never check them in. Old test data may be present locally.
- `unused/` holds older standalone scripts (`telem.py`, `listen.py`, `pilot_light.py`) kept for reference — not imported by the running app.
