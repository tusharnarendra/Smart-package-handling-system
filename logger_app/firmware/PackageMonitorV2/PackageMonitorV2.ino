
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

const unsigned long REED_DEBOUNCE_MS = 200;
const unsigned long WALL_DEBOUNCE_MS = 10;
const unsigned long TILT_STABLE_MS   = 100;
const unsigned long SHOCK_QUIET_MS   = 250;
const unsigned long LIGHT_SAMPLE_MS = 100;
const unsigned long LIGHT_UPDATE_MS = 1000;

const unsigned long SNAPSHOT_MS = 1000;

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
// Idle-only diagnostic counter. Never changes an experiment's CSV shock count.
unsigned long shockTestCount = 0;

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
bool sdInitialized = false;
bool recording = false;
const char *sdLastError = "NONE";
unsigned long sdLastWriteMs = 0;
unsigned long sdMaxWriteMs = 0;

unsigned long recordStartedAt = 0;
int lightBaseline = 0;
bool baselineValid = false;
bool lightSamplerReady = false;
int lightCachedADC = 0;
unsigned long lightSampleAt = 0;
unsigned long lightWindowAt = 0;
unsigned long lightWindowSum = 0;
unsigned int lightWindowSamples = 0;
// CDS classification is intentionally disabled until measured calibration.
// -1 means unknown, never "closed". Record ADC and signed delta for calibration.
const int CDS_UNCALIBRATED = -1;
unsigned long lastSnapshotAt = 0;

char usbBuffer[40] = "";
char btBuffer[40] = "";

byte usbLength = 0;
byte btLength = 0;

// Optional idle preview: complete state snapshots, separate from SD CSV rows.
// A client renews LIVE ON at least every 5 s; no unsolicited output otherwise.
const unsigned long LIVE_TTL_MS = 5000;
const unsigned long LIVE_HEARTBEAT_MS = 500;
const byte LIVE_QUEUE_SIZE = 16;

struct LiveFrame {
  unsigned long sequence;
  unsigned long timestamp;
  unsigned long shockTests;
  unsigned int light;
  byte bits;
};

struct LiveClient {
  LiveFrame frames[LIVE_QUEUE_SIZE];
  unsigned long renewedAt;
  unsigned long dropped;
  byte head;
  byte count;
  bool enabled;
};

LiveClient usbLive = {};
LiveClient btLive = {};
unsigned long liveSequence = 0;
unsigned long lastLiveSnapshotAt = 0;

// SDINFO uses the SD library's existing card, but never its shared cache.
// A failed earlier write can leave that cache dirty; even a new SdVolume's
// init/cacheClear could flush it. Raw card reads avoid all such write retries.
const uint32_t CAPACITY_TIMEOUT_MS = 45000UL;
uint8_t capacityBlock[512];
uint8_t capacityMirror[512];
uint32_t capacityStartedAt = 0;
uint32_t capacityScanned = 0;
bool capacityAbort = false;
char capacityCommand[40] = "";
uint8_t capacityCommandLength = 0;
const char *capacityStage = "IDLE";
const char *capacityFailure = "NONE";

struct CapacityGeometry {
  uint32_t bootBlock, totalBlocks, clusters, fatStart, fatBlocks, dataStart;
  uint8_t type, clusterBlocks, copies, activeFat;
  bool mirrored;
};

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

void resetShockBurst() {
  // A burst begun in one mode must not be attributed to the next mode.
  shockRaw = digitalRead(SHOCK_PIN);
  shockBurstActive = false;
  shockChangedAt = millis();
  shockBurstEdges = 0;
  shockLastEdges = 0;
}

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

  // Tilt: 100 ms state stability
  initFilter(
    tilt,
    TILT_PIN,
    INPUT_PULLUP,
    TILT_STABLE_MS
  );

  tiltBaseline = tilt.stable;

  pinMode(SHOCK_PIN, INPUT_PULLUP);
  resetShockBurst();

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

// One raw sample is a four-conversion mean; discard the first conversion.
int readLightRawADC() {
  analogRead(LIGHT_PIN);

  unsigned long sum = 0;

  for (byte i = 0; i < 4; i++) {
    delayMicroseconds(300);
    sum += analogRead(LIGHT_PIN);
  }

  return (int)(sum / 4);
}

void initializeLightSampler(unsigned long now) {
  // A real initial value is available immediately, before the first 1 s window.
  lightCachedADC = readLightRawADC();
  lightSampleAt = now;
  lightWindowAt = now;
  lightWindowSum = lightCachedADC;
  lightWindowSamples = 1;
  lightSamplerReady = true;
}

bool updateLightSampler(unsigned long now) {
  if (!lightSamplerReady) {
    initializeLightSampler(now);
    return true;
  }

  bool published = false;
  // Publish the completed window before adding a sample for the new window.
  // All elapsed-time comparisons are unsigned so millis() rollover is safe.
  if (now - lightWindowAt >= LIGHT_UPDATE_MS) {
    if (lightWindowSamples > 0)
      lightCachedADC = (int)(lightWindowSum / lightWindowSamples);
    lightWindowAt = now;
    lightWindowSum = 0;
    lightWindowSamples = 0;
    published = true;
  }

  if (now - lightSampleAt >= LIGHT_SAMPLE_MS) {
    // Read once when due; delayed loops must not fabricate catch-up samples.
    lightSampleAt = now;
    lightWindowSum += readLightRawADC();
    lightWindowSamples++;
  }
  return published;
}

int readLightADC() {
  if (!lightSamplerReady) initializeLightSampler(millis());
  return lightCachedADC;
}

// ========================================
// 8. WRITE A CSV ROW
// ========================================

void reportStorageError(const char *message) {
  Serial.print(F("ERROR: ")); Serial.println(message);
  Serial1.print(F("ERROR: ")); Serial1.println(message);
}

void failStorage(const char *message) {
  // Latch failure before cleanup: no later sensor or snapshot retries the write.
  recording = false;
  sdReady = false;
  sdLastError = message;
  clearLiveQueues();
  resetShockBurst();
  reportStorageError(message);
  // File::close has no result; it may attempt one final sync. Never loop/retry.
  if (logFile) logFile.close();
}

bool writeLogBytes(const char *data, size_t length) {
  if (!sdReady || !logFile) return false;
  logFile.clearWriteError();
  unsigned long writeStartedAt = millis();
  size_t written = logFile.write((const uint8_t *)data, length);
  sdLastWriteMs = millis() - writeStartedAt;
  if (sdLastWriteMs > sdMaxWriteMs) sdMaxWriteMs = sdLastWriteMs;
  // O_SYNC makes SdFile::write return failure when its sync fails too.
  if (written != length || logFile.getWriteError()) {
    failStorage("SD WRITE FAILED");
    return false;
  }
  return true;
}

bool logRow(const char *eventName) {

  if (!recording || !logFile) return false;

  char row[240];
  unsigned long timestamp = millis();
  if (strcmp(eventName, "START") == 0) recordStartedAt = timestamp;
  int light = readLightADC();
  int length = snprintf(row, sizeof(row),
    "%lu,%s,%u,%u,%d,%lu,%u,%u,%u,%u,%lu,%u,%u,%lu,%lu,%d,%d,%lu,%d\r\n",
    timestamp, eventName, (unsigned int)light,
    (unsigned int)(reed16Open() || reed09Open()), tilt.stable, shockCount,
    (unsigned int)anyWallPressed(), (unsigned int)reed16Open(), (unsigned int)reed09Open(),
    (unsigned int)tiltAbnormal(), tiltCount,
    (unsigned int)wall1Pressed(), (unsigned int)wall2Pressed(), wall1Count, wall2Count,
    lightBaseline, light - lightBaseline, timestamp - recordStartedAt, CDS_UNCALIBRATED);

  if (length <= 0 || length >= (int)sizeof(row)) {
    failStorage("LOG ROW TOO LONG");
    return false;
  }

  // Send observed events before a possibly slow SD operation. A received row
  // is not proof of SD persistence; any write failure is reported immediately.
  if (USB_EVENT_OUTPUT &&
      strcmp(eventName, "SNAPSHOT") != 0) {
    Serial.write((const uint8_t *)row, length);
  }
  if (strcmp(eventName, "SNAPSHOT") != 0)
    Serial1.write((const uint8_t *)row, length);
  // Include CRLF in one write so O_SYNC does not sync the newline separately.
  return writeLogBytes(row, (size_t)length);
}

// ========================================
// 9. CREATE A NEW SD FILE
// ========================================

bool scanRunDirectory(bool *occupied, bool filesOnly) {
  File root = SD.open("/", FILE_READ);
  if (!root) {
    failStorage("SD ROOT READ FAILED");
    return false;
  }
  // SD.exists(false) cannot distinguish absence from I/O failure. Read the
  // directory explicitly so an error is never interpreted as an empty card.
  while (true) {
    dir_t entry;
    int count = root.read(&entry, sizeof(entry));
    if (count == 0) break;
    if (count != (int)sizeof(entry)) {
      root.close();
      failStorage("SD ROOT READ FAILED");
      return false;
    }
    if (entry.name[0] == DIR_NAME_FREE) break;
    if (entry.name[0] == DIR_NAME_DELETED || DIR_IS_LONG_NAME(&entry)) continue;
    if (filesOnly && !DIR_IS_FILE(&entry)) continue;
    const uint8_t *name = entry.name;
    if (name[0] == 'R' && name[1] == 'U' && name[2] == 'N' &&
        name[3] >= '0' && name[3] <= '9' && name[4] >= '0' && name[4] <= '9' &&
        name[5] == ' ' && name[6] == ' ' && name[7] == ' ' &&
        name[8] == 'C' && name[9] == 'S' && name[10] == 'V') {
      occupied[(name[3] - '0') * 10 + name[4] - '0'] = true;
    }
  }
  root.close();
  return true;
}

bool chooseRunName(char *candidate, size_t capacity) {
  bool occupied[100] = {};
  if (!scanRunDirectory(occupied, false)) return false;
  for (int i = 0; i < 100; i++) {
    if (!occupied[i]) {
      snprintf(candidate, capacity, "RUN%02d.CSV", i);
      return true;
    }
  }
  reportStorageError("RUN NAMES EXHAUSTED");
  return false;
}

bool startRecording() {
  if (recording) return false;
  if (!sdReady) {
    reportStorageError("SD NOT READY");
    return false;
  }

  char candidate[13] = "";
  if (!chooseRunName(candidate, sizeof(candidate))) return false;
  // Exclusive create protects every existing file, even if the listing raced.
  // O_SYNC exposes sync failures through the checked write result. It adds SD
  // I/O per row; this design does not guarantee a fixed sampling latency.
  logFile = SD.open(candidate, O_READ | O_WRITE | O_CREAT | O_EXCL | O_SYNC);
  if (!logFile) {
    failStorage("SD CREATE FAILED");
    return false;
  }

  // Recalibrate tilt baseline and reset counters
  initializeSensors();
  lightBaseline = readLightADC();
  baselineValid = true;

  const char header[] =
    "time_ms,event,light_adc,lid_open,"
      "tilt_raw,shock_count,wall_pressed,"
      "reed16_open,reed09_open,tilt_abnormal,"
      "tilt_count,wall1_pressed,wall2_pressed,"
      "wall1_count,wall2_count,light_baseline,light_delta,run_ms,cds_open\r\n";
  if (!writeLogBytes(header, sizeof(header) - 1)) return false;

  recording = true;
  clearLiveQueues();

  if (!logRow("START")) return false;
  // Only commit the reported filename after the new header and START synced.
  strncpy(fileName, candidate, sizeof(fileName));
  fileName[sizeof(fileName) - 1] = '\0';
  sdLastError = "NONE";

  lastSnapshotAt = millis();

  Serial.print(F("RECORDING FILE: "));
  Serial.println(fileName);

  Serial1.print(F("RECORDING FILE: "));
  Serial1.println(fileName);

  return true;
}

// ========================================
// 10. STOP RECORDING
// ========================================

bool stopRecording() {

  if (!recording) return true;

  if (!logRow("END")) return false;

  // END was already synced by O_SYNC; File::flush would hide its return value.
  logFile.close();

  recording = false;
  resetShockBurst();
  return true;
}

// ========================================
// 11. SHOCK DETECTION
// ========================================

void updateShock(unsigned long now) {

  // Re-arm after a quiet interval, before considering a newly observed edge.
  if (shockBurstActive && now - shockChangedAt >= SHOCK_QUIET_MS) {
    shockBurstActive = false;
    shockLastEdges = shockBurstEdges;
  }

  int reading = digitalRead(SHOCK_PIN);

  // Count raw contact transitions
  if (reading != shockRaw) {

    shockRaw = reading;

    bool firstEdge = !shockBurstActive;
    if (firstEdge) {
      shockBurstActive = true;
      shockBurstEdges = 0;
    }

    shockBurstEdges++;
    shockChangedAt = now;
    // Report promptly; following contact bounce only extends this same burst.
    if (firstEdge) {
      shockLastEdges = shockBurstEdges;
      if (recording) {
        shockCount++;
        logRow("SHOCK_EVENT");
      } else {
        shockTestCount++;
      }
    }
  }
}

// ========================================
// 12. OTHER SENSOR EVENTS
// ========================================

void updateSensorEvents(unsigned long now) {

  if (!recording) return;

  // The two reeds monitor opposite sides of the same lid.
  // Each preceding row may wait for SD; timestamp each subsequent pin read now.
  if (updateFilter(reed16, millis())) logRow(reed16Open() ? "REED16_OPEN" : "REED16_CLOSED");
  if (!recording) return;
  if (updateFilter(reed09, millis())) logRow(reed09Open() ? "REED09_OPEN" : "REED09_CLOSED");
  if (!recording) return;

  // Wall microswitch 1 (D5)
  if (updateFilter(wall1, millis())) {

    if (wall1Pressed()) {
      wall1Count++;
      logRow("WALL1_PRESSED");
    } else {
      logRow("WALL1_RELEASED");
    }
  }

  if (!recording) return;

  // Wall microswitch 2 (D6)
  if (updateFilter(wall2, millis())) {

    if (wall2Pressed()) {
      wall2Count++;
      logRow("WALL2_PRESSED");
    } else {
      logRow("WALL2_RELEASED");
    }
  }

  if (!recording) return;

  // Tilt switch (D7)
  if (updateFilter(tilt, millis())) {

    if (tiltAbnormal()) {
      tiltCount++;
      logRow("TILT_DETECTED");
    } else {
      logRow("TILT_NORMAL");
    }
  }
}

// ========================================
// IDLE LIVE PREVIEW (independent of experiment counters and file format)
// ========================================

void clearLiveQueue(LiveClient &client) {
  client.head = 0;
  client.count = 0;
}

void clearLiveQueues() {
  clearLiveQueue(usbLive);
  clearLiveQueue(btLive);
}

bool liveActive(LiveClient &client, unsigned long now) {
  if (client.enabled && now - client.renewedAt >= LIVE_TTL_MS) {
    client.enabled = false;
    clearLiveQueue(client);
  }
  return client.enabled;
}

void enqueueLive(LiveClient &client, const LiveFrame &frame) {
  if (client.count == LIVE_QUEUE_SIZE) {
    // Preserve the latest state and report that older transitions were lost.
    client.head = (client.head + 1) % LIVE_QUEUE_SIZE;
    client.count--;
    client.dropped++;
  }
  byte tail = (client.head + client.count) % LIVE_QUEUE_SIZE;
  client.frames[tail] = frame;
  client.count++;
}

byte liveStateBits() {
  return (reed16Open() ? 1 : 0) |
         (reed09Open() ? 2 : 0) |
         (wall1Pressed() ? 4 : 0) |
         (wall2Pressed() ? 8 : 0) |
         (tilt.stable == HIGH ? 16 : 0) |
         (tiltAbnormal() ? 32 : 0) |
         (shockRaw == HIGH ? 64 : 0);
}

void queueLiveSnapshot(unsigned long now) {
  bool toUSB = liveActive(usbLive, now);
  bool toBT = liveActive(btLive, now);
  if (recording || (!toUSB && !toBT)) return;

  LiveFrame frame;
  frame.sequence = ++liveSequence;
  frame.timestamp = now;
  frame.shockTests = shockTestCount;
  frame.bits = liveStateBits();
  frame.light = readLightADC();
  lastLiveSnapshotAt = now;
  if (toUSB) enqueueLive(usbLive, frame);
  if (toBT) enqueueLive(btLive, frame);
}

void pollIdleSensors(unsigned long now) {
  if (recording) return;
  unsigned long previousShocks = shockTestCount;
  updateShock(now);
  // Do not short-circuit: every filter must be sampled on every pass.
  bool changed = updateFilter(reed16, now);
  changed = updateFilter(reed09, now) || changed;
  changed = updateFilter(wall1, now) || changed;
  changed = updateFilter(wall2, now) || changed;
  changed = updateFilter(tilt, now) || changed;
  bool lightPublished = updateLightSampler(now);
  if (changed || shockTestCount != previousShocks || lightPublished)
    queueLiveSnapshot(now);
}

void sendLiveFrame(HardwareSerial &port, LiveClient &client) {
  if (!client.enabled || client.count == 0) return;
  const LiveFrame &frame = client.frames[client.head];
  char line[64];
  int length = snprintf(line, sizeof(line), "LIVE,%lu,%lu,%u,%u,%lu,%lu\r\n",
    frame.sequence, frame.timestamp, (unsigned int)frame.bits, frame.light,
    frame.shockTests, client.dropped);
  // At most 59 bytes, including CRLF, so a complete line fits in AVR's TX ring.
  // Never wait for TX space here; slow Bluetooth cannot stall GPIO sampling.
  if (length <= 0 || length >= (int)sizeof(line) ||
      port.availableForWrite() < length) return;
  port.write((const uint8_t *)line, length);
  client.head = (client.head + 1) % LIVE_QUEUE_SIZE;
  client.count--;
}

void serviceLive(unsigned long now) {
  bool activeUSB = liveActive(usbLive, now);
  bool activeBT = liveActive(btLive, now);
  if (recording) {
    clearLiveQueues();
    return;
  }
  if ((activeUSB || activeBT) && now - lastLiveSnapshotAt >= LIVE_HEARTBEAT_MS)
    queueLiveSnapshot(now);
  sendLiveFrame(Serial, usbLive);
  sendLiveFrame(Serial1, btLive);
}

void configureLive(Stream &port, bool enabled) {
  LiveClient &client = (&port == &Serial) ? usbLive : btLive;
  unsigned long now = millis();
  bool wasActive = liveActive(client, now);
  client.enabled = enabled;
  client.renewedAt = now;
  if (!enabled || !wasActive) clearLiveQueue(client);
  // Renewals retain all queued transitions and do not inject another baseline.
  if (enabled && !wasActive && !recording) queueLiveSnapshot(now);
}

// STATUS is longer than the 9600-baud TX ring. Keep sampling during its wait,
// but defer LIVE transmission until the complete END_STATUS line has been sent.
class IdleSamplingStream : public Stream {
 public:
  explicit IdleSamplingStream(HardwareSerial &target) : target_(target) {}
  int available() { return target_.available(); }
  int read() { return target_.read(); }
  int peek() { return target_.peek(); }
  void flush() { target_.flush(); }
  size_t write(uint8_t value) {
    while (target_.availableForWrite() == 0) {
      if (!recording) pollIdleSensors(millis());
    }
    return target_.write(value);
  }
 private:
  HardwareSerial &target_;
};

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

  bool occupied[100] = {};
  if (!scanRunDirectory(occupied, true)) return;

  port.println(F("FILES_BEGIN"));
  for (int i = 0; i < 100; i++) {
    if (occupied[i]) {
      char name[13];
      snprintf(name, sizeof(name), "RUN%02d.CSV", i);
      port.println(name);
    }
  }
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
    // File::open cannot distinguish a missing file from an SD I/O failure.
    if (sdReady) sdLastError = "SD LOG OPEN FAILED";
    port.println(F("ERROR: SD LOG OPEN FAILED"));
    return;
  }

  port.print(F("BEGIN_LOG "));
  port.println(target);

  byte buffer[32];
  unsigned long sentBytes = 0;
  unsigned long expectedBytes = readFile.size();
  uint32_t hash = 2166136261UL;

  while (sentBytes < expectedBytes) {

    int n = readFile.read(
      buffer,
      (uint16_t)min((unsigned long)sizeof(buffer), expectedBytes - sentBytes)
    );

    if (n <= 0) {
      readFile.close();
      port.println();
      failStorage("SD LOG READ FAILED");
      return;
    }

    for (int i = 0; i < n; i++) { hash ^= buffer[i]; hash *= 16777619UL; }
    sentBytes += n;
    port.write(buffer, (size_t)n);
  }

  readFile.close();

  // A later complete read can resolve a per-file open error, but never clears
  // a latched write/root/read failure (sdReady == false).
  if (sdReady && strcmp(sdLastError, "SD LOG OPEN FAILED") == 0)
    sdLastError = "NONE";

  // Delimiter also separates a power-cut final row without a newline.
  port.println();
  port.print(F("LOG_BYTES: ")); port.println(sentBytes);
  port.print(F("LOG_FNV32: ")); port.println(hash, HEX);
  port.println(F("END_LOG"));
}

// ========================================
// 16. STATUS REPORT
// ========================================

uint16_t capacityLittle16(const uint8_t *p) {
  return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

uint32_t capacityLittle32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
         ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint32_t capacityFatValue(const uint8_t *data, uint16_t offset, uint8_t type) {
  if (type == 16) return capacityLittle16(data + offset);
  return capacityLittle32(data + offset) & 0x0FFFFFFFUL;
}

void capacityPrint64(Stream &port, uint64_t value) {
  char digits[21];
  uint8_t count = 0;
  do { digits[count++] = '0' + value % 10; value /= 10; } while (value);
  while (count) port.write(digits[--count]);
}

void capacityPrintBytes(Stream &port, const __FlashStringHelper *name, uint64_t value) {
  port.print(name); capacityPrint64(port, value); port.println();
}

bool capacityParseBoot(const uint8_t *b, uint32_t cardBlocks, uint32_t bootBlock,
                       uint32_t partitionBlocks, CapacityGeometry &g) {
  if (capacityLittle16(b + 510) != 0xAA55 || capacityLittle16(b + 11) != 512)
    return false;
  uint16_t reserved = capacityLittle16(b + 14);
  uint16_t rootEntries = capacityLittle16(b + 17);
  uint16_t fat16Blocks = capacityLittle16(b + 22);
  g.bootBlock = bootBlock;
  g.clusterBlocks = b[13];
  g.copies = b[16];
  g.totalBlocks = capacityLittle16(b + 19);
  if (!g.totalBlocks) g.totalBlocks = capacityLittle32(b + 32);
  g.fatBlocks = fat16Blocks ? fat16Blocks : capacityLittle32(b + 36);
  if (!cardBlocks || !g.totalBlocks || !reserved || !g.fatBlocks || !g.copies ||
      !g.clusterBlocks || (g.clusterBlocks & (g.clusterBlocks - 1))) return false;
  uint64_t volumeEnd = (uint64_t)bootBlock + g.totalBlocks;
  uint64_t fatStart = (uint64_t)bootBlock + reserved;
  uint64_t dataStart = fatStart + (uint64_t)g.copies * g.fatBlocks +
                       ((uint32_t)rootEntries * 32 + 511) / 512;
  if (bootBlock >= cardBlocks || volumeEnd > cardBlocks ||
      (partitionBlocks && g.totalBlocks > partitionBlocks) ||
      dataStart >= volumeEnd) return false;
  g.fatStart = (uint32_t)fatStart;
  g.dataStart = (uint32_t)dataStart;
  g.clusters = (uint32_t)((volumeEnd - dataStart) / g.clusterBlocks);
  if (g.clusters < 4085UL) return false;  // FAT12/exFAT are unsupported.
  g.type = g.clusters < 65525UL ? 16 : 32;
  if (g.clusters > 0x0FFFFFEDUL) return false;
  uint64_t entriesBytes = ((uint64_t)g.clusters + 2) * (g.type == 16 ? 2 : 4);
  if (entriesBytes > (uint64_t)g.fatBlocks * 512) return false;
  g.activeFat = 0;
  g.mirrored = true;
  if (g.type == 16) {
    if (!fat16Blocks || !rootEntries) return false;
  } else {
    if (fat16Blocks || rootEntries || capacityLittle16(b + 42) != 0) return false;
    uint32_t rootCluster = capacityLittle32(b + 44);
    if (rootCluster < 2 || rootCluster >= g.clusters + 2) return false;
    uint16_t flags = capacityLittle16(b + 40);
    g.mirrored = (flags & 0x0080) == 0;
    if (!g.mirrored) g.activeFat = flags & 0x000F;
    if (g.activeFat >= g.copies) return false;
  }
  return true;
}

void capacityPollAbort(Stream &port) {
  while (port.available()) {
    char c = (char)port.read();
    if (c == 27) capacityAbort = true;
    if (c == '\r') continue;
    if (c == '\n') {
      if (capacityCommandLength < sizeof(capacityCommand)) {
        capacityCommand[capacityCommandLength] = '\0';
        if (strcmp(capacityCommand, "ABORT") == 0) capacityAbort = true;
      }
      capacityCommandLength = 0;
    } else if (capacityCommandLength < sizeof(capacityCommand) - 1) {
      capacityCommand[capacityCommandLength++] = c;
    } else {
      capacityCommandLength = 255;  // Ignore an oversized line completely.
    }
  }
}

bool capacityStopped(Stream &port) {
  capacityPollAbort(port);
  // Keep idle input filtering alive between SD reads. No LIVE frames are sent.
  pollIdleSensors(millis());
  if (capacityAbort) { capacityFailure = "ABORTED"; return true; }
  if ((uint32_t)(millis() - capacityStartedAt) >= CAPACITY_TIMEOUT_MS) {
    capacityFailure = "TIMEOUT"; return true;
  }
  return false;
}

bool capacityReadSector(Stream &port, Sd2Card *card, uint32_t sector, uint8_t *destination) {
  if (capacityStopped(port)) return false;
  if (!card->readBlock(sector, destination)) {
    capacityFailure = "SD_READ_FAILED"; return false;
  }
  return !capacityStopped(port);
}

bool capacityScan(Stream &port, Sd2Card *card) {
  capacityStage = "CARD_SIZE";
  port.println(F("STAGE: CARD_SIZE"));
  if (capacityStopped(port)) return false;
  uint32_t cardBlocks = card->cardSize();
  if (!cardBlocks) { capacityFailure = "CARD_SIZE_FAILED"; return false; }
  if (capacityStopped(port)) return false;
  port.print(F("CARD_TYPE: ")); port.println(card->type());
  port.print(F("CARD_BLOCKS_512: ")); port.println(cardBlocks);
  capacityPrintBytes(port, F("CARD_BYTES: "), (uint64_t)cardBlocks * 512);

  capacityStage = "VOLUME_READ";
  port.println(F("STAGE: VOLUME_READ"));
  if (!capacityReadSector(port, card, 0, capacityBlock)) return false;
  CapacityGeometry g = {};
  uint8_t partition = 0;
  bool valid = false;
  // Follow SD.begin's first-partition-then-superfloppy selection without
  // touching the existing SdVolume, root directory, or shared sector cache.
  uint32_t firstBlock = capacityLittle32(capacityBlock + 454);
  uint32_t partitionBlocks = capacityLittle32(capacityBlock + 458);
  bool partitionCandidate = capacityLittle16(capacityBlock + 510) == 0xAA55 &&
      (capacityBlock[446] & 0x7F) == 0 && firstBlock > 0 && partitionBlocks >= 100 &&
      (uint64_t)firstBlock + partitionBlocks <= cardBlocks;
  if (partitionCandidate) {
    if (!capacityReadSector(port, card, firstBlock, capacityBlock)) return false;
    valid = capacityParseBoot(capacityBlock, cardBlocks, firstBlock, partitionBlocks, g);
    if (valid) partition = 1;
    else if (!capacityReadSector(port, card, 0, capacityBlock)) return false;
  }
  if (!valid) valid = capacityParseBoot(capacityBlock, cardBlocks, 0, 0, g);
  if (!valid) { capacityFailure = "INVALID_OR_UNSUPPORTED_FAT_VOLUME"; return false; }

  port.print(F("PARTITION: ")); port.println(partition);
  port.print(F("FAT_TYPE: ")); port.println(g.type);
  port.print(F("FAT_COPIES: ")); port.println(g.copies);
  port.print(F("ACTIVE_FAT: ")); port.println(g.activeFat);
  port.print(F("FAT_MIRRORED: ")); port.println(g.mirrored ? 1 : 0);
  port.print(F("CLUSTERS: ")); port.println(g.clusters);
  port.print(F("BLOCKS_PER_CLUSTER: ")); port.println(g.clusterBlocks);
  capacityPrintBytes(port, F("VOLUME_BYTES: "), (uint64_t)g.totalBlocks * 512);
  capacityPrintBytes(port, F("DATA_CAPACITY_BYTES: "), (uint64_t)g.clusters * g.clusterBlocks * 512);

  capacityStage = "FAT_SCAN";
  port.println(F("STAGE: FAT_SCAN"));
  uint8_t entryBytes = g.type == 16 ? 2 : 4;
  uint16_t entriesPerBlock = 512 / entryBytes;
  uint32_t sectorsToRead = (uint32_t)((((uint64_t)g.clusters + 2) * entryBytes + 511) / 512);
  uint32_t freeClusters = 0, badClusters = 0;
  uint32_t progressAt = millis();
  for (uint32_t relative = 0; relative < sectorsToRead; relative++) {
    if (!capacityReadSector(port, card, g.fatStart + (uint32_t)g.activeFat * g.fatBlocks + relative, capacityBlock))
      return false;
    if (g.mirrored) {
      for (uint8_t copy = 1; copy < g.copies; copy++) {
        if (!capacityReadSector(port, card, g.fatStart + (uint32_t)copy * g.fatBlocks + relative, capacityMirror))
          return false;
        for (uint16_t index = 0; index < entriesPerBlock; index++) {
          uint32_t cluster = relative * entriesPerBlock + index;
          if (cluster < 2 || cluster >= g.clusters + 2) continue;
          uint16_t offset = index * entryBytes;
          if (capacityFatValue(capacityBlock, offset, g.type) != capacityFatValue(capacityMirror, offset, g.type)) {
            capacityFailure = "FAT_COPIES_DISAGREE"; return false;
          }
        }
      }
    }
    for (uint16_t index = 0; index < entriesPerBlock; index++) {
      uint32_t cluster = relative * entriesPerBlock + index;
      if (cluster < 2 || cluster >= g.clusters + 2) continue;
      uint32_t value = capacityFatValue(capacityBlock, index * entryBytes, g.type);
      if (value == 0) freeClusters++;
      if (value == (g.type == 16 ? 0xFFF7UL : 0x0FFFFFF7UL)) badClusters++;
      capacityScanned++;
    }
    if ((uint32_t)(millis() - progressAt) >= 1000UL) {
      port.print(F("SCANNED_CLUSTERS: ")); port.println(capacityScanned);
      progressAt = millis();
    }
  }
  if (capacityStopped(port)) return false;
  if (capacityScanned != g.clusters) { capacityFailure = "INCOMPLETE_FAT_SCAN"; return false; }
  capacityStage = "COMPLETE";
  port.println(F("RESULT: SUCCESS"));
  port.println(F("FREE_VALID: 1"));
  port.print(F("FREE_CLUSTERS: ")); port.println(freeClusters);
  port.print(F("BAD_CLUSTERS: ")); port.println(badClusters);
  capacityPrintBytes(port, F("FREE_BYTES: "), (uint64_t)freeClusters * g.clusterBlocks * 512);
  capacityPrintBytes(port, F("ALLOCATED_OR_UNAVAILABLE_BYTES: "), (uint64_t)(g.clusters - freeClusters) * g.clusterBlocks * 512);
  return true;
}

void sendCapacity(Stream &port) {
  capacityStartedAt = millis();
  capacityScanned = 0;
  capacityAbort = false;
  capacityCommandLength = 0;
  capacityFailure = "NONE";
  capacityStage = "PRECHECK";
  Sd2Card *card = sdInitialized ? SdVolume::sdCard() : NULL;
  bool complete = false;
  port.println(F("BEGIN_SDINFO"));
  port.println(F("DIAGNOSTIC: READ_ONLY_SD_CAPACITY_V1"));
  if (recording) {
    capacityFailure = "STOP_FIRST";
  } else if (!card) {
    capacityFailure = "SD_NOT_INITIALIZED";
  } else {
    configureLive(Serial, false);
    configureLive(Serial1, false);
    complete = capacityScan(port, card);
  }
  if (!complete) {
    port.println(F("RESULT: FAILED"));
    port.println(F("FREE_VALID: 0"));
    port.println(F("FREE_CLUSTERS: UNKNOWN"));
    port.println(F("FREE_BYTES: UNKNOWN"));
    port.print(F("FAILED_STAGE: ")); port.println(capacityStage);
    port.print(F("ERROR: ")); port.println(capacityFailure);
    if (card) {
      port.print(F("LAST_CARD_ERROR_CODE: ")); port.println(card->errorCode(), HEX);
      port.print(F("LAST_CARD_ERROR_DATA: ")); port.println(card->errorData(), HEX);
    }
  }
  port.print(F("SCANNED_CLUSTERS: ")); port.println(capacityScanned);
  port.print(F("ELAPSED_MS: ")); port.println((uint32_t)(millis() - capacityStartedAt));
  port.println(F("END_SDINFO"));
  capacityStage = "IDLE";
  // Do not change sdReady/sdLastError, experiment counters, or fileName. A good
  // FAT read proves neither writable media nor recovery from a latched error.
  // LIVE remains off until the client explicitly subscribes again.
}

void printStatus(Stream &port) {

  port.println(F("PROTOCOL: PACKAGE_V2"));
  port.println(F("FIRMWARE: PACKAGE_V2_SD_CAPACITY_20261127"));
  port.print(F("UPTIME MS: ")); port.println(millis());
  port.println(F("LIVE PROTOCOL: 1"));
  port.println(F("CAPACITY PROTOCOL: 1"));
  port.print(F("REED STABLE MS: ")); port.println(REED_DEBOUNCE_MS);
  port.print(F("WALL STABLE MS: ")); port.println(WALL_DEBOUNCE_MS);
  port.print(F("TILT STABLE MS: ")); port.println(TILT_STABLE_MS);
  port.print(F("SHOCK QUIET MS: ")); port.println(SHOCK_QUIET_MS);
  port.println(F("SHOCK COUNT MODE: FIRST_EDGE"));
  port.print(F("LIGHT SAMPLE MS: ")); port.println(LIGHT_SAMPLE_MS);
  port.print(F("LIGHT UPDATE MS: ")); port.println(LIGHT_UPDATE_MS);
  port.print(F("STATE: "));
  port.println(
    recording ? "RECORDING" : "STOPPED"
  );

  port.print(F("FILE: "));
  port.println(fileName[0] ? fileName : "-");
  port.print(F("SD READY: "));
  port.println(sdReady ? 1 : 0);
  port.print(F("SD INITIALIZED: ")); port.println(sdInitialized ? 1 : 0);
  port.print(F("SD ERROR: ")); port.println(sdLastError);
  port.print(F("SD LAST WRITE MS: ")); port.println(sdLastWriteMs);
  port.print(F("SD MAX WRITE MS: ")); port.println(sdMaxWriteMs);

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
  port.print(F("SHOCK TEST COUNT: "));
  port.println(shockTestCount);
  port.print(F("SHOCK RAW: "));
  port.println(digitalRead(SHOCK_PIN));

  port.print(F("WALL1 PRESSED: "));
  port.println((int)wall1Pressed());

  port.print(F("WALL1 COUNT: "));
  port.println(wall1Count);

  port.print(F("WALL2 PRESSED: "));
  port.println((int)wall2Pressed());

  port.print(F("WALL2 COUNT: "));
  port.println(wall2Count);
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
    HardwareSerial &serialPort = (&port == &Serial) ? Serial : Serial1;
    IdleSamplingStream responsivePort(serialPort);
    printStatus(responsivePort);
  }

  else if (strcmp(command, "LIVE ON") == 0) {
    configureLive(port, true);
  }

  else if (strcmp(command, "LIVE OFF") == 0) {
    configureLive(port, false);
  }

  else if (strcmp(command, "SDINFO") == 0) {
    HardwareSerial &serialPort = (&port == &Serial) ? Serial : Serial1;
    IdleSamplingStream responsivePort(serialPort);
    sendCapacity(responsivePort);
  }

  else if (strcmp(command, "ABORT") == 0) {
    port.println(F("SCAN: IDLE"));
  }

  else if (strcmp(command, "LIGHT") == 0) {
    int current = readLightADC();
    port.print(F("LIGHT: ")); port.print(current); port.print(',');
    port.print(baselineValid ? lightBaseline : -1); port.print(',');
    port.println(baselineValid ? current - lightBaseline : 0);
  }

  else if (strcmp(command, "STOP") == 0) {

    if (recording) {
      if (!stopRecording()) return;
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

    // startRecording reports a specific failure without replacing fileName.
  }

  else if (strcmp(command, "LIST") == 0) {

    configureLive(port, false);

    if (sdInitialized) {
      listFiles(port);
    } else {
      port.println(F("ERROR: SD NOT READY"));
    }
  }

  else if (
    strncmp(command, "GET_LOG", 7) == 0 &&
    (command[7] == '\0' || command[7] == ' ')
  ) {

    configureLive(port, false);

    if (!sdInitialized) {
      port.println(F("ERROR: SD NOT READY"));
      return;
    }

    char *requested = command + 7;

    while (*requested == ' ') {
      requested++;
    }

    sendLog(port, requested);
  }

  else if (strcmp(command, "HELP") == 0) {

    port.println(F("STATUS"));
    port.println(F("LIGHT"));
    port.println(F("LIVE ON"));
    port.println(F("LIVE OFF"));
    port.println(F("SDINFO"));
    port.println(F("STOP"));
    port.println(F("START"));
    port.println(F("LIST"));
    port.println(F("GET_LOG"));
    port.println(F("GET_LOG RUN00.CSV"));
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
  initializeLightSampler(millis());

  if (!SD.begin(SD_CS)) {

    Serial.println(F("ERROR: SD INIT FAILED"));
    Serial1.println(F("ERROR: SD INIT FAILED"));

    return;
  }

  sdReady = true;
  sdInitialized = true;

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

  unsigned long now = millis();

  if (!recording) {
    pollIdleSensors(now);
    serviceLive(millis());
    return;
  }

  // Poll D4 in both modes; idle tests and experiment counts remain separate.
  updateShock(now);
  if (!recording) return;
  updateLightSampler(now);
  serviceLive(now);

  // Check all other digital sensors
  updateSensorEvents(now);
  if (!recording) return;

  // Save every sensor state once per second
  if (now - lastSnapshotAt >= SNAPSHOT_MS) {

    lastSnapshotAt = now;

    logRow("SNAPSHOT");
  }

  // Every successful write includes a checked sync (O_SYNC); no unchecked flush.
}
