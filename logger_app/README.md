# Shared sensor logger (Windows and macOS)

This folder contains the laboratory logger with small operating-system adaptations.
The existing application, `analysis/`, arrival-marking implementation, and firmware
at the repository root are preserved. This folder does not integrate `ARRIVED` or
automatically run the existing analysis scripts.

## What it does

- USB or an available Bluetooth serial port, at 9600 baud.
- Start, stop/save, check status, and download a previous SD recording.
- Live sensor readings during recording and sensor testing, with reed,
  microswitch, tilt, and shock counts.
- One `.xlsx` workbook per saved run, with `한국어` and `English` sheets and a
  final cumulative-count row. Raw transfer data and receipt metadata are also
  retained for recovery and analysis. No Node or Microsoft Excel is needed to
  create the workbook.
- SD capacity checking and bilingual problem/solution messages.
- Open the output location or open the workbook using the OS default application.
  Viewing `.xlsx` requires a compatible viewer, such as Excel or Numbers.

## Windows

Keep `Start_Sensor_UI_With_Excel.exe` beside **all five** `sensor_*.py` modules
and double-click it. Python and Excel-writing libraries are included in the EXE.
Source edits take effect after restarting it. The EXE alone falls back to an older
embedded snapshot; send this complete folder to share the current version.

## macOS: one-time setup

The Windows EXE does not run on macOS. Use the same five Python sources instead.
Install a supported Python 3.12 or newer with working Tcl/Tk. The standard
[python.org macOS installer](https://docs.python.org/3/using/mac.html) supplies
universal2 builds for supported Apple Silicon and Intel Macs.

In Terminal, change to **this `logger_app` folder**, then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m tkinter
```

Close the small Tk test window. If Tk cannot be imported or its window does not
open, repair the Python/Tk installation before running the logger; `pip install
tkinter` is not a replacement for a working Tcl/Tk installation.

Start the application:

```sh
.venv/bin/python -B sensor_logger.py
```

After setup, `Start_Sensor_UI_Mac.command` opens the same application by
double-clicking in Finder. If the download lost its executable permission, run
`chmod +x Start_Sensor_UI_Mac.command` once from this folder.

The macOS launcher opens Terminal while the UI runs. It uses the local `.venv`
and does not automatically install packages or change the system Python.

## Connect and record

1. Use the compatible board firmware described below. Power-on stays idle.
2. Connect USB, or pair HC-05 and use its serial port if macOS exposes one.
   Pairing alone does not guarantee an accessible serial port. USB is the
   simplest initial check; Bluetooth must be checked on the actual Mac.
3. Select the board's actual port. macOS commonly exposes `/dev/cu.usbserial...`,
   `/dev/cu.usbmodem...`, or a Bluetooth `/dev/cu....` port. The list refreshes
   when opened; the field also accepts a typed path. Close other serial monitors.
4. Connect, check status, and either test sensors or press START. STOP saves the
   run. Sensor testing is separate from creating a recorded run.
5. Check SD capacity while stopped. Keep the connection active while it scans.

Output defaults to `data/` beside the sources or EXE. To choose another location
and optionally preselect a port:

```sh
.venv/bin/python -B sensor_logger.py --output "$HOME/Documents/PackageSensorData" --port /dev/cu.usbserial-YOUR_BOARD
```

Use an existing, writable location or one Python can create. The example port is
a placeholder, not an actual device. For a timed CLI recording on macOS,
explicitly provide `--port`; the GUI never starts recording just by connecting.

## Board firmware required for the complete feature set

The optional `firmware/PackageMonitorV2/PackageMonitorV2.ino` in **this folder**
is the current laboratory firmware. It supports `LIVE` and `SDINFO`; the older
firmware at the repository root does not. Uploading changes the board program,
so a board already running this version does not need another upload.

For a board that needs updating, open this sketch in Arduino IDE, select Arduino
Mega or Mega 2560 / ATmega2560 and the board's USB port, install the Arduino SD
library (verified with 1.3.0), and upload over USB. SPI is included with the AVR
board core (verified with 1.8.8). Close serial programs before uploading.

`STATUS` identifies this version as `PACKAGE_V2_SD_CAPACITY_20261127`, with
`LIVE PROTOCOL: 1` and `CAPACITY PROTOCOL: 1`. The PC and Mac use the same serial
commands; the firmware is not operating-system-specific.

The current laboratory setup uses D2 mini reed (LOW = closed), D4 shock,
D5/D6 microswitches (LOW = pressed), D7 tilt, A0 CdS, SD CS D53 with SPI D50-53,
and HC-05 on Serial1 D18/D19. The D3 large reed (HIGH = closed) is also filtered
and logged; the raw `lid_open` field is the OR of both reed open flags. The
current UI and workbook report D2. Match the actual wiring before using this
version on another board.
Sensor timing and counting logic have not been changed for macOS.

## Analysis and collaboration

Use the preserved 19-column raw recording in `data/원본_및_수신기록/` for the existing
analysis parser; the simplified seven-column workbook is for reading, not its
analysis input. The existing analysis has separate dependencies (including
pandas) and its own arrival logic. Those are not installed or replaced here.

Keep generated data, `.venv`, caches, and private experiment logs out of commits.
The local `.gitignore` covers the default output location. Review custom output
folders separately before sharing them.

## Verification limits

The original laboratory version was exercised on Windows with the actual board,
including Bluetooth capacity checking. The platform adaptations are checked by
software tests, including simulated macOS port lists and file-opening commands.
No physical Mac or macOS sensor connection was available for this change: UI
appearance, driver behavior, HC-05 availability, and actual Mac recording still
require a check on the teammate's computer. This is source-based macOS support,
not a bundled or signed Mac application.
