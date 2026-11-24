"""Arduino SD log receiver. Python 3 + pyserial; no firmware writes or SD deletion."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
import uuid
from sensor_export import encode_csv, create_readable_workbook
from sensor_data import HEADER, KHEAD, EHEAD, ProtocolError, parse_csv, friendly_rows, display_rows

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data"
KST = timezone(timedelta(hours=9))

def safe_name(name):
    if not re.fullmatch(r"RUN[0-9]+\.CSV", name, re.I):
        raise ProtocolError(f"예상하지 않은 SD 파일명: {name!r}")
    return name.upper()

def durable_write(path, content):
    with path.open("xb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

def csv_bytes(rows):
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(KHEAD)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8-sig")

def save_result(folder, filename, payload, make_excel=True, allow_incomplete=False):
    filename, folder = safe_name(filename), Path(folder)
    raw_dir = folder / "원본_및_수신기록"
    raw_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    tag = f"{Path(filename).stem}_PCreceived_{now:%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex[:8]}"
    raw_path = raw_dir / f"{tag}_raw.txt"
    durable_write(raw_path, payload)
    try:
        data, warnings = parse_csv(payload, allow_incomplete=allow_incomplete)
    except ProtocolError as exc:
        raise ProtocolError(f"{exc}\n검증 실패 원본 보존: {raw_path}") from exc
    readable = friendly_rows(data, warnings)
    english = display_rows(data, warnings, 'en')
    all_path = folder / f"{tag}_KO.csv"
    event_path = folder / f"{tag}_EN.csv"
    stage_all = all_path.with_suffix(".csv.partial")
    stage_events = event_path.with_suffix(".csv.partial")
    durable_write(stage_all, encode_csv(KHEAD, readable))
    event_rows = [row for row, source in zip(readable, data) if source["event"] != "SNAPSHOT"]
    durable_write(stage_events, encode_csv(EHEAD, english))
    if all_path.exists() or event_path.exists(): raise FileExistsError("출력 파일 충돌")
    stage_all.rename(all_path)
    stage_events.rename(event_path)
    metadata = {"SD_파일명": filename, "PC_수신시각_실험시각아님": now.isoformat(),
                "시간기준": "실험 경과시간=START 기준. 부팅 후 ms 별도 보존. RTC 없음. 실제 날짜시각 알 수 없음.",
                "검증": "CSV 헤더·열·범위·시간·CDS 일관성 검증. V2 수신은 길이/FNV32 검증.",
                "정상종료": data[-1]["complete"], "CDS보정": "임계값 미설정; 실측 후 결정", "전체행수": len(data), "이벤트행수": len(event_rows), "주의": warnings,
                "원본_SHA256": hashlib.sha256(payload).hexdigest(),
                "전체데이터": str(all_path), "한국어CSV": str(all_path), "영어CSV": str(event_path), "원본": str(raw_path),
                "출력안내": "한국어와 영어 CSV에 동일한 전체 기록을 저장. 별도 이벤트 요약 CSV 없음.",
                "excel": None}
    if make_excel:
        xlsx_path = folder / f"{tag}_Readable.xlsx"
        try:
            metadata["excel"] = create_readable_workbook(xlsx_path, KHEAD, readable, english)
        except Exception as exc:
            # CSV export is already durable. Report the separate view failure,
            # never redownload or reset the board because formatting failed.
            metadata["excel_error"] = str(exc)
    durable_write(raw_dir / f"{tag}_수신정보.json", json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"))
    return metadata

def show_file(path):
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", "/select,", str(Path(path).resolve())])

class LineReader:
    """Keep partial lines across serial read timeouts."""
    def __init__(self, port):
        self.port, self.buffer = port, bytearray()
    def poll(self):
        if b"\n" not in self.buffer:
            self.buffer.extend(self.port.read(max(1, min(self.port.in_waiting, 4096))))
        if len(self.buffer) > 131072:
            raise ProtocolError("수신 줄 길이 초과: 속도/프로토콜 확인 필요")
        if b"\n" not in self.buffer: return None
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        return bytes(line) + b"\n"

class Receiver:
    def __init__(self, port, folder, emit=print, cancel=None, idle_timeout=20, total_timeout=3600,
                 command_timeout=10, attempts=3, start_timeout=12):
        self.port, self.folder, self.emit = port, Path(folder), emit
        self.reader = LineReader(port)
        self.cancel = cancel or threading.Event()
        self.idle_timeout, self.total_timeout = idle_timeout, total_timeout
        self.command_timeout, self.attempts = command_timeout, attempts
        self.start_timeout = start_timeout
        self.passive_stopped, self.passive_at = False, None
        self.protocol = None
        self.details = {}
    def check(self):
        if self.cancel.is_set(): raise InterruptedError("사용자가 연결을 종료했습니다.")
    def status(self):
        self.send("STATUS")
        deadline = time.monotonic() + self.command_timeout
        details = {}
        while time.monotonic() < deadline:
            self.check()
            raw = self.reader.poll()
            if raw is None: continue
            line = raw.decode("ascii", errors="replace").strip()
            self.emit(line)
            if line.startswith("ERROR:"): raise ProtocolError(line)
            if ': ' in line:
                key, value = line.split(': ', 1)
                details[key] = value
            if line == 'END_STATUS':
                if details.get('PROTOCOL') != 'PACKAGE_V2': break
                if details.get('STATE') not in ('RECORDING','STOPPED'): break
                if details.get('SD READY') != '1': raise ProtocolError('SD not ready / SD 카드 준비 안 됨')
                filename = details.get('FILE', '-')
                filename = None if filename == '-' else safe_name(filename)
                if details['STATE'] == 'RECORDING' and not filename: break
                self.protocol, self.details = details['PROTOCOL'], details
                return details['STATE'], filename
        raise ProtocolError('PACKAGE_V2 firmware/status required / 새 아두이노 코드 업로드 또는 연결 상태 확인 필요')

    def begin_new(self, previous_file=None):
        # Explicit START works on USB and Bluetooth. Never reset or retry START.
        self.send('START')
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            self.check()
            raw = self.reader.poll()
            if raw is None: continue
            line = raw.decode('ascii', errors='replace').strip()
            self.emit(line)
            if line.startswith('ERROR:'): raise ProtocolError(line)
            if line in ('RECORDING STARTED', 'ALREADY RECORDING'): break
        mode, filename = self.status()
        if mode != 'RECORDING' or not filename or filename == previous_file:
            raise ProtocolError('START not confirmed; use status / 시작 미확인: 상태 확인을 누르세요')
        self.passive_stopped, self.passive_at = False, None
        return filename

    def list_files(self):
        self.send('LIST')
        deadline = time.monotonic() + self.command_timeout
        names, active = [], False
        while time.monotonic() < deadline:
            self.check()
            raw = self.reader.poll()
            if raw is None: continue
            line = raw.decode('ascii', errors='replace').strip()
            if line.startswith('ERROR:'): raise ProtocolError(line)
            if line == 'FILES_BEGIN': active = True
            elif active and line == 'FILES_END': return sorted(set(names), reverse=True)
            elif active: names.append(safe_name(line))
        raise ProtocolError('SD file list timed out / SD 파일 목록 수신 시간 초과')

    def send(self, command):
        self.check()
        if command != "LIGHT": self.emit(f"> {command}")
        data = (command + "\n").encode("ascii")
        if self.port.write(data) != len(data): raise ProtocolError("명령 송신이 완료되지 않았습니다.")
    def monitor(self):
        self.check()
        raw = self.reader.poll()
        if raw is None: return None
        line = raw.decode("ascii", errors="replace").strip()
        self.emit(line)
        if line == "RECORDING STOPPED":
            self.passive_stopped, self.passive_at = True, time.monotonic()
        if self.passive_stopped and line.startswith("FILE:"):
            self.passive_stopped, self.passive_at = False, None
            return safe_name(line.split(":", 1)[1].strip())
        return None
    def stop(self):
        stopped = False
        for attempt in range(self.attempts):
            if not stopped: self.send("STOP")
            deadline = time.monotonic() + self.command_timeout
            while time.monotonic() < deadline:
                self.check()
                raw = self.reader.poll()
                if raw is None: continue
                line = raw.decode("ascii", errors="replace").strip()
                self.emit(line)
                if line in ("RECORDING STOPPED", "ALREADY STOPPED"): stopped = True
                if line.startswith("ERROR:"): raise ProtocolError(line)
                if stopped and line.startswith("FILE:"):
                    return safe_name(line.split(":", 1)[1].strip())
            if stopped: break
            self.emit(f"STOP 응답 대기 만료 ({attempt + 1}/{self.attempts})")
        raise ProtocolError("STOP 및 FILE 응답 확인 실패. 재연결 없이 '로그 다시 받기'로 복구할 수 있습니다.")
    def preserve_partial(self, payload):
        if not payload: return
        folder = self.folder / "원본_및_수신기록"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"불완전수신_{datetime.now(KST):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.partial"
        durable_write(path, payload)
        self.emit(f"불완전 수신 보존: {path}")
    def receive_once(self, expected=None):
        payload, active, filename = bytearray(), False, None
        started = last = time.monotonic()
        byte_count, received_hash = None, None
        self.send("GET_LOG " + safe_name(expected) if expected else "GET_LOG")
        try:
            while time.monotonic() - started < self.total_timeout:
                self.check()
                raw = self.reader.poll()
                if raw is None:
                    if time.monotonic() - last > self.idle_timeout:
                        raise ProtocolError("로그 수신 무응답 시간 초과")
                    continue
                last = time.monotonic()
                line = raw.decode("ascii", errors="replace").strip()
                if line.startswith("ERROR:"): raise ProtocolError(line)
                if not active:
                    self.emit(line)
                    if line.startswith("BEGIN_LOG "):
                        filename = safe_name(line.split(" ", 1)[1].strip())
                        if expected and filename != expected:
                            raise ProtocolError(f"STOP 파일({expected})과 수신 파일({filename})이 다릅니다.")
                        active = True
                    continue
                if line.startswith('LOG_BYTES: '):
                    byte_count = int(line.split(': ',1)[1]); continue
                if line.startswith('LOG_FNV32: '):
                    received_hash = int(line.split(': ',1)[1],16); continue
                if line == "END_LOG":
                    if self.protocol == 'PACKAGE_V2' and (byte_count is None or received_hash is None):
                        raise ProtocolError('Missing transfer checksum / 전송 검증값 없음')
                    if byte_count is not None:
                        if byte_count > len(payload) or bytes(payload[byte_count:]) not in (b'', b'\r\n', b'\n'):
                            raise ProtocolError('Transfer length mismatch / 수신 길이 불일치')
                        payload = payload[:byte_count]
                        checksum = 2166136261
                        for value in payload: checksum = ((checksum ^ value) * 16777619) & 0xffffffff
                        if checksum != received_hash: raise ProtocolError('Transfer checksum mismatch / 수신 검증값 불일치')
                    self.emit(f"END_LOG · 수신 {len(payload):,} 바이트")
                    return filename, bytes(payload)
                payload.extend(raw)
                if len(payload) > 128 * 1024 * 1024: raise ProtocolError("로그 크기 제한(128 MiB) 초과")
            raise ProtocolError("전체 수신 제한 시간 초과(기본 60분)")
        except BaseException:
            self.preserve_partial(bytes(payload) + bytes(self.reader.buffer))
            raise
    def settle(self):
        end, quiet = time.monotonic() + self.idle_timeout + 5, time.monotonic()
        while time.monotonic() < end:
            self.check()
            raw = self.reader.poll()
            if raw is not None: quiet = time.monotonic()
            elif time.monotonic() - quiet > 1.0:
                if self.reader.buffer: self.preserve_partial(bytes(self.reader.buffer))
                self.reader.buffer.clear()
                return
        raise ProtocolError("이전 전송이 계속되어 자동 재시도를 중단했습니다. 연결을 유지하고 기다려 주세요.")
    def download(self, expected=None, allow_incomplete=False):
        for attempt in range(self.attempts):
            try:
                filename, payload = self.receive_once(expected)
                result = save_result(self.folder, filename, payload, allow_incomplete=allow_incomplete)
                self.emit(f"저장 완료 · 전체 {result['전체행수']}행 / 이벤트 {result['이벤트행수']}행")
                return result
            except ProtocolError as exc:
                self.emit(f"수신/검증 실패 ({attempt + 1}/{self.attempts}): {exc}")
                if attempt + 1 == self.attempts: raise
                self.settle()

def open_port(name):
    import serial
    port = serial.Serial(port=None, baudrate=9600, timeout=0.1, write_timeout=3,
                         xonxoff=False, rtscts=False, dsrdtr=False)
    # Best effort only: USB drivers can still pulse these lines when opening.
    port.dtr = False
    port.rts = False
    port.port = name
    port.open()
    return port

class RecordingSession:
    """Serialize start/stop; preserve the previous completed run without resetting."""
    def __init__(self, receiver):
        self.receiver = receiver
        self.saved_file = None
    def save(self, expected, allow_incomplete=False):
        result = self.receiver.download(expected, allow_incomplete=allow_incomplete)
        self.saved_file = result["SD_파일명"]
        return result
    def stop_save(self):
        return self.save(self.receiver.stop())
    def start(self, on_preserved=lambda result: None):
        mode, current_file = self.receiver.status()
        if mode == "RECORDING":
            self.receiver.emit("이미 기록 중입니다. 현재 RUN을 유지합니다.")
            return current_file
        if current_file and self.saved_file != current_file:
            self.receiver.emit("이전 기록을 먼저 PC에 보존합니다.")
            on_preserved(self.save(current_file))
        return self.receiver.begin_new(current_file)

def gui(folder):
    from sensor_gui import gui as show_gui
    show_gui(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", default="COM4")
    parser.add_argument("--stop-after", type=float, help="CLI: 지정 초 모니터링 후 STOP/저장")
    parser.add_argument("--convert", type=Path, help="종료된 원본 RUN CSV를 오프라인 변환")
    parser.add_argument("--no-explorer", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.convert:
        result = save_result(args.output, args.convert.name, args.convert.read_bytes())
    elif args.stop_after is not None:
        if args.stop_after < 3: parser.error("--stop-after는 3초 이상이어야 합니다.")
        with open_port(args.port) as port:
            receiver = Receiver(port, args.output)
            boot_deadline = time.monotonic() + 3
            while time.monotonic() < boot_deadline: receiver.monitor()
            RecordingSession(receiver).start()
            deadline = time.monotonic() + args.stop_after
            while time.monotonic() < deadline:
                stopped = receiver.monitor()
                if stopped:
                    result = receiver.download(stopped)
                    break
            else:
                result = receiver.download(receiver.stop())
    else:
        gui(args.output)
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.no_explorer: show_file(result["전체데이터"])

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        sys.exit(1)
