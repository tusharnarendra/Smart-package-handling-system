"""Validated sensor records and language-independent display meanings."""
import csv
import io
import re

LEGACY_HEADER = 'time_ms,event,light_adc,lid_open,tilt_raw,shock_count,wall_pressed'
REFERENCE_HEADER = LEGACY_HEADER + ',reed16_open,reed09_open,tilt_abnormal,tilt_count,wall1_pressed,wall2_pressed,wall1_count,wall2_count,shock_last_edges'
HEADER = LEGACY_HEADER + ',reed16_open,reed09_open,tilt_abnormal,tilt_count,wall1_pressed,wall2_pressed,wall1_count,wall2_count,light_baseline,light_delta,run_ms,cds_open'
KHEAD = ['경과시간', '리드 스위치', '충격 누적 횟수', '마이크로 스위치 1',
         '마이크로 스위치 2', '틸트 스위치', 'CdS 광센서']
EHEAD = ['Elapsed Time', 'Reed Switch', 'Shock Count', 'Microswitch 1',
         'Microswitch 2', 'Tilt Switch', 'CdS Light Sensor']
NUMERIC_COLUMNS = [2, 6]
EVENT_NAMES = {
    'START': ('기록 시작', 'Recording started'), 'END': ('기록 종료', 'Recording ended'),
    'SNAPSHOT': ('정기 상태 기록', 'Periodic snapshot'),
    'REED16_OPEN': ('뚜껑 1 자석 미감지', 'Lid 1 magnet not detected'), 'REED16_CLOSED': ('뚜껑 1 자석 감지', 'Lid 1 magnet detected'),
    'REED09_OPEN': ('뚜껑 2 자석 미감지', 'Lid 2 magnet not detected'), 'REED09_CLOSED': ('뚜껑 2 자석 감지', 'Lid 2 magnet detected'),
    'LID_OPEN': ('주 리드 개봉 감지', 'Primary reed detected opening'), 'LID_CLOSED': ('주 리드 닫힘 감지', 'Primary reed detected closure'),
    'WALL1_PRESSED': ('꼭짓점 1 눌림', 'Corner 1 pressed'), 'WALL1_RELEASED': ('꼭짓점 1 눌림 해제', 'Corner 1 released'),
    'WALL2_PRESSED': ('꼭짓점 2 눌림', 'Corner 2 pressed'), 'WALL2_RELEASED': ('꼭짓점 2 눌림 해제', 'Corner 2 released'),
    'TILT_DETECTED': ('기울기 시작 기준 이탈', 'Tilt departed from start'), 'TILT_NORMAL': ('기울기 시작 기준 복귀', 'Tilt returned to start'),
    'SHOCK_EVENT': ('충격 감지', 'Shock detected'), 'SHOCK_PULSE': ('충격 펄스 감지(구형)', 'Shock pulse detected (legacy)'),
    'TILT_CHANGE': ('기울기 상태 변화(구형)', 'Tilt state changed (legacy)'),
    'WALL_PRESSED': ('벽면 눌림(구형)', 'Wall pressed (legacy)'), 'WALL_RELEASED': ('벽면 해제(구형)', 'Wall released (legacy)'),
}

class ProtocolError(RuntimeError):
    pass

class ReedCycles:
    """Count observed D2 closed-to-open transitions; an initial open is a baseline."""
    def __init__(self, position=None):
        self.count = 0
        self.previous = position if position in (0, 1) else None

    def preview(self, position):
        if position not in (0, 1):
            self.previous = None
            return
        if self.previous == 0 and position == 1:
            self.count += 1
        self.previous = position


def summarize_counts(data):
    """Totals from validated raw records, never sums of cumulative row values.

    Missing legacy sensor fields remain None. Reed openings are observed D2
    transitions; switch/tilt totals exclude a final, unfinished active state.
    Incomplete logs describe only the portion successfully recovered.
    """
    totals = dict.fromkeys(('reed_count', 'shock_count', 'wall1_cycles',
                            'wall2_cycles', 'tilt_cycles'))
    if not data:
        return totals

    if all(record.get('reed16_open') in (0, 1) for record in data):
        reed = ReedCycles()
        for record in data:
            reed.preview(record['reed16_open'])
        totals['reed_count'] = reed.count

    final = data[-1]
    shock = final.get('shock_count')
    if isinstance(shock, int) and shock >= 0:
        totals['shock_count'] = shock
    for name, count_key, active_key in (
        ('wall1_cycles', 'wall1_count', 'wall1_pressed'),
        ('wall2_cycles', 'wall2_count', 'wall2_pressed'),
        ('tilt_cycles', 'tilt_count', 'tilt_abnormal'),
    ):
        count, active = final.get(count_key), final.get(active_key)
        if isinstance(count, int) and count >= 0 and active in (0, 1):
            totals[name] = max(0, count - active)
    return totals


def parse_csv(payload, allow_incomplete=False):
    try:
        text = payload.decode('ascii')
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise ProtocolError('Invalid CSV encoding or syntax / CSV 형식 오류') from exc
    if not rows or ','.join(rows[0]) not in (HEADER, LEGACY_HEADER, REFERENCE_HEADER):
        raise ProtocolError('Unsupported CSV header / 지원하지 않는 CSV 헤더')
    fields = rows.pop(0)
    while rows and not rows[-1]: rows.pop()
    warnings = []
    if allow_incomplete and rows and len(rows[-1]) != len(fields) and not text.endswith('\n'):
        rows.pop()
        warnings.append(('전원 중단으로 잘린 마지막 행 제외', 'Excluded a truncated final row after power interruption'))
    data = []
    for number, values in enumerate(rows, 2):
        if len(values) != len(fields): raise ProtocolError(f'CSV row {number}: incorrect column count / 열 개수 오류')
        r = dict(zip(fields, values))
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,63}', r['event']): raise ProtocolError(f'Invalid event at row {number}')
        for key in fields:
            if key == 'event': continue
            if not re.fullmatch('-?[0-9]+', r[key]): raise ProtocolError(f'Invalid number: row {number}, {key}')
            r[key] = int(r[key])
            if key in ('light_adc', 'light_baseline'): valid = 0 <= r[key] <= 1023
            elif key == 'light_delta': valid = -1023 <= r[key] <= 1023
            elif key == 'cds_open': valid = r[key] in (-1, 0, 1)
            elif key in ('lid_open', 'tilt_raw', 'wall_pressed', 'reed16_open', 'reed09_open', 'tilt_abnormal', 'wall1_pressed', 'wall2_pressed'): valid = r[key] in (0, 1)
            else: valid = 0 <= r[key] <= 0xffffffff
            if not valid: raise ProtocolError(f'Out of range: row {number}, {key}')
        r.update(line=number, raw=values, schema=','.join(fields))
        data.append(r)
    if not data or data[0]['event'] != 'START': raise ProtocolError('Missing START / 시작 기록 없음')
    if sum(r['event'] == 'START' for r in data) != 1: raise ProtocolError('Duplicate START / 시작 기록 중복')
    complete = data[-1]['event'] == 'END'
    if sum(r['event'] == 'END' for r in data) != int(complete): raise ProtocolError('Unexpected END / 종료 위치 오류')
    if not complete:
        if not allow_incomplete: raise ProtocolError('Missing END / 종료되지 않은 기록')
        warnings.append(('종료 기록 없음: 복구된 미완료 기록', 'No END marker: recovered incomplete recording'))
    previous = None
    offset = 0
    for r in data:
        if previous is not None and previous-r['time_ms'] > 0x80000000: offset += 0x100000000
        r['boot_unwrapped'] = r['time_ms'] + offset
        previous = r['time_ms']
    start = data[0]['boot_unwrapped']
    baseline = data[0].get('light_baseline', data[0]['light_adc'])
    for r in data:
        r['elapsed'] = r['boot_unwrapped']-start
        if r['elapsed'] < 0: raise ProtocolError('Timestamp precedes START / 시작 전 시간')
        if 'run_ms' in r and r['run_ms'] != r['elapsed'] % 0x100000000: raise ProtocolError('Run time mismatch / 실험 시간 불일치')
        if 'light_baseline' in r and (r['light_baseline'] != baseline or r['light_delta'] != r['light_adc']-baseline):
            raise ProtocolError('CDS baseline/delta mismatch / CDS 기준값·변화량 불일치')
        r['complete'] = complete
    if any(a['elapsed'] > b['elapsed'] for a,b in zip(data,data[1:])):
        warnings.append(('원본 시간 역전: 시간순 정렬함', 'Source timestamps reversed: sorted by elapsed time'))
    data.sort(key=lambda r:r['elapsed'])
    return data, warnings


def display_rows(data, language='ko'):
    english = language == 'en'

    def state(record, key, korean, translated):
        value = record.get(key)
        if value is None:
            return 'Not recorded' if english else '기록 없음'
        return (translated if english else korean)[value]

    rows = []
    for record in data:
        seconds, milliseconds = divmod(record['elapsed'], 1000)
        minutes, seconds = divmod(seconds, 60)
        rows.append([
            f'{minutes:02d}:{seconds:02d}.{milliseconds:03d}',
            state(record, 'reed16_open', ('닫힘', '열림'), ('Closed', 'Open')),
            record['shock_count'],
            state(record, 'wall1_pressed', ('해제', '눌림'), ('Released', 'Pressed')),
            state(record, 'wall2_pressed', ('해제', '눌림'), ('Released', 'Pressed')),
            state(record, 'tilt_abnormal', ('기준 자세', '기울어짐'), ('Normal', 'Tilted')),
            record['light_adc'],
        ])
    return rows
