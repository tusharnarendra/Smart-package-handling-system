
#include <SPI.h>
#include <SD.h>
#include <string.h>

// ========================================
// 1. PIN SETTINGS - USER VERIFIED
// ========================================

const byte REED16_PIN = 2;     // Mini reed switch
const byte REED09_PIN = 3;     // Large reed module DO
const byte SHOCK_PIN  = 4;
const byte WALL1_PIN  = 5;
const byte WALL2_PIN  = 6;
const byte TILT_PIN   = 7;
const byte LIGHT_PIN  = A0;

const byte SD_CS = 53;

// HC-05:
// TXD -> MEGA D19 (RX1)
// RXD <- MEGA D18 (TX1) through divider

// Both reeds monitor opposite sides of the same lid.
// Either missing magnet indicates possible opening on that side.

// USB debug output:
// Event rows are shown on the USB serial monitor.
// SNAPSHOT rows are saved to SD but not printed live.
const bool USB_EVENT_OUTPUT = true;

// ========================================
// 2. TIMING SETTINGS (ms)
// ========================================

const unsigned long REED_DEBOUNCE_MS = 30;
const unsigned long WALL_DEBOUNCE_MS = 30;
const unsigned long TILT_STABLE_MS   = 500;
const unsigned long SHOCK_QUIET_MS   = 250;

const unsigned long SNAPSHOT_MS = 1000;
const unsigned long FLUSH_MS    = 2000;

// ========================================
// 3. SENSOR STATE STRUCTURE
// ========================================

struct DigitalFilter {
  byte pin;
  int raw;
  int stable;
  unsigned long rawChangedAt;
  unsigned long stableRequiredMs;
};

DigitalFilter reed16;
DigitalFilter reed09;
DigitalFilter wall1;
DigitalFilter wall2;
DigitalFilter tilt;

int tiltBaseline = HIGH;

unsigned long tiltCount = 0;
unsigned long wall1Count = 0;
unsigned long wall2Count = 0;
unsigned long shockCount = 0;

int shockRaw = HIGH;
bool shockBurstActive = false;

unsigned long shockChangedAt = 0;
unsigned long shockBurstEdges = 0;
unsigned long shockLastEdges = 0;

// ========================================
// 4. SD / COMMUNICATION
// ========================================

File logFile;
char fileName[13] = "";

bool sdReady = false;
bool recording = false;
bool arrivalMarked = false;

unsigned long recordStartedAt = 0;
int lightBaseline = 0;
bool baselineValid = false;
// CDS classification is intentionally disabled until measured calibration.
// -1 means unknown, never "closed". Record ADC and signed delta for calibration.
const int CDS_UNCALIBRATED = -1;
unsigned long lastSnapshotAt = 0;
unsigned long lastFlushAt = 0;

char usbBuffer[40] = "";
char btBuffer[40] = "";

byte usbLength = 0;
byte btLength = 0;

// ========================================
// 5. DIGITAL FILTER FUNCTIONS
// ========================================

void initFilter(
  DigitalFilter &sensor,
  byte pin,
  byte inputMode,
  unsigned long stableMs
) {
  sensor.pin = pin;
  sensor.stableRequiredMs = stableMs;

  pinMode(pin, inputMode);

  sensor.raw = digitalRead(pin);
  sensor.stable = sensor.raw;
  sensor.rawChangedAt = millis();
}

bool updateFilter(
  DigitalFilter &sensor,
  unsigned long now
) {
  int reading = digitalRead(sensor.pin);

  if (reading != sensor.raw) {
    sensor.raw = reading;
    sensor.rawChangedAt = now;
  }

  if (reading != sensor.stable &&
      now - sensor.rawChangedAt >=
      sensor.stableRequiredMs) {

    sensor.stable = reading;
    return true;
  }

  return false;
}

// ========================================
// 6. INITIALIZE ALL SENSORS
// ========================================

void initializeSensors() {

  // #16: magnet near = LOW (CLOSED)
  initFilter(
    reed16,
    REED16_PIN,
    INPUT_PULLUP,
    REED_DEBOUNCE_MS
  );

  // #09: magnet near = HIGH (CLOSED)
  // The module has its own digital output.
  initFilter(
    reed09,
    REED09_PIN,
    INPUT,
    REED_DEBOUNCE_MS
  );

  // Wall switches: COM -> GND, NO -> pin
  initFilter(
    wall1,
    WALL1_PIN,
    INPUT_PULLUP,
    WALL_DEBOUNCE_MS
  );

  initFilter(
    wall2,
    WALL2_PIN,
    INPUT_PULLUP,
    WALL_DEBOUNCE_MS
  );

  // Tilt: 500 ms state stability
  initFilter(
    tilt,
    TILT_PIN,
    INPUT_PULLUP,
    TILT_STABLE_MS
  );

  tiltBaseline = tilt.stable;

  pinMode(SHOCK_PIN, INPUT_PULLUP);
  shockRaw = digitalRead(SHOCK_PIN);

  shockBurstActive = false;
  shockChangedAt = millis();
  shockBurstEdges = 0;
  shockLastEdges = 0;

  tiltCount = 0;
  wall1Count = 0;
  wall2Count = 0;
  shockCount = 0;

  pinMode(LIGHT_PIN, INPUT);
}

// ========================================
// 7. STATE INTERPRETATION
// ========================================

bool reed16Open() {
  return reed16.stable == HIGH;
}

bool reed09Open() {
  return reed09.stable == LOW;
}

bool lidOpen() {
  return reed16Open() || reed09Open();
}

bool wall1Pressed() {
  return wall1.stable == LOW;
}

bool wall2Pressed() {
  return wall2.stable == LOW;
}

bool anyWallPressed() {
  return wall1Pressed() || wall2Pressed();
}

bool tiltAbnormal() {
  return tilt.stable != tiltBaseline;
}

// Read CDS a few times and average.
// The first conversion is discarded.
int readLightADC() {
  analogRead(LIGHT_PIN);

  unsigned long sum = 0;

  for (byte i = 0; i < 4; i++) {
    delayMicroseconds(300);
    sum += analogRead(LIGHT_PIN);
  }

  return (int)(sum / 4);
}

// ========================================
// 8. WRITE A CSV ROW
// ========================================

void logRow(const char *eventName) {

  if (!recording || !logFile) return;

  char row[240];
  unsigned long timestamp = millis();
  if (strcmp(eventName, "START") == 0) recordStartedAt = timestamp;
  int light = readLightADC();
  snprintf(row, sizeof(row),
    "%lu,%s,%u,%u,%d,%lu,%u,%u,%u,%u,%lu,%u,%u,%lu,%lu,%d,%d,%lu,%d",
    timestamp, eventName, (unsigned int)light,
    (unsigned int)(reed16Open() || reed09Open()), tilt.stable, shockCount,
    (unsigned int)anyWallPressed(), (unsigned int)reed16Open(), (unsigned int)reed09Open(),
    (unsigned int)tiltAbnormal(), tiltCount,
    (unsigned int)wall1Pressed(), (unsigned int)wall2Pressed(), wall1Count, wall2Count,
    lightBaseline, light - lightBaseline, timestamp - recordStartedAt, CDS_UNCALIBRATED);

  logFile.println(row);

  if (USB_EVENT_OUTPUT &&
      strcmp(eventName, "SNAPSHOT") != 0) {
    Serial.println(row);
  }
  if (strcmp(eventName, "SNAPSHOT") != 0) Serial1.println(row);
}

// ========================================
// 9. CREATE A NEW SD FILE
// ========================================

bool startRecording() {

  if (!sdReady || recording) return false;

  bool nameFound = false;

  // Prevent overwriting existing files
  for (int i = 0; i < 100; i++) {

    snprintf(
      fileName,
      sizeof(fileName),
      "RUN%02d.CSV",
      i
    );

    if (!SD.exists(fileName)) {
      nameFound = true;
      break;
    }
  }

  if (!nameFound) return false;

  logFile = SD.open(fileName, FILE_WRITE);

  if (!logFile) return false;

  // Recalibrate tilt baseline and reset counters
  initializeSensors();
  arrivalMarked = false;
  lightBaseline = readLightADC();
  baselineValid = true;

  logFile.println(
    F("time_ms,event,light_adc,lid_open,"
      "tilt_raw,shock_count,wall_pressed,"
      "reed16_open,reed09_open,tilt_abnormal,"
      "tilt_count,wall1_pressed,wall2_pressed,"
      "wall1_count,wall2_count,light_baseline,light_delta,run_ms,cds_open")
  );

  recording = true;

  logRow("START");
  logFile.flush();

  lastSnapshotAt = millis();
  lastFlushAt = millis();

  Serial.print(F("RECORDING FILE: "));
  Serial.println(fileName);

  Serial1.print(F("RECORDING FILE: "));
  Serial1.println(fileName);

  return true;
}

// ========================================
// 10. STOP RECORDING
// ========================================

void stopRecording() {

  if (!recording) return;

  logRow("END");

  logFile.flush();
  logFile.close();

  recording = false;
}

// ========================================
// 11. SHOCK DETECTION
// ========================================

void updateShock(unsigned long now) {

  int reading = digitalRead(SHOCK_PIN);

  // Count raw contact transitions
  if (reading != shockRaw) {

    shockRaw = reading;

    if (!shockBurstActive) {
      shockBurstActive = true;
      shockBurstEdges = 0;
    }

    shockBurstEdges++;
    shockChangedAt = now;
  }

  // Finalize one event after 250 ms of silence
  if (shockBurstActive &&
      now - shockChangedAt >= SHOCK_QUIET_MS) {

    shockBurstActive = false;

    shockCount++;
    shockLastEdges = shockBurstEdges;

    logRow("SHOCK_EVENT");
  }
}

// ========================================
// 12. OTHER SENSOR EVENTS
// ========================================

void updateSensorEvents(unsigned long now) {

  // The two reeds monitor opposite sides of the same lid.
  if (updateFilter(reed16, now)) logRow(reed16Open() ? "REED16_OPEN" : "REED16_CLOSED");
  if (updateFilter(reed09, now)) logRow(reed09Open() ? "REED09_OPEN" : "REED09_CLOSED");

  // Wall microswitch 1 (D5)
  if (updateFilter(wall1, now)) {

    if (wall1Pressed()) {
      wall1Count++;
      logRow("WALL1_PRESSED");
    } else {
      logRow("WALL1_RELEASED");
    }
  }

  // Wall microswitch 2 (D6)
  if (updateFilter(wall2, now)) {

    if (wall2Pressed()) {
      wall2Count++;
      logRow("WALL2_PRESSED");
    } else {
      logRow("WALL2_RELEASED");
    }
  }

  // Tilt switch (D7)
  if (updateFilter(tilt, now)) {

    if (tiltAbnormal()) {
      tiltCount++;
      logRow("TILT_DETECTED");
    } else {
      logRow("TILT_NORMAL");
    }
  }
}

// ========================================
// 13. CHECK A RUN FILENAME
// ========================================

bool validRunName(const char *s) {

  // Example: RUN03.CSV (8.3 filename)
  if (strlen(s) != 9) return false;

  return (
    s[0] == 'R' &&
    s[1] == 'U' &&
    s[2] == 'N' &&
    s[3] >= '0' && s[3] <= '9' &&
    s[4] >= '0' && s[4] <= '9' &&
    s[5] == '.' &&
    s[6] == 'C' &&
    s[7] == 'S' &&
    s[8] == 'V'
  );
}

// ========================================
// 14. LIST SD FILES
// ========================================

void listFiles(Stream &port) {

  if (recording) {
    port.println(F("ERROR: STOP FIRST"));
    return;
  }

  File root = SD.open("/");

  if (!root) {
    port.println(F("ERROR: ROOT OPEN"));
    return;
  }

  port.println(F("FILES_BEGIN"));

  while (true) {

    File entry = root.openNextFile();

    if (!entry) break;

    if (!entry.isDirectory() &&
        validRunName(entry.name())) {
      port.println(entry.name());
    }

    entry.close();
  }

  root.close();

  port.println(F("FILES_END"));
}

// ========================================
// 15. SEND A SAVED CSV FILE
// ========================================

void sendLog(
  Stream &port,
  const char *requestedFile
) {

  if (recording) {
    port.println(F("ERROR: STOP FIRST"));
    return;
  }

  const char *target = fileName;

  if (requestedFile[0] != '\0') {
    target = requestedFile;
  }

  if (!validRunName(target)) {
    port.println(F("ERROR: INVALID FILE NAME"));
    return;
  }

  File readFile = SD.open(target, FILE_READ);

  if (!readFile) {
    port.println(F("ERROR: FILE NOT FOUND"));
    return;
  }

  port.print(F("BEGIN_LOG "));
  port.println(target);

  byte buffer[32];
  unsigned long sentBytes = 0;
  uint32_t hash = 2166136261UL;

  while (readFile.available()) {

    int n = readFile.read(
      buffer,
      sizeof(buffer)
    );

    if (n <= 0) break;

    for (int i = 0; i < n; i++) { hash ^= buffer[i]; hash *= 16777619UL; }
    sentBytes += n;
    port.write(buffer, (size_t)n);
  }

  readFile.close();

  // Delimiter also separates a power-cut final row without a newline.
  port.println();
  port.print(F("LOG_BYTES: ")); port.println(sentBytes);
  port.print(F("LOG_FNV32: ")); port.println(hash, HEX);
  port.println(F("END_LOG"));
}

// ========================================
// 16. STATUS REPORT
// ========================================

void printStatus(Stream &port) {

  port.println(F("PROTOCOL: PACKAGE_V2"));
  port.print(F("STATE: "));
  port.println(
    recording ? "RECORDING" : "STOPPED"
  );

  port.print(F("FILE: "));
  port.println(fileName[0] ? fileName : "-");
  port.print(F("SD READY: "));
  port.println(sdReady ? 1 : 0);

  port.print(F("LIGHT ADC: "));
  port.println(readLightADC());

  port.print(F("LID OPEN: "));
  port.println((int)lidOpen());

  port.print(F("REED16 OPEN: "));
  port.println((int)reed16Open());

  port.print(F("REED09 OPEN: "));
  port.println((int)reed09Open());

  port.print(F("TILT RAW: "));
  port.println(tilt.stable);

  port.print(F("TILT ABNORMAL: "));
  port.println((int)tiltAbnormal());

  port.print(F("TILT COUNT: "));
  port.println(tiltCount);

  port.print(F("SHOCK COUNT: "));
  port.println(shockCount);

  port.print(F("WALL1 PRESSED: "));
  port.println((int)wall1Pressed());

  port.print(F("WALL1 COUNT: "));
  port.println(wall1Count);

  port.print(F("WALL2 PRESSED: "));
  port.println((int)wall2Pressed());

  port.print(F("WALL2 COUNT: "));
  port.println(wall2Count);
  port.print(F("ARRIVED: "));
  port.println(arrivalMarked ? 1 : 0);
  port.println(F("CDS CALIBRATED: 0"));
  port.println(F("END_STATUS"));
}

// ========================================
// 17. HANDLE SERIAL COMMANDS
// ========================================

void handleCommand(
  Stream &port,
  char *command
) {

  if (command[0] == '\0') return;

  if (strcmp(command, "STATUS") == 0) {

    printStatus(port);
  }

  else if (strcmp(command, "LIGHT") == 0) {
    int current = readLightADC();
    port.print(F("LIGHT: ")); port.print(current); port.print(',');
    port.print(baselineValid ? lightBaseline : -1); port.print(',');
    port.println(baselineValid ? current - lightBaseline : 0);
  }

  else if (strcmp(command, "STOP") == 0) {

    if (recording) {
      stopRecording();
      port.println(F("RECORDING STOPPED"));
    } else {
      port.println(F("ALREADY STOPPED"));
    }

    port.print(F("FILE: "));
    port.println(fileName[0] ? fileName : "-");
  }

  else if (strcmp(command, "START") == 0) {

    if (recording) {
      port.println(F("ALREADY RECORDING"));
    }

    else if (startRecording()) {
      port.println(F("RECORDING STARTED"));
    }

    else {
      port.println(F("ERROR: START FAILED"));
    }
  }

  else if (strcmp(command, "LIST") == 0) {

    if (sdReady) {
      listFiles(port);
    } else {
      port.println(F("ERROR: SD NOT READY"));
    }
  }

  else if (
    strncmp(command, "GET_LOG", 7) == 0 &&
    (command[7] == '\0' || command[7] == ' ')
  ) {

    if (!sdReady) {
      port.println(F("ERROR: SD NOT READY"));
      return;
    }

    char *requested = command + 7;

    while (*requested == ' ') {
      requested++;
    }

    sendLog(port, requested);
  }

  else if (strcmp(command, "ARRIVED") == 0) {

    if (!recording) {
      port.println(F("ERROR: NOT RECORDING"));
    }
    else if (arrivalMarked) {
      port.println(F("ALREADY ARRIVED"));
    }
    else {
      arrivalMarked = true;
      logRow("ARRIVED");
      logFile.flush();
      port.println(F("ARRIVAL MARKED"));
    }
  }

  else if (strcmp(command, "HELP") == 0) {

    port.println(F("STATUS"));
    port.println(F("LIGHT"));
    port.println(F("STOP"));
    port.println(F("START"));
    port.println(F("LIST"));
    port.println(F("GET_LOG"));
    port.println(F("GET_LOG RUN00.CSV"));
    port.println(F("ARRIVED"));
  }

  else {
    port.println(F("UNKNOWN COMMAND"));
  }
}

// ========================================
// 18. RECEIVE USB / BLUETOOTH COMMANDS
// ========================================

void readCommands(
  Stream &port,
  char *buffer,
  byte &length
) {

  while (port.available()) {

    char c = (char)port.read();

    if (c == '\r') continue;

    if (length == 255) {
      if (c == '\n') length = 0;
      continue;
    }

    if (c == '\n') {

      buffer[length] = '\0';

      handleCommand(port, buffer);

      length = 0;
    }

    else if (length < 39) {
      buffer[length++] = c;
    }

    else {
      length = 255;
      port.println(F("ERROR: COMMAND TOO LONG"));
    }
  }
}

// ========================================
// 19. SETUP
// ========================================

void setup() {

  Serial.begin(9600);    // USB
  Serial1.begin(9600);   // HC-05 D18/D19

  pinMode(SD_CS, OUTPUT);
  pinMode(LIGHT_PIN, INPUT);

  Serial.println(F("=== PACKAGE MONITOR ==="));
  Serial1.println(F("=== PACKAGE MONITOR ==="));

  // Keep the package still during startup.
  delay(2000);

  initializeSensors();

  if (!SD.begin(SD_CS)) {

    Serial.println(F("ERROR: SD INIT FAILED"));
    Serial1.println(F("ERROR: SD INIT FAILED"));

    return;
  }

  sdReady = true;

  // Power-on/reconnect never starts a run. START is an explicit user action.
  Serial.println(F("PROTOCOL: PACKAGE_V2"));
  Serial.println(F("STATE: STOPPED"));
  Serial.println(F("READY: SEND START"));
  Serial1.println(F("PROTOCOL: PACKAGE_V2"));
  Serial1.println(F("STATE: STOPPED"));
  Serial1.println(F("READY: SEND START"));
}

// ========================================
// 20. MAIN LOOP
// ========================================

void loop() {

  // Read USB & Bluetooth commands
  readCommands(
    Serial,
    usbBuffer,
    usbLength
  );

  readCommands(
    Serial1,
    btBuffer,
    btLength
  );

  if (!recording) {
    unsigned long idleNow = millis();
    updateFilter(reed16, idleNow); updateFilter(reed09, idleNow);
    updateFilter(wall1, idleNow); updateFilter(wall2, idleNow); updateFilter(tilt, idleNow);
    return;
  }

  unsigned long now = millis();

  // Poll shock first to reduce missed pulses
  updateShock(now);

  // Check all other digital sensors
  updateSensorEvents(now);

  // Save every sensor state once per second
  if (now - lastSnapshotAt >= SNAPSHOT_MS) {

    lastSnapshotAt = now;

    logRow("SNAPSHOT");
  }

  // Periodically flush SD write buffer
  if (now - lastFlushAt >= FLUSH_MS) {

    lastFlushAt = now;

    logFile.flush();
  }
}
