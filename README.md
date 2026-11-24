# Smart Package Project - source handoff

Prepared on 2026-11-24 (Korea time). Extract the ZIP completely before running.
This is editable source, not a compiled application. All original files were left unchanged.

## Which version is included?

The installed `CSV 데이터/프로그램` folder was verified in Windows File Explorer.
The selected firmware is `firmware/PackageMonitorV2/PackageMonitorV2.ino`, modified
2026-11-23 01:04:51 KST. It is byte-identical to the development workspace firmware
(SHA-256: `4123ef4e9870c70f39ab9db721ed357ebae5d055e396089bdd6abe9c9368d1ce`, case-insensitive).
It uses Serial1 on D18/D19, PACKAGE_V2 status, explicit START, a 19-column CSV,
two independent reed inputs, two independent microswitch inputs, and transfer checksums.

The five application Python modules and Excel builder in the installed folder matched
the development workspace byte-for-byte before the portability changes below.
Their modification times range from 2026-11-23 00:57:43 to 01:04:51 KST.
The installed `test_sensor_logger.py` was stale (2026-11-22 18:50:08): it still expected
reset-based starts and the old schema. The included test file is the newer existing
development copy (2026-11-23 01:01:18), which tests PACKAGE_V2 and explicit START.
No historical backup source is included. The older Serial1/Serial2 bridge sketches
were communication diagnostics only, without this logging protocol.
This selection is based on file contents, timestamps and matching hashes; no complete
version-control history was available for the installed folder.

Shared-copy changes only:
- Default output is the `data` folder beside `sensor_logger.py`.
- `excel_runtime.json` uses `node` on PATH and the local `build_excel.mjs`.
- `sensor_export.py` resolves that relative builder path beside its own configuration.
- The newer, already existing V2 test file replaces the stale installed test copy.
Firmware, sensor algorithms, parser, GUI, translations and Excel builder are unchanged.

## Files and Python setup

- `sensor_logger.py`: entry point, serial protocol, raw preservation and export workflow.
- `sensor_gui.py`: Tkinter GUI; `sensor_i18n.py`: bilingual UI strings.
- `sensor_data.py`: 19/16/7-column validation and bilingual 25-column analysis views.
- `sensor_export.py`, `build_excel.mjs`, `excel_runtime.json`: CSV and optional Excel export.
- `test_sensor_logger.py`: current software tests (mock serial; no board required).
- `firmware/PackageMonitorV2/PackageMonitorV2.ino`: the only uploadable sketch.
- `samples`: one actual complete 15-row recording, raw and two analysis CSVs.

Install Python with Tcl/Tk support. Python 3.14.7, Tk 9.0 and pyserial 3.5 were available
on the preparation PC. The code uses standard-library modules plus pyserial;
there is no pandas dependency. From a terminal in the extracted package folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe sensor_logger.py
```

The GUI is bilingual. Select the actual COM port in its editable port field, connect,
check status, close the lid and hold the reference orientation, then press START.
STOP / Save ends the run and downloads it. Use Download again / select RUN / Download
selected to recover a prior SD file while stopped. A missing END is explicitly marked
incomplete; a truncated final row may be excluded while the original bytes are preserved.

COM4 (USB) and COM5 (paired HC-05 outgoing serial port) were local examples only.
Check Windows Device Manager / Bluetooth port settings for the recipient's assignments.
Close Arduino Serial Monitor before using the same port in Python. Baud is 9600, 8N1,
with no flow control. `--port` applies to the CLI timed run; the GUI has its own port field
and initially displays COM4. Change the save folder on launch:

```powershell
.\.venv\Scripts\python.exe sensor_logger.py --output ".\my_measurements"
```

Relative `--output` paths are relative to the terminal's working directory. There is
no folder picker in this GUI. To change the default permanently, edit DEFAULT_OUTPUT.
Outputs include KO/EN CSVs, optional XLSX, and a `원본_및_수신기록` folder for raw data,
receipt metadata and communication records. Those new records can contain local output
paths; review them separately before sending future experiment data to others.

Offline conversion (no board needed; input name must match RUNxx.CSV):

```powershell
.\.venv\Scripts\python.exe sensor_logger.py --convert samples\RUN08.CSV --output .\converted --no-explorer
```

Optional timed hardware run (actually starts and stops the connected board):

```powershell
.\.venv\Scripts\python.exe sensor_logger.py --port COM5 --stop-after 15 --output .\data
```

## Excel / Node dependency and fallback

CSV reception and export require only Python and pyserial. Both language CSVs are saved
before Excel generation. An Excel failure is recorded as `excel_error`; the CSVs and raw
data remain saved. This existing fallback is the supported portable route when the
recipient does not have the special Excel runtime. Open/import an analysis CSV in Excel
as UTF-8, mark `Experiment elapsed (HH:MM:SS.mmm)` as Text to preserve milliseconds,
adjust column widths, and use Save As XLSX if desired.

The supplied original `build_excel.mjs` requires Node.js and `@oai/artifact-tool`.
The inspected local runtime used Node v24.22.3 and @oai/artifact-tool 2.8.188; the latter
declares `private: true`. It is not assumed to be a publicly installable npm dependency.
This ZIP does not redistribute the Codex application runtime, its node_modules junction,
or binaries. Installing ordinary Node alone is NOT enough for formatted XLSX generation.
If you have an authorized compatible artifact-tool installation, make it resolvable from
the builder's directory and set `node` in `excel_runtime.json` to your Node executable
(or keep `node` on PATH). `builder` is resolved relative to this configuration file;
an absolute path is also accepted. A future portable Excel exporter can replace
`create_readable_workbook` in `sensor_export.py`; none is silently substituted here.
CSV column widths are not stored in CSV. The original workbook has Korean and English
sheets, numeric seconds and counters, text elapsed time, filters and a frozen header.

## Arduino IDE and hardware

Open `firmware/PackageMonitorV2/PackageMonitorV2.ino` in Arduino IDE. Keep the sketch
and its folder named PackageMonitorV2. Select **Arduino Mega or Mega 2560**,
processor **ATmega2560 (Mega 2560)**, and the board's USB upload port.
The local build environment has Arduino AVR Boards 1.8.8 and SD library 1.3.0.
Install SD through Library Manager if missing. SPI comes with the AVR board core;
string.h is part of the C toolchain. No third-party sensor library is required.
Compile/Verify first; uploading replaces the board firmware. Upload was not performed
while preparing this package.

| Function | Mega pin | Actual implementation / wiring |
| --- | --- | --- |
| Mini reed, lid side 1 | D2 | INPUT_PULLUP; LOW = magnet detected/closed; HIGH = open; 30 ms debounce |
| Large reed DO, lid side 2 | D3 | INPUT; HIGH = magnet detected/closed; LOW = open; 30 ms debounce |
| Shock switch | D4 | INPUT_PULLUP; groups all contact transitions; counts once after 250 ms with no further transition |
| Microswitch 1 | D5 | INPUT_PULLUP; COM to GND, NO to input; LOW = pressed; 30 ms debounce |
| Microswitch 2 | D6 | Same polarity/debounce, independent state and press counter |
| Tilt | D7 | INPUT_PULLUP; state different from START baseline stable for 500 ms increments departure count |
| CdS | A0 | INPUT; external 100 kOhm pull-up to 5 V, CdS from signal node to GND (user-specified physical wiring) |
| SD SPI | D50 / D51 / D52 / D53 | MISO / MOSI / SCK / CS; SD_CS = 53 |
| HC-05 transmit | HC-05 TXD to D19 RX1 | Serial1 receive, common GND |
| HC-05 receive | D18 TX1 to HC-05 RXD | D18 -- 1 kOhm -- RXD node; RXD node -- 2 kOhm -- GND |

The two reeds monitor opposite sides of ONE lid. `lid_open` is the OR of the two
open flags, despite the different electrical polarities. `wall_pressed` is the OR of
the two press flags. Microswitches measure contact/press events, not damage, depth or
force. Tilt is a binary departure, not an angle. Shock is an event count, not magnitude.
The pin definitions and polarities above were checked in source. External resistance,
physical continuity and actual sensor response cannot be verified by reading code.

CdS discards one ADC conversion and averages four, separated by 300 microseconds.
The baseline is measured at START; delta is current ADC minus baseline. The code
does not set a calibrated opening threshold or direction: `cds_open` is always -1.
Starting with the lid shut is a procedure, not a verified condition. Calibrate using
real closed/open/dark readings before implementing a light-based opening decision.

Power-on stays idle. START creates the first unused RUN00.CSV through RUN99.CSV,
initializes sensors, captures tilt/light baselines and resets counters. It does not
delete files or reset the board. When all 100 names exist, START fails. STOP writes
END and flushes/closes the file. Data is logged as events plus 1-second snapshots;
periodic SD flush is every 2 seconds. SNAPSHOT rows are not streamed live; retrieve
the SD file for the complete data. Power loss can lose unflushed data. Polling, SD
writes and serial traffic can miss short pulses; pending debounce/shock/tilt events
can be absent if STOP occurs before confirmation. Connecting USB may reset the board.
A power bank supplies power only; HC-05 is needed for untethered PC commands.

## Protocol (USB Serial and HC-05 Serial1)

ASCII, 9600 baud; uppercase commands terminated by LF (`\n`); CR is ignored.
Maximum 39 command characters. Responses are generally CRLF terminated.
The Python GUI requires `PROTOCOL: PACKAGE_V2` status, not the old bridge firmware.

| Command | Response / behavior |
| --- | --- |
| STATUS | PROTOCOL, STATE: STOPPED or RECORDING, FILE, SD READY, sensor states/counts, CDS CALIBRATED: 0, END_STATUS |
| START | RECORDING FILE: RUNxx.CSV and RECORDING STARTED; ALREADY RECORDING or ERROR: START FAILED as appropriate |
| STOP | Writes END if recording; RECORDING STOPPED or ALREADY STOPPED, followed by FILE |
| LIST | Only while stopped; FILES_BEGIN, RUN filenames, FILES_END |
| GET_LOG | Retrieves current in-memory filename, only while stopped |
| GET_LOG RUN08.CSV | Retrieves named SD file; use after reboot when current filename is empty |
| LIGHT | LIGHT: current_adc,baseline_or_minus_1,delta; no calibrated classification |
| HELP | Lists supported commands |

Download framing: `BEGIN_LOG RUNxx.CSV`, exact CSV bytes, an extra line delimiter,
`LOG_BYTES: <decimal>`, `LOG_FNV32: <hex>`, `END_LOG`. FNV-1a is 32-bit, initial
2166136261, multiplier 16777619. Length/hash cover only original file bytes, excluding
the extra delimiter and framing. The V2 receiver checks both. These are corruption
checks, not cryptographic authentication. START and sensor event rows can also appear
live on both serial interfaces. SD file data is the complete source of record.

## CSV schema and sample limitations

Raw file: 19 ASCII columns in exactly this order:

```text
time_ms,event,light_adc,lid_open,tilt_raw,shock_count,wall_pressed,reed16_open,reed09_open,tilt_abnormal,tilt_count,wall1_pressed,wall2_pressed,wall1_count,wall2_count,light_baseline,light_delta,run_ms,cds_open
```

`time_ms` is milliseconds since boot (32-bit wrapping); `run_ms` is milliseconds
since START (also wrapping). Neither is a calendar timestamp. `light_adc` and baseline
are 0..1023, delta is signed, counts are unsigned, state fields are 0/1, and cds_open
is -1 (unknown/unset) in this firmware. `tilt_raw` actually stores the debounced stable
digital value. `reed16_open` is D2 and `reed09_open` is D3; 16/09 are historical sensor
labels, NOT the Mega pin numbers. `shock_last_edges` exists internally but is not
part of this 19-column export.

Events: START, END, SNAPSHOT, REED16_OPEN/CLOSED, REED09_OPEN/CLOSED,
WALL1_PRESSED/RELEASED, WALL2_PRESSED/RELEASED, TILT_DETECTED/NORMAL, SHOCK_EVENT.
Python can also import the old 7- and 16-column CSVs, with unavailable sensor values
marked not recorded. That import compatibility does not make old firmware compatible
with the current live GUI protocol.

The analysis CSVs each contain the same 15 records and 25 localized columns, UTF-8 BOM.
They include seconds and HH:MM:SS.mmm since START, source event, separate reed/corner
states and counts, light baseline/delta, tilt/shock, original boot time and row number,
and END confirmation. The exact English headers are the first line of the EN sample
and `EHEAD` in sensor_data.py. Times in output filenames are PC receipt times in KST,
not experiment wall-clock timestamps. No RTC-derived experiment date is available.

`samples/RUN08.CSV` is a byte-preserving copy of the actual received raw RUN08 file
received on 2026-11-23 01:05:59 KST; only its filename was simplified. The EN and KO
samples are the matching existing analysis files, also copied without row changes.
This is the entire small run: START + 13 snapshots + END, duration 13.817 seconds.
Its light ADC is 0, baseline 1, both reed open flags are 1 and press/shock counts are 0.
It demonstrates parsing/export, not a calibrated closed-box measurement or a complete
exercise of all sensors. Synthetic sensor-event examples in unit tests are not real data.

## Validation and limits

Run software tests from the extracted package folder:

```powershell
.\.venv\Scripts\python.exe -B -m unittest -v test_sensor_logger
```

Checks performed on the shared copy on 2026-11-24:
- All 24 current unit tests passed using Python 3.14.7 (mock serial, including checksum,
  recovery, separate sensor fields, explicit START and Excel-failure CSV preservation).
- All six Python files parsed; application modules imported; Node syntax check passed.
- Mega 2560 compilation passed with AVR core 1.8.8 and SD 1.3.0: 21,014 bytes flash
  and 1,519 bytes static RAM. This is compilation only, not upload or physical testing.
- Firmware's 19-column header matched Python HEADER exactly; pins, polarities,
  timing constants and Serial1 selection were checked.
- The actual 15-row raw sample parsed; both stored analysis samples matched current
  conversion exactly. The command-line converter worked from a different folder.
- In the standalone package, automatic XLSX generation was unavailable because the
  private artifact-tool module was not bundled; the actual fallback preserved both
  matching CSVs and raw bytes successfully. Formatted XLSX was not validated here.
- Original selected source/sample hashes remained unchanged. ZIP member bytes, names
  and CRC integrity were verified; only the 14 listed package files are included.

Earlier local evidence records USB and COM5 STATUS/LIST/named GET_LOG length/FNV32
checks for the V2 work, with USB power. It is historical evidence, not a new test of
this ZIP or proof of all physical sensor responses. This packaging session did not
connect serial ports, start/stop the board, upload firmware or test battery-only use.
Actual wiring, individual sensor transitions, closed/open/dark CdS calibration and
power-bank operation still require a bench check by the team.

Caches, backups, shortcuts, large logs, receipt JSON with personal paths, runtimes,
compiled firmware and original bulk data are excluded. Review of the included text
files found no credentials or personal user-directory paths. Bluetooth pairing secrets
and account credentials are not needed in this source package.
