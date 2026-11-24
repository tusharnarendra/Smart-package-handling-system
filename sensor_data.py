"""Validated sensor records and language-independent display meanings."""
import csv
import io
import re

LEGACY_HEADER = 'time_ms,event,light_adc,lid_open,tilt_raw,shock_count,wall_pressed'
REFERENCE_HEADER = LEGACY_HEADER + ',reed16_open,reed09_open,tilt_abnormal,tilt_count,wall1_pressed,wall2_pressed,wall1_count,wall2_count,shock_last_edges'
HEADER = LEGACY_HEADER + ',reed16_open,reed09_open,tilt_abnormal,tilt_count,wall1_pressed,wall2_pressed,wall1_count,wall2_count,light_baseline,light_delta,run_ms,cds_open'
KHEAD = ['실험 경과시간(초)', '실험 경과시간(HH:MM:SS.mmm)', '이벤트', '종합 개봉 상태', '감지 근거',
         'CDS 밝기 ADC값(0~1023)', '시작 CDS 기준값(ADC)', '시작 대비 CDS 변화량(ADC)', 'CDS 개봉 판정',
         '뚜껑 1 자석 감지(D2)', '뚜껑 2 자석 감지(D3)', '꼭짓점 1 눌림(D5)', '꼭짓점 1 누적 눌림 횟수',
         '꼭짓점 2 눌림(D6)', '꼭짓점 2 누적 눌림 횟수', '기울기 시작 기준 대비 상태', '기울기 기준 이탈 누적 횟수',
         '해당 행 충격 이벤트', '누적 충격 감지 횟수', '이상/특이사항', '부팅 후 시간(ms)', '원문 이벤트',
         '기울기 안정화 디지털 상태(0/1)', '원본 행 번호', '기록 종료 확인']
EHEAD = ['Experiment elapsed (s)', 'Experiment elapsed (HH:MM:SS.mmm)', 'Event', 'Combined lid status', 'Detection source',
         'CDS light ADC (0-1023)', 'Starting CDS baseline (ADC)', 'CDS change from start (ADC)', 'CDS opening assessment',
         'Lid 1 magnet detected (D2)', 'Lid 2 magnet detected (D3)', 'Corner 1 pressed (D5)', 'Corner 1 press count',
         'Corner 2 pressed (D6)', 'Corner 2 press count', 'Tilt relative to start', 'Tilt departure count',
         'Shock event in this row', 'Cumulative shock detections', 'Observations / flags', 'Time since boot (ms)', 'Source event',
         'Stable digital tilt state (0/1)', 'Source row number', 'Recording end confirmed']
NUMERIC_COLUMNS = [5, 6, 7, 12, 14, 16, 18, 20, 22, 23]
EVENT_NAMES = {
    'START': ('기록 시작', 'Recording started'), 'END': ('기록 종료', 'Recording ended'),
    'ARRIVED': ('도착 표시', 'Arrival marked'),
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
        r.setdefault('light_baseline', baseline)
        r.setdefault('light_delta', r['light_adc']-baseline)
        r.setdefault('cds_open', -1)
        r['complete'] = complete
    if any(a['elapsed'] > b['elapsed'] for a,b in zip(data,data[1:])):
        warnings.append(('원본 시간 역전: 시간순 정렬함', 'Source timestamps reversed: sorted by elapsed time'))
    data.sort(key=lambda r:r['elapsed'])
    return data, warnings

def display_rows(data, warnings, language='ko'):
    lang = int(language == 'en')
    def tr(ko, en): return (ko,en)[lang]
    def state(v, ko_yes, en_yes, ko_no, en_no):
        return tr('기록 없음', 'Not recorded') if v is None else tr(ko_yes,en_yes) if v else tr(ko_no,en_no)
    result = []
    for r in data:
        e = r['event']
        r1, r2 = r.get('reed16_open'), r.get('reed09_open')
        # Legacy logs only know a primary lid sensor, never fabricate the second.
        any_open = bool(r1 or r2) if r1 is not None else bool(r['lid_open'])
        cds = r['cds_open']
        evidence = []
        if cds == 1: evidence.append('CDS')
        if r1: evidence.append(tr('리드 1', 'Reed 1'))
        if r2: evidence.append(tr('리드 2', 'Reed 2'))
        if r1 is None and any_open: evidence.append(tr('주 리드(구형)', 'Primary reed (legacy)'))
        if any_open and cds == 1: overall = tr('개봉 감지: 밝기·리드', 'Opening detected: light and reed')
        elif any_open: overall = tr('개봉 감지: 리드', 'Opening detected: reed')
        elif cds == 1: overall = tr('개봉 의심: 밝기 변화', 'Possible opening: light change')
        elif cds == -1: overall = tr('리드 개봉 미감지 / CDS 미보정', 'No reed opening / CDS uncalibrated')
        else: overall = tr('개봉 징후 미감지', 'No opening indication')
        notes = [w[lang] for w in warnings]
        if cds == -1: notes.append(tr('CDS 임계값 미설정', 'CDS threshold not set'))
        for n in (1,2):
            if r.get(f'wall{n}_pressed'): notes.append(tr(f'꼭짓점 {n} 눌림; 파손 미판정', f'Corner {n} pressed; damage not assessed'))
        if r.get('tilt_abnormal'): notes.append(tr('시작 기준과 다름; 각도 미측정', 'Differs from start; angle not measured'))
        if e in ('SHOCK_EVENT','SHOCK_PULSE'): notes.append(tr('충격 감지; 세기 미측정', 'Shock detected; magnitude not measured'))
        if r['schema'] != HEADER: notes.append(tr('구형 형식: 없는 센서값은 기록 없음', 'Older format: unavailable sensor values not recorded'))
        seconds, ms = divmod(r['elapsed'],1000)
        hours, rem = divmod(seconds,3600)
        mins, secs = divmod(rem,60)
        result.append([f'{seconds}.{ms:03d}', f'{hours:02d}:{mins:02d}:{secs:02d}.{ms:03d}',
            EVENT_NAMES.get(e,(f'미정의 이벤트 ({e})',f'Unknown event ({e})'))[lang], overall,
            ', '.join(evidence) or tr('없음', 'None'), r['light_adc'], r['light_baseline'], r['light_delta'],
            tr('미보정', 'Uncalibrated') if cds == -1 else state(cds,'변화 감지','Change detected','변화 미감지','No change detected'),
            state(None if r1 is None else not r1,'감지','Detected','미감지','Not detected'),
            state(None if r2 is None else not r2,'감지','Detected','미감지','Not detected'),
            state(r.get('wall1_pressed'),'눌림','Pressed','해제','Released'),r.get('wall1_count'),
            state(r.get('wall2_pressed'),'눌림','Pressed','해제','Released'),r.get('wall2_count'),
            state(r.get('tilt_abnormal'),'기준과 다름','Different from start','기준과 같음','Same as start'),r.get('tilt_count'),
            state(e in ('SHOCK_EVENT','SHOCK_PULSE'),'있음','Yes','없음','No'),r['shock_count'], '; '.join(notes),
            r['time_ms'],e,r['tilt_raw'],r['line'],state(r['complete'],'확인','Confirmed','미완료','Incomplete')])
    return result

def friendly_rows(data, warnings):
    return display_rows(data, warnings, 'ko')
