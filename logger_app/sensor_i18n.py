"""Display Korean messages with an English companion line."""
import re

PHRASES = {
 "박스 센서 기록 시작/종료": "Package Sensor Logging · Start / Stop",
 "센서 기록 시작/종료": "Sensor Logging · Start / Stop",
 "① 연결 → ② 시작 → ③ 실험 → ④ 종료·저장": "1. Connect → 2. Start → 3. Experiment → 4. Stop and save",
 "보드 RESET은 필요 없습니다. Arduino IDE 시리얼 모니터는 닫아 주세요.": "No manual board reset is needed. Close the Arduino IDE Serial Monitor.",
 "COM 포트 연결": "Connect",
 "▶ 기록 시작": "▶ START",
 "■ 종료·저장": "■ STOP · Save",
 "상태 확인": "Check status",
 "로그 다시 받기": "Download again",
 "연결 해제": "Disconnect",
 "저장 폴더": "Output folder",
 "보기용 Excel 열기": "Open formatted Excel",
 "연결 대기 · COM4 / 9600 baud": "Disconnected · COM4 / 9600 baud",
 "COM 포트 연결을 누르면 보드의 실제 기록 상태를 확인합니다.": "Connect to check whether the board is recording or stopped.",
 "기록 중 · STOP을 누르면 종료하고 CSV로 저장합니다.": "Recording · Press STOP to finish and save.",
 " / 9600 연결. PC 시각은 통신 시각이며 이벤트 발생 시각이 아닙니다.": " / 9600 connected. PC timestamps refer to communication, not sensor events.",
 "기록 정지": "Stopped",
 "START로 새 기록을 시작하세요.": "Press START for a new run.",
 "상태 미확인 · 상태 확인 또는 STOP을 사용하세요.": "Status unknown · Use Check status or STOP.",
 "새 기록 시작 중 · 이전 기록 보존 및 START 응답 확인…": "Starting a new run · Preserving the previous run and waiting for START…",
 "센서를 조작하며 실험하세요.": "Operate the sensors to conduct your experiment.",
 "기록 종료 및 CSV 저장 중…": "Stopping and saving Korean/English CSVs and formatted Excel…",
 "종료된 로그를 다시 받는 중…": "Downloading the completed log…",
 "먼저 STOP을 눌러 주세요.": "Press STOP first.",
 "보드의 현재 상태 확인 중…": "Checking the board status…",
 "STOP 감지 · CSV 자동 저장 중…": "STOP detected · Saving CSV and Excel files…",
 "STOP 뒤 FILE 응답이 없습니다. 상태 확인 또는 로그 다시 받기를 사용하세요.": "No FILE response after STOP. Use Check status or Download again.",
 "작업 실패 · 수신창을 확인하고 상태 확인/STOP/로그 다시 받기를 사용하세요.": "Operation failed · Check the log, then use Check status, STOP or Download again.",
 "연결을 해제했습니다.": "Disconnected.",
 "연결/저장 오류": "Connection/save error",
 "USB, 시리얼 모니터 종료, 저장 공간을 확인해 주세요.": "Check USB, close the Serial Monitor and check available disk space.",
 "현재 측정값은 아래에 표시됩니다. STOP으로 종료·저장한 뒤 START로 다음 실험을 시작하세요.": "Live values appear below. STOP saves this run; START begins the next run.",
 "START를 누르면 새 기록이 시작됩니다. 미저장 이전 기록이 있으면 먼저 자동 보존합니다.": "START begins a new run. Any unsaved previous run is preserved first.",
 "명령 처리 중입니다. USB를 분리하지 말고 완료될 때까지 기다려 주세요.": "Processing. Keep USB connected and wait for completion.",
 "실제 START가 확인되지 않으면 기록 중으로 표시하지 않습니다. START 재시작은 자동 반복하지 않습니다.": "Recording requires a confirmed START. Reset attempts are not repeated automatically.",
 "보드 응답을 기다리고 있습니다.": "Waiting for the board.",
 "연결 및 기록 상태 확인 중…": "Connecting and checking recording status…",
 "요청 처리 중…": "Processing request…",
 "연결 종료 중…": "Disconnecting…",
 "연결 해제됨 · 수신창의 결과를 확인하세요.": "Disconnected · Check the results in the log.",
 "프로그램 종료": "Exit program",
 "수신을 종료할까요? Arduino 기록은 자동 중지되지 않습니다.": "Disconnect? Arduino recording will not stop automatically.",
 "CSV가 필요하면 취소 후 STOP · 종료·저장을 누르세요.": "To save the data, cancel and press STOP · Save first.",
 "새 기록 시작 요청 · USB 재시작 신호를 보냅니다.": "Starting a new run · Sending a USB reset pulse.",
 "이미 기록 중입니다. 현재 RUN을 유지합니다.": "Already recording. Keeping the current RUN.",
 "이전 기록을 먼저 PC에 보존합니다.": "Preserving the previous run on this PC first.",
 "사용자가 연결을 종료했습니다.": "Disconnected by the user.",
 "보드 상태 확인 실패. 연결됨만으로 기록 중이라고 판단하지 않습니다.": "Board status unavailable. A connection alone does not confirm recording.",
 "새 RUN 파일을 확인하지 못했습니다. 재시작을 반복하지 않습니다.": "No new RUN file confirmed. Reset will not be repeated.",
 "START 응답을 확인하지 못했습니다. '상태 확인'으로 현재 상태를 확인하세요.": "START was not confirmed. Use Check status.",
 "STOP 및 FILE 응답 확인 실패. 재연결 없이 '로그 다시 받기'로 복구할 수 있습니다.": "STOP/FILE confirmation failed. Try Download again without reconnecting.",
 "명령 송신이 완료되지 않았습니다.": "Command transmission did not complete.",
 "로그 수신 무응답 시간 초과": "Log reception timed out.",
 "로그 크기 제한(128 MiB) 초과": "Log exceeds the 128 MiB limit.",
 "전체 수신 제한 시간 초과(기본 60분)": "Total reception timeout (default 60 minutes).",
 "이전 전송이 계속되어 자동 재시도를 중단했습니다. 연결을 유지하고 기다려 주세요.": "The previous transfer is still active. Keep connected and wait; automatic retry was cancelled.",
 "수신 줄 길이 초과: 속도/프로토콜 확인 필요": "Incoming line too long. Check baud rate/protocol.",
 "CSV 문자 또는 구분 형식 오류": "Invalid CSV character or delimiter format.",
 "CSV 헤더가 현재 센서 형식과 다릅니다.": "CSV header does not match the sensor format.",
 "START부터 END까지 있는 종료된 로그가 아닙니다. 원본을 확인하세요.": "The log does not contain a complete START-to-END run. Check the raw capture.",
 "START/END 중복: 서로 다른 기록이 섞였을 수 있습니다.": "Duplicate START/END markers; multiple runs may be mixed.",
 "7개 열이 필요합니다.": "7 columns required.",
 "이벤트 형식 오류": "Invalid event format",
 "센서 숫자 형식 오류": "Invalid numeric sensor format",
 "센서값 범위 오류": "Sensor value out of range",
 "검증 실패 원본 보존": "Validation failed; raw capture preserved",
 "예상하지 않은 SD 파일명": "Unexpected SD filename",
 "출력 파일 충돌": "Output filename collision",
 "STOP 응답 대기 만료": "STOP response timeout",
 "불완전 수신 보존": "Partial capture preserved",
 "수신/검증 실패": "Reception/validation failed",
 "시작 실패": "Start failed",
 "STOP 파일": "STOP file",
 "수신 파일": "received file",
 "과 ": " and ",
 "이 다릅니다.": " do not match.",
 "저장 완료": "Saved",
 "기록 중": "Recording",
 "전체 ": "Rows: ",
 " / 이벤트 ": " / events: ",
 "행": " rows",
 "원본 ": "Source ",
 "바이트": "bytes",
 "수신 ": "received ",
 "영어 번역 누락": "Untranslated English text",
 "Excel 생성 실패": "Excel creation failed",
 "CSV 2개는 저장됐습니다.": "Both CSV files were saved.",
 "저장은 완료됐지만 탐색기를 열지 못했습니다": "Files were saved, but Explorer could not open",
 "먼저 기록을 저장해 주세요.": "Save a run first.",
 "Excel 파일이 없습니다. CSV를 다시 내려받아 생성해 주세요.": "No Excel file is available. Download the log again to create it.",
}

PHRASES.update({
 '전원 연결만으로 기록하지 않습니다. USB 또는 블루투스로 연결하세요. 시리얼 모니터는 닫아 주세요.': 'Power-on stays idle. Connect by USB or Bluetooth. Close the Arduino Serial Monitor.',
 '뚜껑을 닫고 기준 자세로 둔 뒤 START를 누르세요. CDS 임계값은 실측 후 설정합니다.': 'Close the lid, hold the reference orientation, then START. CDS threshold awaits measurement.',
 '명령 처리 중입니다. 전원과 통신 연결을 유지해 주세요.': 'Processing. Keep power and communication connected.',
 '오류 내용을 확인하세요. 전원이 끊겼다면 SD 파일 목록에서 이전 기록을 복구하세요.': 'Check the error. After power loss, recover the previous run from the SD file list.',
 'USB 또는 블루투스 연결, 시리얼 모니터 종료, 저장 공간을 확인해 주세요.': 'Check USB/Bluetooth, close Serial Monitor, and check available disk space.',
 'SD 파일을 선택하세요.': 'Select an SD file.',
 '선택 파일 수신·검증 중…': 'Receiving and validating the selected file…',
 '보드 재시작 감지 · 상태 확인 후 SD 파일을 복구하세요.': 'Board restart detected. Check status and recover the SD file.',
})

PHRASES.update({
    '기록 중 · STOP을 누르면 종료하고 엑셀로 저장합니다.': 'Recording; STOP saves one bilingual Excel file.',
    '기록 종료 및 엑셀 저장 중…': 'Stopping and saving Excel...',
    'STOP 감지 · 엑셀 자동 저장 중…': 'STOP detected; saving Excel...',
    '새 기록 시작 중 · START 응답 확인…': 'Starting a new run; checking START response...',
    'START로 다음 실험을 시작하세요.': 'Press START to begin the next experiment.',
    'Excel 파일이 없습니다. 로그 다시 받기로 재시도해 주세요.': 'No Excel file. Retry using Download again.',
    '수신을 종료할까요? Arduino 기록은 자동 중지되지 않습니다.\n엑셀이 필요하면 취소 후 STOP · 종료·저장을 누르세요.': 'Close reception? Arduino recording will continue.\nTo save Excel, cancel and press STOP first.',
})

def bilingual(value):
    value = str(value)
    if re.match(r'^[A-Za-z][^가-힣]* / ', value): return value
    if not re.search(r"[가-힣]", value): return value
    # File paths are data, not UI prose; never translate a user's folder names.
    if re.match(r"^[A-Za-z]:[\\/]", value): return value
    english = re.sub(r"원본 (\d+)행", r"Source row \1", value)
    for ko, en in sorted(PHRASES.items(), key=lambda item: -len(item[0])):
        english = english.replace(ko, en)
    return value + "\n" + english


# Error guidance is authored in both languages; do not machine-substitute paths
# or exception details. Each entry contains title, reason and action pairs.
_ERROR_GUIDANCE = {
    'sd_not_ready': (
        ('SD 카드 인식 오류', 'SD card not detected'),
        ('보드가 SD 카드 초기화에 실패했거나 준비 상태를 확인하지 못했습니다. 카드 접촉, 모듈 전원·배선, 카드 형식 등을 확인해야 하며 용량 부족으로 단정할 수 없습니다.',
         'The board could not initialize or confirm the SD card. Card contact, module power/wiring or card format may be involved; this does not prove that the card is full.'),
        ('기록 정지를 확인하고 전원을 끈 뒤 SD 카드를 다시 꽂으세요. 전원을 켠 다음 상태 확인을 누르세요.',
         'Confirm recording is stopped. Power off, reseat the SD card, power on, then click Check status.'),
    ),
    'sd_root': (
        ('SD 카드 목록을 열지 못했습니다', 'Cannot open the SD directory'),
        ('보드가 SD 카드의 파일 목록을 읽지 못했습니다. 카드 접촉이나 파일 시스템 문제 등이 가능하지만 이 메시지만으로 원인은 확정되지 않습니다.',
         'The board could not read the SD file directory. Card contact or a filesystem issue is possible, but the message does not identify the exact cause.'),
        ('전원을 유지하고 상태 확인 후 로그 다시 받기를 재시도하세요. 계속 실패하면 기록 종료를 확인한 뒤 전원을 끄고 카드 연결 상태를 점검하세요.',
         'Keep power on, Check status, and retry Download again. If it persists, confirm recording has stopped before powering off and checking the card connection.'),
    ),
    'sd_read': (
        ('SD 파일을 읽지 못했습니다', 'Cannot read the SD log'),
        ('보드가 SD 로그를 열거나 읽는 데 실패했습니다. 카드나 파일 문제 등이 가능하며 저장 공간 부족을 뜻하는 메시지는 아닙니다.',
         'The board could not open or read the SD log. A card or file issue is possible; this message does not establish insufficient storage space.'),
        ('전원을 유지하고 상태 확인 후 SD 파일 목록에서 같은 RUN 파일을 다시 선택하세요. 반복되면 기록 종료를 확인한 뒤 카드의 원본 파일을 점검하세요.',
         'Keep power on, Check status, and select the same RUN file from the SD list again. If it repeats, confirm recording has stopped before inspecting the original card files.'),
    ),
    'sd_write': (
        ('SD 카드에 기록하지 못했습니다', 'Cannot write to the SD card'),
        ('보드가 SD 파일 쓰기 실패를 보고했습니다. 카드 상태, 접촉, 파일 시스템 또는 여유 공간 등은 별도 점검이 필요합니다.',
         'The board reported an SD write failure. Card condition/contact, filesystem and free space require separate checks.'),
        ('상태와 기록 종료 여부를 확인하고 보존 가능한 기존 RUN 파일을 먼저 받으세요. 기록 종료를 확인한 뒤 전원을 끄고 카드 상태와 여유 공간을 점검하세요.',
         'Check status and whether recording has stopped, then retrieve existing RUN files that can be preserved. Confirm recording has stopped before powering off and checking the card and its free space.'),
    ),
    'sd_file_missing': (
        ('SD 기록 파일을 열 수 없습니다', 'Cannot open the SD recording'),
        ('보드가 요청한 RUN 파일을 열지 못했습니다. 파일이 없거나 SD 카드·파일 시스템에 문제가 있을 수 있어, 파일이 없다고 단정할 수 없습니다.',
         'The board could not open the requested RUN file. It may be missing, or the SD card/filesystem may have failed; this response alone does not prove the file is absent.'),
        ('새 기록을 시작하지 말고 로그 다시 받기로 같은 RUN 파일을 재시도하세요. 계속 실패하면 기록 정지를 확인하고 카드리더로 SD 원본을 보존하세요.',
         'Do not start another run. Use Download again for the same RUN file. If it still fails, confirm recording is stopped and preserve the SD files with a card reader.'),
    ),
    'start_failed': (
        ('새 기록을 시작하지 못했습니다', 'A new recording could not be started'),
        ('보드가 새 기록 파일을 준비하지 못했습니다. SD 상태, 파일 생성·쓰기 문제 또는 사용 가능한 RUN 파일명 등이 원인일 수 있습니다.',
         'The board could not prepare a new log file. SD readiness, file creation/writing or available RUN filenames may be involved.'),
        ('START를 반복해서 누르지 말고 전원을 유지한 채 상태 확인을 누르세요. 기존 로그를 먼저 확인·보존하고 SD 상태가 정상인지 확인한 뒤 다시 시작하세요.',
         'Do not repeatedly press START. Keep power on and Check status. Check and preserve existing logs, then retry only after confirming the SD is ready.'),
    ),
    'sd_create': (
        ('SD 카드에 새 기록 파일을 만들지 못했습니다', 'Cannot create a new SD recording'),
        ('SD 파일 생성에 실패했습니다. 카드 상태·접촉, 파일 시스템 또는 여유 공간을 확인해야 합니다.',
         'Creating the SD file failed. Check card condition/contact, filesystem and free space.'),
        ('새 기록을 시작하지 마세요. 기록 정지를 확인하고 기존 파일을 보존한 뒤, 전원을 끄고 SD 카드를 점검하세요.',
         'Do not start a new run. Confirm recording is stopped, preserve existing files, then power off and inspect the SD card.'),
    ),
    'run_names_full': (
        ('사용 가능한 RUN 파일명이 없습니다', 'No unused RUN filename is available'),
        ('보드가 사용하는 RUN00.CSV부터 RUN99.CSV까지의 이름이 모두 사용 중입니다. SD 용량이 찼다는 뜻은 아닙니다.',
         'All supported names RUN00.CSV through RUN99.CSV are in use. This does not mean that the SD card is full.'),
        ('기록 정지를 확인한 뒤 SD 파일을 PC에 백업하세요. 백업을 확인하고 카드리더로 기존 RUN 파일을 정리한 다음 다시 연결하세요.',
         'Confirm recording is stopped and back up the SD files to the PC. Verify the backup, free an existing RUN filename using a card reader, then reconnect.'),
    ),
    'stop_required': (
        ('기록 종료가 먼저 필요합니다', 'Stop recording first'),
        ('기록 중에는 SD 파일 목록 조회나 다운로드를 할 수 없습니다.',
         'The SD file list and downloads are unavailable while recording.'),
        ('현재 실험을 끝내려면 종료·저장을 누르고 종료 응답을 기다린 뒤 파일을 다시 요청하세요. 실험을 계속하려면 다운로드를 나중에 하세요.',
         'To finish the experiment, press STOP · Save and wait for confirmation before requesting the file. Otherwise, postpone the download.'),
    ),
    'invalid_filename': (
        ('SD 파일명을 확인해 주세요', 'Check the SD filename'),
        ('요청하거나 받은 파일명이 프로그램에서 허용하는 RUN 파일 형식과 다릅니다.',
         'The requested or received filename does not match the supported RUN filename format.'),
        ('로그 다시 받기로 실제 SD 파일 목록을 불러와 선택하세요. 반복되면 오류 상세와 보드 프로그램 버전을 확인하세요.',
         'Use Download again and select a filename from the actual SD list. If it repeats, check the error details and board firmware version.'),
    ),
    'port_missing': (
        ('선택한 시리얼 포트가 없습니다', 'Selected serial port is unavailable'),
        ('선택한 포트를 찾지 못했습니다. 장치 연결이 끊겼거나 포트 이름이 바뀌었을 수 있습니다.',
         'The selected port could not be found. The device may be disconnected or its port name may have changed.'),
        ('보드 전원은 유지하세요. USB·블루투스 연결과 현재 포트 이름을 확인한 뒤 해당 포트를 선택해 연결하고 상태 확인을 누르세요.',
         'Keep the board powered. Check USB/Bluetooth and the current port name, select that port, reconnect, and Check status.'),
    ),
    'port_busy': (
        ('시리얼 포트를 열 수 없습니다', 'Cannot open the serial port'),
        ('포트 접근이 거부되었습니다. 다른 프로그램이 사용 중이거나 운영체제가 접근을 제한할 수 있습니다.',
         'Access to the port was denied. Another application may be using it, or the operating system may be preventing access.'),
        ('보드 전원을 유지하고 Arduino 시리얼 모니터와 같은 포트를 사용하는 다른 센서 프로그램을 닫으세요. 다시 연결한 뒤 상태 확인을 누르세요.',
         'Keep the board powered. Close the Arduino Serial Monitor and other sensor applications using the same port, then reconnect and Check status.'),
    ),
    'disconnected': (
        ('통신 연결이 끊겼거나 응답하지 않습니다', 'Communication was interrupted'),
        ('포트에서 데이터를 읽거나 쓰지 못했습니다. 케이블·블루투스 연결이나 드라이버 문제가 가능하며 보드의 기록 종료 여부는 확인되지 않았습니다.',
         'The port could not be read from or written to. Cable, Bluetooth or driver issues are possible; recording may still be running on the board.'),
        ('보드 전원을 유지하고 연결을 복구한 뒤 상태 확인을 누르세요. 종료 상태이면 로그 다시 받기로 SD 기록을 복구하세요.',
         'Keep the board powered, restore the connection, and Check status. If stopped, recover the SD log with Download again.'),
    ),
    'serial_timeout': (
        ('통신 응답 시간이 초과되었습니다', 'Serial communication timed out'),
        ('운영체제 또는 시리얼 포트가 제한 시간 안에 응답하지 않았습니다. 이 오류만으로 센서 고장이나 기록 종료를 판단할 수 없습니다.',
         'The operating system or serial port did not respond within the time limit. This alone does not establish a failed sensor or stopped recording.'),
        ('보드 전원을 유지하고 케이블·블루투스와 포트를 사용하는 다른 앱을 확인하세요. 다시 연결한 뒤 상태 확인을 누르세요.',
         'Keep the board powered. Check the cable/Bluetooth link and other apps using the port, reconnect, then Check status.'),
    ),
    'live_timeout': (
        ('실시간 센서 응답이 멈췄습니다', 'Live sensor updates stopped'),
        ('정해진 시간 동안 실시간 상태를 받지 못했습니다. 화면의 마지막 값은 현재 상태가 아닐 수 있습니다.',
         'No live state arrived within the expected time. The last displayed values may no longer reflect the current sensor state.'),
        ('보드 전원을 유지하고 연결 상태와 상태 확인을 먼저 확인하세요. 연결이 정상으로 돌아온 뒤 센서 테스트를 다시 시작하세요.',
         'Keep the board powered and check the connection and board status first. Restart the sensor test after communication returns to normal.'),
    ),
    'live_gap': (
        ('일부 실시간 변화가 누락되었습니다', 'Some live sensor changes were missed'),
        ('실시간 수신 순서가 끊기거나 다시 시작되었습니다. 화면의 테스트 누적 횟수는 실제 움직임보다 적을 수 있으며 SD 원본의 누락 여부는 별도 확인이 필요합니다.',
         'The live sequence has a gap or restarted. Displayed test counts may be low; whether the SD log is affected must be checked separately.'),
        ('연결을 확인하고 테스트를 새로 시작해 동작을 다시 확인하세요. 정식 실험의 횟수는 종료 후 다운로드한 SD 원본과 엑셀을 확인하세요.',
         'Check the connection, restart the sensor test, and repeat the movement. For an actual experiment, check the downloaded SD log and Excel after stopping.'),
    ),
    'protocol_mismatch': (
        ('보드와 프로그램의 통신 형식이 다릅니다', 'Board communication format does not match'),
        ('보드가 응답한 통신 규약이나 명령 형식이 현재 프로그램의 기대 형식과 다릅니다.',
         'The reported board protocol or command format does not match what this application expects.'),
        ('선택한 COM 포트가 해당 보드인지 확인하고 9600 baud 및 호환되는 보드·PC 프로그램 버전을 확인하세요. 기록 중인지 확인하고 로그를 보존하기 전에는 보드 프로그램을 바꾸지 마세요.',
         'Verify the selected COM port, 9600 baud, and compatible board/PC software versions. Confirm recording status and preserve logs before changing board firmware.'),
    ),
    'status_timeout': (
        ('보드 상태 응답을 확인하지 못했습니다', 'Board status response was incomplete'),
        ('상태 응답이 제한 시간 안에 완료되지 않았거나 필요한 항목이 빠졌습니다. 이것만으로 보드 프로그램이 잘못되었다고 단정할 수 없습니다.',
         'The status response timed out or lacked required fields. This alone does not prove that the board firmware is incorrect.'),
        ('보드 전원을 유지하고 연결과 COM 포트를 확인한 뒤 상태 확인을 다시 누르세요. START를 반복하지 말고 기존 기록 상태부터 확인하세요.',
         'Keep the board powered, check the connection and COM port, then retry Check status. Do not repeat START before confirming the existing recording state.'),
    ),
    'status_unconfirmed': (
        ('보드의 상태와 호환성을 확인하지 못했습니다', 'Board status and compatibility are unconfirmed'),
        ('완전한 호환 상태 응답을 받지 못했습니다. 통신 지연인지 프로그램 형식 불일치인지는 이 메시지만으로 구분되지 않습니다.',
         'A complete compatible status response was not received. This message does not distinguish a communication delay from a software format mismatch.'),
        ('전원을 유지하고 연결·COM 포트를 확인한 뒤 상태 확인을 재시도하세요. 응답 내용이 계속 다르면 기록을 보존한 뒤 보드·PC 프로그램 버전을 확인하세요.',
         'Keep power on, check the connection and COM port, and retry Check status. If the response remains incompatible, preserve logs before checking board/PC software versions.'),
    ),
    'board_reset': (
        ('보드가 재시작되었습니다', 'Board restart detected'),
        ('보드 시작 메시지를 다시 받았습니다. 진행 중이던 기록은 정상 종료되지 않았을 수 있고 실시간 기준·횟수가 다시 시작될 수 있습니다.',
         'A board startup message was received again. A previous recording may lack a normal END marker, and live baselines/counts may have restarted.'),
        ('다시 재시작하지 말고 상태 확인을 누르세요. 로그 다시 받기에서 이전 RUN 파일을 찾아 복구한 뒤 새 실험을 시작하세요.',
         'Do not restart again. Check status and recover the previous RUN file with Download again before starting a new experiment.'),
    ),
    'transfer_invalid': (
        ('수신 데이터 검증에 실패했습니다', 'Received data failed validation'),
        ('전송 길이·검증값·CSV 형식 또는 센서값이 예상 조건과 맞지 않습니다. 통신 누락, 불완전한 기록 또는 서로 다른 형식 등이 가능하며 원인은 아직 확정되지 않았습니다.',
         'The transfer length/checksum, CSV format or sensor values failed validation. Missing data, an incomplete run or a format mismatch is possible; the cause is not yet confirmed.'),
        ('보드 전원을 유지하고 같은 RUN 파일을 로그 다시 받기로 재시도하세요. 반복되면 오류 상세와 SD 원본·이미 저장된 PC 파일을 함께 확인하세요.',
         'Keep the board powered and retry the same RUN file with Download again. If it repeats, inspect the error details, SD original, and any files already saved on the PC.'),
    ),
    'download_timeout': (
        ('SD 목록 또는 로그 수신 시간이 초과되었습니다', 'SD list or log reception timed out'),
        ('SD 파일 목록이나 로그 전송이 제한 시간 안에 완료되지 않았습니다. 연결 지연이나 중단 등이 가능하며 파일이 없다는 뜻은 아닙니다.',
         'The SD file list or log transfer did not complete within the time limit. A delayed or interrupted connection is possible; this does not mean the file is absent.'),
        ('보드 전원과 연결을 유지하세요. 진행 중인 전송이 끝나길 기다린 뒤 상태 확인을 하고 로그 다시 받기로 같은 파일을 요청하세요.',
         'Keep board power and communication connected. Wait for any current transfer to finish, Check status, then request the same file with Download again.'),
    ),
    'stop_unconfirmed': (
        ('기록 종료를 확인하지 못했습니다', 'Recording stop is not confirmed'),
        ('STOP 또는 종료 파일명 응답을 받지 못했습니다. 기록이 계속되는지 이미 종료됐는지 아직 확인되지 않았습니다.',
         'The STOP or final filename response was not received. It is not yet known whether recording is continuing or has stopped.'),
        ('보드 전원을 유지하고 상태 확인을 누르세요. 기록 중이면 종료·저장을 사용하고, 종료 상태이면 로그 다시 받기로 해당 RUN 파일을 받으세요.',
         'Keep the board powered and Check status. If recording, use STOP · Save; if stopped, retrieve the RUN file with Download again.'),
    ),
    'start_unconfirmed': (
        ('기록 시작을 확인하지 못했습니다', 'Recording start is not confirmed'),
        ('START 요청 후 새 기록 파일이나 기록 중 상태를 확인하지 못했습니다. 실제로 시작되었을 가능성도 있습니다.',
         'A new log file or RECORDING state was not confirmed after START. The board may nevertheless have started recording.'),
        ('START를 반복하거나 전원을 끄지 말고 상태 확인을 누르세요. 현재 RUN과 기록 상태를 확인한 뒤 계속 진행하세요.',
         'Do not repeat START or power the board off. Check status and confirm the current RUN and recording state before proceeding.'),
    ),
    'transfer_busy': (
        ('이전 전송이 아직 끝나지 않았습니다', 'A previous transfer is still active'),
        ('이전 로그 전송이 계속되어 새 다운로드의 자동 재시도가 중단되었습니다.',
         'Automatic retry stopped because data from a previous transfer is still arriving.'),
        ('전원과 통신 연결을 유지하고 전송이 끝날 때까지 기다리세요. 이후 상태 확인을 하고 필요한 파일을 다시 받으세요.',
         'Keep power and communication connected and wait for the transfer to finish. Then Check status and download the required file again.'),
    ),
    'transfer_too_large': (
        ('수신 데이터 크기 제한을 넘었습니다', 'Received data exceeded the size limit'),
        ('프로그램의 수신 크기 제한을 초과했습니다. 매우 긴 기록이거나 전송 종료 표시를 정상적으로 받지 못했을 수 있습니다.',
         'The application reception size limit was exceeded. The run may be unusually large, or its transfer end marker may not have been received correctly.'),
        ('전원을 유지하고 상태와 선택한 RUN 파일을 확인하세요. 원본 파일 크기와 오류 상세를 확인한 뒤 필요한 구간의 복구 방법을 결정하세요.',
         'Keep power on and verify the board status and selected RUN. Check the original file size and error details before choosing a recovery method.'),
    ),
    'pc_disk_full': (
        ('PC 저장 공간이 부족합니다', 'PC storage is full'),
        ('컴퓨터 저장 위치의 공간이 부족합니다. Arduino SD 카드 용량에 대한 판정은 아닙니다.',
         'There is insufficient space at the computer save location. This is not a diagnosis of the Arduino SD card capacity.'),
        ('PC의 여유 공간을 확보하거나 다른 저장 폴더를 선택한 뒤 다시 저장하세요. 보드 전원을 유지하고 필요한 RUN 파일을 로그 다시 받기로 복구하세요.',
         'Free PC space or select another output folder, then save again. Keep the board powered and retrieve the required RUN with Download again if needed.'),
    ),
    'save_permission': (
        ('PC 파일에 쓸 수 없습니다', 'Cannot write to the PC file'),
        ('저장 위치가 읽기 전용이거나 쓰기 권한이 없거나 다른 프로그램이 파일을 사용 중일 수 있습니다.',
         'The location may be read-only, write permission may be missing, or another application may be holding the file open.'),
        ('열려 있는 해당 엑셀 파일을 닫고 쓰기 가능한 다른 저장 폴더를 선택한 뒤 다시 저장하세요. 파일이 보존됐는지는 실제 저장 폴더에서 확인하세요.',
         'Close the affected Excel file, choose another writable output folder, and retry. Check the actual output folder to see which files were saved.'),
    ),
    'save_path_missing': (
        ('PC 저장 경로를 사용할 수 없습니다', 'PC save path is unavailable'),
        ('저장 폴더나 드라이브를 찾거나 열지 못했습니다. 이동식 드라이브·네트워크 경로 연결 또는 폴더 위치가 바뀌었을 수 있습니다.',
         'The output folder or drive could not be found or opened. A removable/network drive may be unavailable, or the folder may have moved.'),
        ('존재하는 로컬 저장 폴더를 선택하고 접근 가능한지 확인한 뒤 다시 저장하세요. 보드 전원을 유지하면 필요한 로그를 다시 받을 수 있습니다.',
         'Choose an existing local output folder, verify access, and retry. Keep the board powered so the required log can be requested again.'),
    ),
    'save_collision': (
        ('같은 이름의 PC 파일이 이미 있습니다', 'A PC file with this name already exists'),
        ('기존 파일 덮어쓰기를 방지하기 위해 저장을 중단했습니다.',
         'Saving stopped to avoid overwriting an existing file.'),
        ('기존 파일을 확인하고 다른 파일명이나 저장 폴더를 사용해 다시 저장하세요.',
         'Check the existing file and retry with a different filename or output folder.'),
    ),
    'save_failed': (
        ('PC 파일 저장에 실패했습니다', 'PC file saving failed'),
        ('PC 파일을 만드는 과정에서 오류가 발생했습니다. 원인과 저장 완료 여부는 오류 상세 및 실제 폴더 확인이 필요합니다.',
         'An error occurred while creating PC files. The details and actual output folder must be checked to determine the cause and what was saved.'),
        ('저장 폴더 접근과 PC 여유 공간을 확인하고 다시 저장하세요. 보드 전원을 유지하고 필요한 로그를 다시 받을 수 있는지 확인하세요.',
         'Check access to the output folder and free PC space, then retry. Keep the board powered and verify that the required log can be downloaded again.'),
    ),
    'excel_dependency': (
        ('엑셀 생성 구성요소가 없습니다', 'Excel export component is missing'),
        ('엑셀 파일 생성에 필요한 Python 구성요소를 불러오지 못했습니다. Microsoft Excel 설치 여부와는 별개의 문제입니다.',
         'A Python component required to generate Excel files could not be loaded. This is separate from whether Microsoft Excel is installed.'),
        ('필수 구성요소가 포함된 실행 프로그램을 복구하거나 Python 환경의 openpyxl을 확인한 뒤 엑셀 생성을 재시도하세요.',
         'Restore the application with its required components, or check openpyxl in the Python environment, then retry Excel export.'),
    ),
    'excel_save': (
        ('엑셀 파일을 만들지 못했습니다', 'Excel file creation failed'),
        ('엑셀 파일 생성 또는 저장 중 오류가 발생했습니다. 저장 위치·파일 잠금 또는 출력 데이터 문제 등은 상세 오류로 확인해야 합니다.',
         'Excel creation or saving failed. The error details are needed to check the output location, file locks or report data.'),
        ('해당 엑셀 파일을 닫고 저장 폴더를 확인한 뒤 엑셀 생성을 재시도하세요. 계속 실패하면 상세 오류를 확인하세요.',
         'Close the affected Excel file, check the output folder, and retry Excel creation. If it keeps failing, inspect the detailed error.'),
    ),
    'open_file': (
        ('파일 또는 폴더를 열지 못했습니다', 'Cannot open the file or folder'),
        ('탐색기 또는 연결된 앱을 열지 못했습니다. 이 오류만으로 저장 파일이 없어졌다고 판단할 수 없습니다.',
         'Explorer or the associated application could not be opened. This alone does not mean that a saved file was lost.'),
        ('저장 폴더에서 해당 파일이 있는지 확인하고 직접 여세요. 파일이 없으면 저장 결과와 엑셀 생성 오류를 먼저 확인하세요.',
         'Check for the file in the output folder and open it manually. If it is missing, check the save result and any Excel creation error first.'),
    ),
    'capacity_unsupported': (
        ('보드에서 용량 조회를 지원하지 않습니다', 'The board does not support capacity checks'),
        ('현재 보드 프로그램은 SD 카드 여유 공간을 조회하는 기능이 없습니다. 남은 용량은 확인되지 않았습니다.',
         'The current board firmware cannot report free SD space. Remaining capacity is unknown.'),
        ('SD 용량 조회 기능이 포함된 보드 프로그램으로 업데이트한 뒤 다시 연결하세요.',
         'Update the board firmware to a version with SD capacity checks, then reconnect.'),
    ),
    'capacity_timeout': (
        ('SD 용량 확인 시간이 초과되었습니다', 'SD capacity check timed out'),
        ('카드 검사 또는 응답 수신이 제한 시간 안에 끝나지 않았습니다. 남은 용량은 확인되지 않았습니다.',
         'The card scan or response did not finish in time. Remaining capacity is unknown.'),
        ('전원과 연결을 유지하고 상태 확인 후 다시 조회하세요. 계속 실패하면 SD 카드 연결과 오류 상세를 확인하세요.',
         'Keep power and the connection active, Check status, then retry. If it repeats, check the SD connection and error details.'),
    ),
    'capacity_invalid': (
        ('SD 용량 응답을 확인하지 못했습니다', 'The SD capacity response could not be verified'),
        ('용량 응답이 누락되었거나 수치가 일치하지 않습니다. 남은 용량은 확인되지 않았습니다.',
         'The capacity response is incomplete or its values are inconsistent. Remaining capacity is unknown.'),
        ('연결과 보드 프로그램 버전을 확인하고 다시 조회하세요. 상세 오류를 확인하면 누락된 응답을 알 수 있습니다.',
         'Check the connection and board firmware version, then retry. Review the error details for the invalid response.'),
    ),
    'capacity_failed': (
        ('SD 용량을 확인하지 못했습니다', 'SD capacity could not be checked'),
        ('SD 용량 조회에 실패했습니다. 이 오류만으로 카드가 가득 찼는지 판단할 수 없으며 남은 용량은 확인되지 않았습니다.',
         'The SD capacity check failed. This does not establish that the card is full; remaining capacity is unknown.'),
        ('보드 전원을 유지하고 오류 상세를 확인하세요. 기록이 정지된 상태에서 연결과 SD 카드 상태를 확인한 뒤 다시 조회하세요.',
         'Keep the board powered and review the error details. With recording stopped, check the connection and SD card, then retry.'),
    ),
    'cancelled': (
        ('연결 작업을 종료했습니다', 'Connection operation was cancelled'),
        ('사용자 요청으로 PC 통신을 종료했습니다. 보드 기록이 자동으로 종료된 것은 아닙니다.',
         'PC communication was cancelled by the user. This does not automatically stop recording on the board.'),
        ('기록 상태 확인이나 저장이 필요하면 다시 연결한 뒤 상태 확인을 누르세요.',
         'If you need to check recording or save it, reconnect and Check status.'),
    ),
    'unknown': (
        ('작업 중 오류가 발생했습니다', 'An error occurred during the operation'),
        ('현재 오류만으로 원인을 분류하지 못했습니다. 아래 상세 오류를 확인해야 합니다.',
         'The cause could not be classified from this error. Review the detailed message below.'),
        ('보드 전원을 유지하고 상세 오류와 현재 연결·저장 상태를 확인하세요. 상태 확인 후 기록이 종료된 경우 필요한 SD 로그를 다시 받으세요.',
         'Keep the board powered and check the details, connection and save state. Check status; if recording has stopped, retrieve any required SD log again.'),
    ),
}


def error_guidance(error, context='operation'):
    """Return bilingual guidance without treating a PC save error as a COM fault.

    Contexts: open_port, operation, status, live, capacity, save, excel, open_file.
    Only ``excel`` asserts that a raw capture was already preserved; callers
    must use it only after successful raw preservation and failed XLSX export.
    ``detail`` is always the original str(error), including paths and OS codes.
    """
    detail = str(error)
    text = detail.casefold()
    errnos, winerrors = set(), set()
    current, seen = error, set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        errnos.add(getattr(current, 'errno', None))
        winerrors.add(getattr(current, 'winerror', None))
        current = current.__cause__ or current.__context__
    errnos.update(int(value) for value in re.findall(r'\[errno\s+(\d+)\]', text))
    errnos.update(int(value) for value in re.findall(r'(?:oserror|permissionerror|filenotfounderror)\((\d+),', text))
    winerrors.update(int(value) for value in re.findall(r'\[winerror\s+(\d+)\]', text))
    winerrors.update(int(value) for value in re.findall(r'none,\s*(\d+)\)', text))

    def has(*phrases):
        return any(phrase in text for phrase in phrases)

    save_context = context in ('save', 'excel')
    missing = isinstance(error, FileNotFoundError) or 2 in errnos or bool(winerrors & {2, 3}) or has('filenotfounderror', 'cannot find the file', '지정된 파일을 찾을 수')
    denied = isinstance(error, PermissionError) or bool(errnos & {13, 30}) or bool(winerrors & {5, 32}) or has('permissionerror', 'permission denied', 'access is denied', 'access denied', 'read-only', '읽기 전용', '액세스가 거부', '다른 프로세스가 파일을 사용')
    disk_full = bool(errnos & {28, 112}) or 112 in winerrors or has('no space left on device', 'disk full', '디스크 공간이 부족', '저장 공간이 부족')
    serial_context = context in ('open_port', 'operation', 'status', 'live', 'capacity')

    if context == 'open_file':
        code = 'open_file'
    elif save_context and disk_full:
        code = 'pc_disk_full'
    elif save_context and denied:
        code = 'save_permission'
    elif save_context and (isinstance(error, FileExistsError) or 17 in errnos or 183 in winerrors or has('fileexistserror', 'already exists', '출력 파일 충돌')):
        code = 'save_collision'
    elif (has('openpyxl') and has('no module named', 'cannot import', 'modulenotfounderror', 'importerror')) or (context == 'excel' and isinstance(error, ImportError)):
        code = 'excel_dependency'
    elif context == 'excel':
        code = 'excel_save'
    elif context == 'save' and missing:
        code = 'save_path_missing'
    elif context == 'save':
        code = 'save_failed'
    elif re.search(r'\bsd\s+(?:not ready|init failed)\b|\bsd ready\s*:\s*0\b', text) or has('sd 카드 준비 안 됨'):
        code = 'sd_not_ready'
    elif has('error: root open', 'sd root open failed', 'error: sd root read failed'):
        code = 'sd_root'
    elif has('error: sd read', 'error: file read', 'error: read failed', 'error: file open failed', 'sd read failed', 'sd file open failed', 'error: sd log read failed'):
        code = 'sd_read'
    elif has('error: sd write', 'error: file write', 'error: write failed', 'sd write failed'):
        code = 'sd_write'
    elif has('error: file not found', 'error: sd log open failed'):
        code = 'sd_file_missing'
    elif has('error: sd create failed'):
        code = 'sd_create'
    elif has('error: run names exhausted'):
        code = 'run_names_full'
    elif has('error: start failed'):
        code = 'start_failed'
    elif has('error: stop first'):
        code = 'stop_required'
    elif has('error: invalid file name', '예상하지 않은 sd 파일명', 'unexpected sd filename'):
        code = 'invalid_filename'
    elif serial_context and (121 in winerrors or 121 in errnos or has('semaphore timeout', '세마포', 'write timeout', 'serial timeout')):
        code = 'serial_timeout'
    elif context == 'open_port' and missing:
        code = 'port_missing'
    elif context == 'open_port' and denied:
        code = 'port_busy'
    elif has('ready: send start', '보드 재시작', 'board restart'):
        code = 'board_reset'
    elif has('live stream timed out', '실시간 센서 응답 중단'):
        code = 'live_timeout'
    elif has('live events lost', '센서 변화 수신 누락', 'live sequence restarted', '실시간 수신 순서 재설정'):
        code = 'live_gap'
    elif has('protocol mismatch', '보드 통신 규약 불일치', 'unknown command', 'error: command too long'):
        code = 'protocol_mismatch'
    elif has('status response timed out', '상태 응답 시간 초과', 'status timed out', 'status timeout'):
        code = 'status_timeout'
    elif has('package_v2 firmware/status required', '상태 미확인', '보드 상태 확인 실패'):
        code = 'status_unconfirmed'
    elif has('start not confirmed', '시작 미확인', 'start 응답을 확인하지 못', '새 run 파일을 확인하지 못'):
        code = 'start_unconfirmed'
    elif has('stop 및 file 응답 확인 실패', 'stop 뒤 file 응답이 없습니다', 'stop/file confirmation failed', 'no file response after stop', 'stop 응답 대기 만료'):
        code = 'stop_unconfirmed'
    elif has('sd file list timed out', 'sd 파일 목록 수신 시간 초과', '로그 수신 무응답 시간 초과', '전체 수신 제한 시간 초과', 'log reception timed out', 'total reception timeout'):
        code = 'download_timeout'
    elif has('이전 전송이 계속', 'previous transfer is still active'):
        code = 'transfer_busy'
    elif has('로그 크기 제한', 'log exceeds the 128 mib'):
        code = 'transfer_too_large'
    elif has('invalid csv', 'unsupported csv header', 'incorrect column count', 'invalid event at row', 'invalid number:', 'out of range:',
             'missing start', 'duplicate start', 'unexpected end', 'missing end', 'timestamp precedes start', 'run time mismatch',
             'cds baseline/delta mismatch', 'missing transfer checksum', 'transfer length mismatch', 'transfer checksum mismatch',
             'invalid live frame', 'invalid live value', '수신 줄 길이 초과', 'incoming line too long') or (has('stop 파일(') and has('수신 파일(')):
        code = 'transfer_invalid'
    elif serial_context and (5 in errnos or (denied and context != 'open_port') or bool(winerrors & {6, 31, 995, 1167}) or has('getoverlappedresult', 'clearcommerror', 'readfile failed', 'writefile failed', 'input/output error', 'device disconnected', '장치가 연결되어 있지', '명령 송신이 완료되지 않았습니다', 'command transmission did not complete', 'attempting to use a port that is not open')):
        code = 'disconnected'
    elif isinstance(error, InterruptedError) or has('사용자가 연결을 종료했습니다', 'disconnected by the user'):
        code = 'cancelled'
    elif has('sd capacity unsupported:'):
        code = 'capacity_unsupported'
    elif has('sd capacity timed out'):
        code = 'capacity_timeout'
    elif has('sd capacity response invalid:'):
        code = 'capacity_invalid'
    elif context == 'capacity' or has('sd capacity failed:'):
        code = 'capacity_failed'
    else:
        code = 'unknown'

    title, reason, action = _ERROR_GUIDANCE[code]
    if context == 'excel':
        reason = ('수신 원본은 이미 보존되었습니다. ' + reason[0],
                  'The received raw data has already been preserved. ' + reason[1])
    return {'code': code, 'title': '\n'.join(title), 'reason': '\n'.join(reason),
            'action': '\n'.join(action), 'detail': detail}
