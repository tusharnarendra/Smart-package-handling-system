"""Start/stop desktop controls for the existing MEGA firmware."""
import queue
import re
import threading
import time
import uuid
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from serial.tools import list_ports
from sensor_data import HEADER, ReedCycles
from sensor_i18n import bilingual, error_guidance
from sensor_logger import Receiver, RecordingSession, ProtocolError, open_port, open_path, show_file, datetime, KST

SD_LATCH_CODES = frozenset(('sd_not_ready', 'sd_root', 'sd_read', 'sd_write',
                            'sd_create', 'sd_file_missing', 'start_failed', 'run_names_full'))
SD_READ_CODES = frozenset(('sd_root', 'sd_read', 'sd_file_missing'))


class StorageRecoveryGuard:
    """Keep an SD failure until evidence stronger than cached STATUS says it recovered."""
    def __init__(self):
        self.fault = None
        self.uptime = None
        self.restarted = False
        self.sd_ready = None

    def remember(self, info):
        code = info.get('code')
        if code not in SD_LATCH_CODES:
            return
        # A later read failure must not weaken an earlier write/create failure.
        if self.fault is None or (self.fault['code'] in SD_READ_CODES and code not in SD_READ_CODES):
            self.fault = info

    def observe_uptime(self, raw):
        if not re.fullmatch(r'[0-9]{1,10}', str(raw)) or int(raw) > 0xffffffff:
            return
        current = int(raw)
        if self.uptime is not None and ((current - self.uptime) & 0xffffffff) >= 0x80000000:
            self.restarted = True
        self.uptime = current

    def observe_status(self, details, allow_recovery=True):
        if 'UPTIME MS' in details:
            self.observe_uptime(details['UPTIME MS'])
        self.sd_ready = details.get('SD READY') == '1'
        fresh_initialization = (allow_recovery and self.restarted and self.sd_ready
                                and details.get('SD ERROR') == 'NONE'
                                and details.get('FIRMWARE', '').startswith(
                                    ('PACKAGE_V2_SD_CHECKED_', 'PACKAGE_V2_SD_CAPACITY_')))
        if fresh_initialization:
            self.fault = None
            self.restarted = False
        return fresh_initialization

    def verified_start(self):
        self.fault = None
        self.sd_ready = True
        self.restarted = False

    def verified_download(self):
        # Reading a file cannot prove that a previous write failure is fixed.
        if self.fault and self.fault['code'] in SD_READ_CODES and self.sd_ready is not False:
            self.fault = None

    @property
    def start_allowed(self):
        return self.fault is None and self.sd_ready is not False


def capacity_query_available(state):
    thread = state.get('thread')
    return (state.get('mode') in ('stopped', 'error') and state.get('board_state') == 'STOPPED'
            and state.get('sd_initialized') is True
            and thread is not None and thread.is_alive() and not state.get('capacity_running', False))


def capacity_summary(values):
    """Format only a validated successful result; unknown capacity is never zero."""
    if values.get('FREE_VALID') != 1:
        raise ProtocolError('SD capacity response invalid: free space is unknown')
    keys = ('CARD_BYTES', 'DATA_CAPACITY_BYTES', 'FREE_BYTES', 'ALLOCATED_OR_UNAVAILABLE_BYTES')
    if any(type(values.get(key)) is not int or values[key] < 0 for key in keys):
        raise ProtocolError('SD capacity response invalid: byte counts')
    card, data, free, allocated = (values[key] for key in keys)
    if data <= 0 or card < data or free > data or allocated != data - free:
        raise ProtocolError('SD capacity response invalid: inconsistent byte counts')
    def size(value):
        if value >= 1000000000:
            return f'{value / 1000000000:.2f} GB'
        if value >= 1000000:
            return f'{value / 1000000:.2f} MB'
        if value >= 1000:
            return f'{value / 1000:.2f} KB'
        return f'{value} B'
    return '\n'.join((
        f'전체 저장 공간 / Total storage: {size(data)}',
        f'남은 공간 / Free: {size(free)} ({100 * free / data:.2f}%)',
        f'사용·예약 공간 / Used or reserved: {size(allocated)}',
        '',
        '조회 시점 기준 / At time of check',
    ))

# CSV field, STATUS label, display name, descriptions for digital 0 and 1.
LIVE_FIELDS = (
    ('tilt_raw', 'TILT RAW', 'D7  틸트 신호 / TILT RAW', ('LOW', 'HIGH')),
    ('tilt_abnormal', 'TILT ABNORMAL', 'D7  시작 자세 대비 / TILT ABNORMAL', ('기준 자세 / Normal', '기울어짐 / Tilted')),
    ('tilt_count', 'TILT COUNT', 'D7  복귀 누적 / Completed tilts', None),
    ('reed16_open', 'REED16 OPEN', 'D2  리드 스위치 / Reed switch', ('닫힘 / Closed', '열림 / Open')),
    ('reed_count', 'REED COMPLETED COUNT', 'D2  개폐 누적 / Open-close count', None),
    ('shock_count', 'SHOCK COUNT', 'D4  충격 누적 / Shock count', None),
    ('wall1_pressed', 'WALL1 PRESSED', 'D5  마이크로 스위치 1 / Microswitch 1', ('해제 / Released', '눌림 / Pressed')),
    ('wall1_count', 'WALL1 COUNT', 'D5  눌림·해제 누적 / Completed presses', None),
    ('wall2_pressed', 'WALL2 PRESSED', 'D6  마이크로 스위치 2 / Microswitch 2', ('해제 / Released', '눌림 / Pressed')),
    ('wall2_count', 'WALL2 COUNT', 'D6  눌림·해제 누적 / Completed presses', None),
    ('light_adc', 'LIGHT ADC', 'A0  CdS 광센서 / Light ADC (0–1023)', None),
)
CSV_FIELDS = HEADER.split(',')
MONITOR_SENSORS = (
    ('reed16_open', 'D2 리드', 'D2 Reed'),
    ('shock_count', 'D4 충격 누적', 'D4 Shock count'),
    ('wall1_pressed', 'D5 스위치 1', 'D5 Microswitch 1'),
    ('wall2_pressed', 'D6 스위치 2', 'D6 Microswitch 2'),
    ('tilt_abnormal', 'D7 틸트', 'D7 Tilt'),
)
DIGITAL_LABELS = {key: labels for key, _, _, labels in LIVE_FIELDS if labels}


def monitor_segments(values, changed, english=False):
    """Format one language line, retaining which sensor segments changed."""
    for key, korean_name, english_name in MONITOR_SENSORS:
        value = values.get(key)
        label = '—' if value is None else str(value)
        if value is not None and key in DIGITAL_LABELS:
            label = DIGITAL_LABELS[key][value].split(' / ')[int(english)]
        marked = key in changed
        if key == 'tilt_abnormal':
            raw, count = values.get('tilt_raw', '—'), values.get('tilt_count', '—')
            detail = f'raw {raw}, return count {count}' if english else f'신호 {raw}, 복귀 누적 {count}'
            label = f'{label} ({detail})'
            marked = marked or bool(changed.intersection(('tilt_raw', 'tilt_count')))
        elif key in ('reed16_open', 'wall1_pressed', 'wall2_pressed'):
            count_key = 'reed_count' if key == 'reed16_open' else key.replace('_pressed', '_count')
            count = values.get(count_key, '—')
            detail = f'completed {count}' if english else f'누적 {count}회'
            label = f'{label} ({detail})'
            marked = marked or count_key in changed
        name = english_name if english else korean_name
        if key == 'shock_count' and values.get('shock_test_mode'):
            name = 'D4 Test shocks' if english else 'D4 테스트 충격'
        yield f'{"* " if marked else ""}{name} {label}', marked


class ShockPreview:
    """Offset the firmware's separate idle counter for each new sensor test."""
    def __init__(self):
        self.total = None
        self.origin = None
        self.count = 0

    def restart(self):
        self.origin = self.total
        self.count = 0

    def update(self, raw):
        if raw is None or not re.fullmatch(r'[0-9]{1,10}', str(raw)):
            self.total = self.origin = None
            self.count = 0
            return None
        total = int(raw)
        if total > 0xffffffff:
            self.total = self.origin = None
            self.count = 0
            return None
        if self.origin is None or (self.total is not None and total < self.total):
            self.origin = total
        self.total = total
        self.count = total - self.origin
        return self.count


def status_readings(details):
    values = {key: details[field] for key, field, _, _ in LIVE_FIELDS if field in details}
    if details.get('STATE') == 'STOPPED':
        values['shock_test_count'] = details.get('SHOCK TEST COUNT')
    return values


class LivePreview:
    """Decode ordered idle snapshots without treating them as experiment rows."""

    def __init__(self):
        self.previous = None
        self.dropped = None
        self.reset_detected = False

    def read(self, line):
        fields = line.split(',')
        if (len(fields) != 7 or fields[0] != 'LIVE'
                or any(not re.fullmatch(r'[0-9]{1,10}', item) for item in fields[1:])):
            raise ProtocolError('Invalid LIVE frame / 실시간 수신 형식 오류')
        seq, board_ms, bits, adc, shocks, dropped = map(int, fields[1:])
        if (max(seq, board_ms, shocks, dropped) > 0xffffffff or bits > 127 or adc > 1023):
            raise ProtocolError('Invalid LIVE value / 실시간 수신 값 오류')
        self.reset_detected = False
        warning = None
        if self.previous is not None:
            delta = (seq - self.previous) & 0xffffffff
            if delta == 0:
                return None, None
            if delta >= 0x80000000:
                self.reset_detected = True
                warning = '실시간 수신 순서 재설정 / Live sequence restarted'
            elif delta > 1 or (self.dropped is not None and dropped != self.dropped):
                warning = '일부 센서 변화 수신 누락 · 다시 테스트하세요. / Live events lost; repeat the test.'
        self.previous, self.dropped = seq, dropped
        values = {
            'reed16_open': str(bits & 1),
            'wall1_pressed': str((bits >> 2) & 1),
            'wall2_pressed': str((bits >> 3) & 1),
            'tilt_raw': str((bits >> 4) & 1),
            'tilt_abnormal': str((bits >> 5) & 1),
            'light_adc': str(adc),
            'shock_count': str(shocks),
            'shock_test_count': str(shocks),
        }
        return values, warning


class TiltCycles:
    """Count complete 0-to-1-to-0 cycles for tilt and microswitch inputs."""

    def __init__(self, position=None):
        self.count = 0
        # A test opened mid-cycle must first see normal before it can count one.
        self.previous = 0 if position == 0 else None

    def recording(self, departures, position):
        # The firmware increments on departure; a currently open excursion is unfinished.
        self.count = max(0, departures - position)
        self.previous = None

    def preview(self, position):
        if self.previous == 1 and position == 0:
            self.count += 1
        if position == 0 or self.previous is not None:
            self.previous = position


def serial_port_choices(ports, platform=None):
    """Keep actual discovered names, preferring macOS call-out devices."""
    platform = sys.platform if platform is None else platform
    devices = list(dict.fromkeys(str(port.device) for port in ports if port.device))
    if platform == 'darwin':
        devices.sort(key=lambda value: (not value.startswith('/dev/cu.'),
                                        any(part in value.lower() for part in
                                            ('bluetooth-incoming-port', 'debug-console', 'wlan-debug'))))
    return devices


def default_port(ports, platform=None, initial_port=None):
    """An explicit or manually supplied port never gets replaced by discovery."""
    if initial_port is not None:
        return str(initial_port).strip()
    platform = sys.platform if platform is None else platform
    ports = list(ports)
    if platform != 'darwin':
        return next((port.device for port in ports if 'Bluetooth' in (port.description or '')), 'COM4')
    candidates = [name for name in serial_port_choices(ports, platform)
                  if not any(part in name.lower() for part in
                             ('bluetooth-incoming-port', 'debug-console', 'wlan-debug'))]
    callout = [name for name in candidates if name.startswith('/dev/cu.')]
    candidates = callout or candidates
    descriptions = {port.device: (port.description or '') for port in ports}
    for name in candidates:
        if re.search(r'hc[-_ ]?05|bluetooth', name + ' ' + descriptions.get(name, ''), re.I):
            return name
    return candidates[0] if candidates else ''


def port_field_width(devices, selected='', platform=None):
    platform = sys.platform if platform is None else platform
    if platform != 'darwin':
        return 8
    return min(52, max(30, max((len(name) for name in [*devices, selected]), default=0) + 2))


def select_ui_font(families, platform=None, fallback='TkDefaultFont'):
    """Use an installed Korean font for both drawing and text measurement."""
    platform = sys.platform if platform is None else platform
    available = {str(family).casefold(): str(family) for family in families}
    candidates = (('Apple SD Gothic Neo', 'AppleGothic', 'Noto Sans CJK KR',
                   'Noto Sans KR', 'Arial Unicode MS', '맑은 고딕', 'Malgun Gothic')
                  if platform == 'darwin' else
                  ('맑은 고딕', 'Malgun Gothic', 'Noto Sans CJK KR', 'Noto Sans KR'))
    return next((available[name.casefold()] for name in candidates
                 if name.casefold() in available), fallback)


def gui(folder, initial_port=None):
    root = tk.Tk()
    root.title('센서 기록 시작/종료 · Sensor Logging Start / Stop')
    font_families = root.tk.splitlist(root.tk.call('font', 'families'))
    ui_font = select_ui_font(font_families, fallback=root.tk.call('font', 'actual', 'TkDefaultFont', '-family'))
    # Match the actual UI font/DPI instead of opening a maximized or fixed-width window.
    # Use the bundled Tcl font API; older standalone EXEs omit tkinter.font.
    width_fonts = {bold: root.tk.call('font', 'create', '-family', ui_font,
                                     '-size', 10, '-weight', 'bold' if bold else 'normal')
                   for bold in (False, True)}
    def text_width(text, bold=False):
        return int(root.tk.call('font', 'measure', width_fonts[bold], text))
    initial_values = {'reed16_open': 0, 'reed_count': 0, 'shock_count': 0,
                      'shock_test_mode': 1, 'wall1_pressed': 0, 'wall1_count': 0,
                      'wall2_pressed': 0, 'wall2_count': 0, 'tilt_abnormal': 0,
                      'tilt_raw': 1, 'tilt_count': 0}
    line_widths = []
    for english in (False, True):
        for initial in (False, True):
            prefix = '' if english else '[23:59:59.999] ' + ('테스트 시작 / Initial  ' if initial else '')
            segments = list(monitor_segments(initial_values, set() if initial else set(initial_values), english))
            line_widths.append(text_width(prefix + ' · ' * (len(segments)-1)) +
                               sum(text_width(segment, marked) for segment, marked in segments))
    for font_name in width_fonts.values():
        root.tk.call('font', 'delete', font_name)
    # Outer padding, tab borders, vertical scrollbar and text inset need 69 px
    # at the standard Tk scale; keep a small 3 px margin for rounded glyph widths.
    initial_width = min(max(980, max(line_widths) + 72), root.winfo_screenwidth()-60)
    root.geometry(f'{initial_width}x{min(780, root.winfo_screenheight()-90)}')
    root.minsize(min(980, root.winfo_screenwidth()-40), min(720, root.winfo_screenheight()-90))
    style = ttk.Style(root)
    style.configure('TButton', font=(ui_font, 10), padding=7)
    style.configure('TLabel', font=(ui_font, 10))
    outer = ttk.Frame(root, padding=16)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=bilingual('박스 센서 기록 시작/종료'), font=(ui_font, 16, 'bold')).pack(anchor='w')
    ttk.Label(outer, text=bilingual('전원 연결만으로 기록하지 않습니다. USB 또는 블루투스로 연결하세요. 시리얼 모니터는 닫아 주세요.'), foreground='#8b4513').pack(anchor='w', pady=(0, 8))
    main = ttk.Frame(outer)
    main.pack(fill='x')
    available_ports = list(list_ports.comports())
    port_name = tk.StringVar(value=default_port(available_ports, initial_port=initial_port))
    port_choices = serial_port_choices(available_ports)
    def refresh_ports():
        choices = serial_port_choices(list_ports.comports())
        # Updating the choices must preserve an entered /dev/cu.* or COM name.
        port_box.configure(values=choices, width=port_field_width(choices, port_name.get()))
    port_box = ttk.Combobox(main, textvariable=port_name,
                           width=port_field_width(port_choices, port_name.get()),
                           values=port_choices, postcommand=refresh_ports)
    port_box.pack(side='left', padx=(0, 8))
    secondary = ttk.Frame(outer)
    secondary.pack(fill='x', pady=(8, 0))
    status = tk.StringVar(value=f'연결 대기 · {port_name.get()} / 9600 baud\nDisconnected · {port_name.get()} / 9600 baud')
    status_label = ttk.Label(outer, textvariable=status, font=(ui_font, 11, 'bold'), wraplength=1030, foreground='#44546a')
    status_label.pack(anchor='w', pady=(12, 4))
    tip = tk.StringVar(value=bilingual('COM 포트 연결을 누르면 보드의 실제 기록 상태를 확인합니다.'))
    tip_label = ttk.Label(outer, textvariable=tip, wraplength=1030)
    tip_label.pack(anchor='w')
    def fit_status(event):
        width = max(300, event.width - 24)
        status_label.configure(wraplength=width)
        tip_label.configure(wraplength=width)
    outer.bind('<Configure>', fit_status)
    cds_value = tk.StringVar(value='—')
    cds_row = ttk.Frame(outer)
    cds_row.pack(fill='x', pady=(2, 4))
    ttk.Label(cds_row, text='CdS 광센서 (A0) · ADC').pack(side='left')
    ttk.Label(cds_row, textvariable=cds_value, font=(ui_font, 12, 'bold'),
              foreground='#1d4e89').pack(side='left', padx=8)
    tabs = ttk.Notebook(outer)
    tabs.pack(fill='both', expand=True)
    monitor_tab = ttk.Frame(tabs, padding=6)
    live_tab, log_tab = ttk.Frame(tabs, padding=6), ttk.Frame(tabs)
    tabs.add(monitor_tab, text='시리얼 모니터 / Serial monitor')
    tabs.add(live_tab, text='실시간 센서 / Live sensors')
    tabs.add(log_tab, text='통신 기록 / Serial log')
    monitor_toolbar = ttk.Frame(monitor_tab)
    monitor_toolbar.pack(fill='x', pady=(0, 4))
    ttk.Label(monitor_tab, text='* 변경된 디지털 센서 / Changed digital sensor').pack(anchor='w')
    monitor = scrolledtext.ScrolledText(monitor_tab, font=(ui_font, 10), height=7,
                                        wrap='none', state='disabled')
    monitor.tag_configure('change', foreground='#134d7a', font=(ui_font, 10, 'bold'))
    monitor_xscroll = ttk.Scrollbar(monitor_tab, orient='horizontal', command=monitor.xview)
    monitor.configure(xscrollcommand=monitor_xscroll.set)
    monitor_xscroll.pack(side='bottom', fill='x')
    monitor.pack(fill='both', expand=True)
    table = ttk.Treeview(live_tab, columns=('sensor', 'current', 'change', 'time'),
                         show='headings', selectmode='none', height=len(LIVE_FIELDS))
    for column, title, width in (
        ('sensor', '센서 / Sensor', 310), ('current', '현재 값 / Current', 195),
        ('change', '최근 변화 / Last change', 185), ('time', '변화 수신 시각 / PC time', 180),
    ):
        table.heading(column, text=title, anchor='w')
        table.column(column, width=width, minwidth=100, anchor='w')
    style.configure('Live.Treeview', rowheight=26, font=(ui_font, 10))
    table.configure(style='Live.Treeview')
    table.tag_configure('changed', background='#fff0c9')
    table.pack(fill='x')
    for key, _, label, _ in LIVE_FIELDS:
        table.insert('', 'end', iid=key, values=(label, '—', '—', '—'))
    live_note = tk.StringVar(value='연결 대기 / Awaiting connection')
    ttk.Label(live_tab, textvariable=live_note, foreground='#44546a').pack(anchor='w', pady=(5, 0))
    ttk.Label(log_tab, text=f'저장 폴더 / Output folder: {folder}', wraplength=900).pack(anchor='w')
    ttk.Label(log_tab, text='Excel · 한국어 / English').pack(anchor='w')
    log = scrolledtext.ScrolledText(log_tab, font=(ui_font, 10), height=7, wrap='word', state='disabled')
    log.pack(fill='both', expand=True)
    events, commands, cancel = (queue.Queue(), queue.Queue(), threading.Event())
    state = {'thread': None, 'result': None, 'closing': False, 'mode': 'closed',
             'preview': 'polling', 'preview_warning': None, 'tilt_stable_ms': 500,
             'problem': None, 'storage_guard': StorageRecoveryGuard(),
             'board_state': None, 'sd_initialized': None, 'capacity_running': False}
    last_values = {}
    highlight_until = {}
    last_sample_time = None
    test_baseline = None  # None while paused; otherwise the most recent displayed digital values.
    recording_baseline = {}  # Recording always displays, independently of idle sensor testing.
    tilt_cycles = TiltCycles()
    reed_cycles = ReedCycles()
    switch_cycles = {'wall1': TiltCycles(), 'wall2': TiltCycles()}
    shock_preview = ShockPreview()

    def refresh_test_controls():
        testing = test_baseline is not None
        recording_now = state['mode'] == 'recording'
        ready = state['mode'] == 'stopped'
        test_btn.configure(state='normal' if ready and not testing else 'disabled')
        end_test_btn.configure(state='normal' if testing and not recording_now else 'disabled')
        text = ('기록 중 자동 표시 / Automatic recording monitor' if recording_now else
                ('테스트 중 / Testing' if testing else '테스트 대기 / Test off'))
        if state['mode'] == 'stopped':
            if state['preview'] == 'live':
                text += '\n변화 즉시 전송 / Event stream'
            elif state['preview'] == 'waiting':
                text += '\n실시간 수신 연결 중 / Connecting live stream'
            else:
                text += '\n짧은 동작 감지: 보드 업데이트 필요\nShort presses need firmware update'
            if shock_preview.total is None and state['preview'] == 'polling':
                text += '\n충격 테스트도 업데이트 필요 / Shock test also needs update'
            if state['preview_warning']:
                text += '\n수신 누락 · 다시 테스트 / Events lost; repeat test'
        test_status.set(text)

    def append_test_reading(timestamp, recording=False):
        baseline = recording_baseline if recording else test_baseline
        if baseline is None or timestamp is None:
            return
        digital = {key: value for key, value in last_values.items() if key != 'light_adc'}
        if not digital:
            return
        initial = not baseline
        changed = {key for key, value in digital.items() if baseline.get(key) != value}
        if not changed:
            return
        baseline.update(digital)
        if initial:
            changed.clear()
        monitor.config(state='normal')
        initial_label = '기록 시작 / Initial  ' if recording else '테스트 시작 / Initial  '
        monitor.insert('end', f'[{timestamp}] ' + (initial_label if initial else ''))
        for english in (False, True):
            for index, (segment, marked) in enumerate(monitor_segments(last_values, changed, english)):
                if index:
                    monitor.insert('end', ' · ')
                monitor.insert('end', segment, ('change',) if marked else ())
            monitor.insert('end', '\n')
        monitor.insert('end', '\n')
        if int(monitor.index('end-1c').split('.')[0]) > 1500:
            monitor.delete('1.0', '301.0')
        monitor.see('end')
        monitor.config(state='disabled')

    def start_test():
        nonlocal test_baseline, tilt_cycles, reed_cycles
        state['preview_warning'] = None
        if state['mode'] == 'stopped':
            shock_preview.restart()
            if shock_preview.total is not None:
                last_values['shock_count'] = 0
                table.set('shock_count', 'current', '0')
                table.set('shock_count', 'change', '첫 수신 / Initial')
                table.set('shock_count', 'time', '—')
                table.item('shock_count', tags=())
                highlight_until.pop('shock_count', None)
            tilt_cycles = TiltCycles(last_values.get('tilt_abnormal'))
            reed_cycles = ReedCycles(last_values.get('reed16_open'))
            if 'reed16_open' in last_values:
                last_values['reed_count'] = 0
                table.set('reed_count', 'current', '0')
                table.set('reed_count', 'change', '첫 수신 / Initial')
                table.set('reed_count', 'time', '—')
                table.item('reed_count', tags=())
                highlight_until.pop('reed_count', None)
            if 'tilt_count' in last_values:
                last_values['tilt_count'] = 0
                table.set('tilt_count', 'current', '0')
                table.set('tilt_count', 'change', '첫 수신 / Initial')
                table.set('tilt_count', 'time', '—')
                table.item('tilt_count', tags=())
                highlight_until.pop('tilt_count', None)
            for key in switch_cycles:
                switch_cycles[key] = TiltCycles(last_values.get(key + '_pressed'))
                count_key = key + '_count'
                if key + '_pressed' in last_values:
                    last_values[count_key] = 0
                    table.set(count_key, 'current', '0')
                    table.set(count_key, 'change', '첫 수신 / Initial')
                    table.set(count_key, 'time', '—')
                    table.item(count_key, tags=())
                    highlight_until.pop(count_key, None)
        test_baseline = {}
        append_test_reading(last_sample_time)
        refresh_test_controls()

    def stop_test():
        nonlocal test_baseline
        test_baseline = None
        refresh_test_controls()

    def clear_monitor():
        monitor.config(state='normal')
        monitor.delete('1.0', 'end')
        monitor.config(state='disabled')

    test_btn = ttk.Button(monitor_toolbar, text='센서 테스트 / Test sensors', command=start_test)
    test_btn.pack(side='left')
    end_test_btn = ttk.Button(monitor_toolbar, text='테스트 종료 / End test', command=stop_test)
    end_test_btn.pack(side='left', padx=4)
    ttk.Button(monitor_toolbar, text='클리어 / Clear', command=clear_monitor).pack(side='left')
    test_status = tk.StringVar()
    ttk.Label(monitor_toolbar, textvariable=test_status, justify='left').pack(side='left', padx=10)
    refresh_test_controls()

    def reset_live(note):
        nonlocal last_sample_time, tilt_cycles, reed_cycles, shock_preview
        tilt_cycles = TiltCycles()
        reed_cycles = ReedCycles()
        recording_baseline.clear()
        for key in switch_cycles:
            switch_cycles[key] = TiltCycles()
        shock_preview = ShockPreview()
        state['preview_warning'] = None
        last_sample_time = None
        cds_value.set('—')
        last_values.clear()
        highlight_until.clear()
        for key, _, label, _ in LIVE_FIELDS:
            table.item(key, values=(label, '—', '—', '—'), tags=())
        live_note.set(note)

    def update_live(values, timestamp, recording):
        nonlocal last_sample_time
        # Count each accepted closed-to-open transition once, using the same
        # rule as the workbook. Repeated status/snapshot rows add no counts.
        reed_position = values.get('reed16_open')
        if reed_position in ('0', '1'):
            if recording or test_baseline is not None:
                reed_cycles.preview(int(reed_position))
            values['reed_count'] = str(reed_cycles.count)
        if 'shock_count' in values:
            last_values['shock_test_mode'] = int(not recording)
            if recording:
                table.set('shock_count', 'sensor', 'D4  기록 충격 누적 / Recording shocks')
            else:
                table.set('shock_count', 'sensor', 'D4  테스트 충격 누적 / Test shocks')
                count = shock_preview.update(values.pop('shock_test_count', None))
                if count is None:
                    values.pop('shock_count', None)
                    last_values.pop('shock_count', None)
                    table.set('shock_count', 'current', '업데이트 필요 / Update needed')
                else:
                    values['shock_count'] = str(count)
                refresh_test_controls()
        position = values.get('tilt_abnormal')
        # Replace only the live display value. The original serial and SD records retain TILT COUNT.
        departures = values.pop('tilt_count', None)
        if position in ('0', '1'):
            if recording and departures is not None and re.fullmatch(r'[0-9]{1,10}', departures):
                tilt_cycles.recording(int(departures), int(position))
            elif not recording and test_baseline is not None:
                tilt_cycles.preview(int(position))
            values['tilt_count'] = str(tilt_cycles.count)
        # Firmware wall counters count presses; the display counts completed
        # press/release cycles, just as the tilt display counts completed returns.
        # Never replace the original CSV/SD counters or use them for idle tests.
        for key, cycles in switch_cycles.items():
            pressed = values.get(key + '_pressed')
            count_key = key + '_count'
            presses = values.pop(count_key, None)
            if pressed not in ('0', '1'):
                continue
            if recording and presses is not None and re.fullmatch(r'[0-9]{1,10}', presses):
                cycles.recording(int(presses), int(pressed))
            elif not recording and test_baseline is not None:
                cycles.preview(int(pressed))
            values[count_key] = str(cycles.count)
        for key, _, _, labels in LIVE_FIELDS:
            if key not in values:
                continue
            value = values[key]
            if not re.fullmatch(r'[0-9]{1,10}', value):
                continue
            number = int(value)
            if (labels and number not in (0, 1)) or (key == 'light_adc' and number > 1023):
                continue
            previous = last_values.get(key)
            if previous == number:
                if table.set(key, 'change') == '첫 수신 / Initial':
                    table.set(key, 'change', '변화 없음 / No change')
                continue
            last_values[key] = number
            if key == 'light_adc':
                cds_value.set(str(number))
            table.set(key, 'current', f'{number} · {labels[number]}' if labels else str(number))
            if previous is None:
                table.set(key, 'change', '첫 수신 / Initial')
            else:
                table.set(key, 'change', f'{previous} → {number}')
                table.set(key, 'time', timestamp)
                table.item(key, tags=('changed',))
                highlight_until[key] = time.monotonic() + 1.3
        last_sample_time = timestamp
        append_test_reading(timestamp, recording=recording)
        tilt_seconds = state.get('tilt_stable_ms', 500) / 1000
        live_note.set(f'최근 수신 / Last received  {timestamp}   ·   D7 신호는 {tilt_seconds:g}초간 유지되면 반영됩니다. / Tilt requires {tilt_seconds:g} s.')

    def emit(text):
        events.put(('log', text))

    def post_mode(mode, text):
        events.put(('mode', (mode, text)))

    def post_problem(error, context='operation'):
        info = error_guidance(error, context=getattr(error, 'sensor_context', context))
        events.put(('problem', info))
        events.put(('diagnostic_log', '\n'.join((info['title'], info['reason'], info['action'], info['detail']))))

    def worker(name):
        port, journal = (None, None)
        phase = 'save'
        try:
            logs = Path(folder) / '원본_및_수신기록'
            logs.mkdir(parents=True, exist_ok=True)
            journal = (logs / f'통신_START_{datetime.now(KST):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.txt').open('x', encoding='utf-8')
            watching = False
            next_light = time.monotonic()
            board_mode = None
            next_preview = 0.0
            preview_query = False
            live_supported = False
            live_enabled = False
            live_ready = False
            live_preview = LivePreview()
            last_live = next_live_renew = 0.0

            def publish(values, recording=False):
                stamp = datetime.now(KST).strftime('%H:%M:%S.%f')[:-3]
                events.put(('readings', (values, stamp, recording)))

            def publish_status():
                events.put(('storage_status', dict(receiver.details)))
                raw = receiver.details.get('TILT STABLE MS', '500')
                delay = int(raw) if re.fullmatch(r'[0-9]{1,5}', raw) else 500
                events.put(('tilt_timing', delay if 1 <= delay <= 60000 else 500))
                publish(status_readings(receiver.details), recording=receiver.details.get('STATE') == 'RECORDING')

            def record(text):
                nonlocal board_mode, next_preview, last_live, live_ready
                try:
                    journal.write(f'[PC {datetime.now(KST).isoformat()}] {text}\n')
                    journal.flush()
                except OSError as exc:
                    exc.sensor_context = 'save'
                    raise
                if text.startswith('ERROR:') and watching:
                    post_problem(text)
                if text.startswith('UPTIME MS: '):
                    events.put(('board_uptime', text.split(': ', 1)[1]))
                if text.startswith('LIVE,'):
                    if live_enabled and board_mode == 'STOPPED':
                        values, warning = live_preview.read(text)
                        if values is not None:
                            last_live = time.monotonic()
                            if live_preview.reset_detected:
                                events.put(('reset_live', '실시간 수신 재시작 / Live stream restarted'))
                            if warning:
                                events.put(('live_warning', warning))
                                emit(warning)
                            if not live_ready:
                                live_ready = True
                                events.put(('preview', 'live'))
                            publish(values)
                    return
                if text.startswith('LIGHT: '):
                    fields = text[7:].split(',')
                    if len(fields) == 3:
                        publish({'light_adc': fields[0]})
                    return
                if text == 'READY: SEND START':
                    board_mode = None
                    events.put(('board_restart', None))
                    events.put(('reset_live', '보드 재시작 / Board restarted'))
                    post_problem('Board restarted / 보드 재시작 감지')
                if re.match(r'^[0-9]+,[A-Z][A-Z0-9_]*,', text):
                    parts = text.split(',')
                    if len(parts) == len(CSV_FIELDS):
                        event = parts[1]
                        if event == 'START':
                            events.put(('reset_live', '새 기록 / New recording'))
                        if watching and event != 'END' and board_mode != 'RECORDING':
                            post_mode('recording', '기록 중 · STOP을 누르면 종료하고 엑셀로 저장합니다.')
                        board_mode = 'STOPPED' if event == 'END' else 'RECORDING'
                        next_preview = time.monotonic() + 1.5
                        publish(dict(zip(CSV_FIELDS, parts)), recording=True)
                if not preview_query or text.startswith('ERROR:'):
                    emit(text)
            record(f'{name} / 9600 연결. PC 시각은 통신 시각이며 이벤트 발생 시각이 아닙니다.')
            phase = 'open_port'
            port = open_port(name)
            phase = 'operation'
            receiver = Receiver(port, folder, record, cancel)
            session = RecordingSession(receiver)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                receiver.monitor()

            def pause_preview():
                nonlocal live_enabled, live_ready
                if live_enabled:
                    # Same UART order: OFF is processed before the following command.
                    receiver.send('LIVE OFF')
                live_enabled = live_ready = False
                events.put(('preview', 'polling'))

            def resume_preview():
                nonlocal live_enabled, live_ready, live_preview, last_live, next_live_renew
                if board_mode != 'STOPPED' or not live_supported or live_enabled:
                    return
                live_preview = LivePreview()
                live_enabled, live_ready = True, False
                last_live = time.monotonic()
                next_live_renew = last_live + 2.0
                receiver.send('LIVE ON')
                events.put(('preview', 'waiting'))

            def sync_status(automatic=False):
                nonlocal board_mode, preview_query, next_preview, live_supported
                pause_preview()
                previous_mode = board_mode
                preview_query = automatic
                try:
                    mode, filename = receiver.status()
                finally:
                    preview_query = False
                publish_status()
                board_mode = mode
                live_supported = receiver.details.get('LIVE PROTOCOL') == '1'
                next_preview = time.monotonic() + 1.5
                resume_preview()
                if automatic and mode == previous_mode:
                    return
                if mode == 'RECORDING':
                    post_mode('recording', f'기록 중 · {filename}')
                else:
                    post_mode('stopped', f'기록 정지 · {filename or chr(45)} · START로 새 기록을 시작하세요.')
            try:
                sync_status()
            except ProtocolError as exc:
                events.put(('storage_fault_status', dict(receiver.details)))
                post_problem(exc, 'status')
            while not cancel.is_set():
                try:
                    action = commands.get_nowait()
                except queue.Empty:
                    action = None
                try:
                    watching = False
                    selected_file = None
                    if isinstance(action, tuple): action, selected_file = action
                    if action is not None:
                        pause_preview()
                    if action == 'start':
                        post_mode('busy', '새 기록 시작 중 · START 응답 확인…')
                        filename = session.start(lambda result: events.put(('preserved', result)))
                        board_mode = 'RECORDING'
                        events.put(('storage_verified_start', None))
                        publish_status()
                        post_mode('recording', f'기록 중 · {filename} · 센서를 조작하며 실험하세요.')
                    elif action == 'stop':
                        post_mode('busy', '기록 종료 및 엑셀 저장 중…')
                        events.put(('saved', session.stop_save()))
                        board_mode = 'STOPPED'
                        next_preview = time.monotonic() + 1.5
                    elif action == 'get':
                        post_mode('busy', '종료된 로그를 다시 받는 중…')
                        try:
                            mode, filename = receiver.status()
                            publish_status()
                        except ProtocolError as exc:
                            details = receiver.details
                            if (details.get('PROTOCOL') != 'PACKAGE_V2'
                                    or details.get('STATE') != 'STOPPED'
                                    or error_guidance(exc, 'status')['code'] not in SD_LATCH_CODES):
                                raise
                            # Explicit recovery reads remain available after SD write failure.
                            events.put(('storage_fault_status', dict(details)))
                            post_problem(exc, 'status')
                            mode, filename = 'STOPPED', details.get('FILE')
                        board_mode = mode
                        if mode == 'RECORDING':
                            post_mode('recording', f'기록 중 · {filename} · 먼저 STOP을 눌러 주세요.')
                        else:
                            files = receiver.list_files()
                            post_mode('stopped', '기록 정지 · SD 파일을 선택하세요.')
                            events.put(('files', files))
                    elif action == 'download':
                        post_mode('busy', '선택 파일 수신·검증 중…')
                        events.put(('saved', session.save(selected_file, allow_incomplete=True)))
                    elif action == 'status':
                        post_mode('busy', '보드의 현재 상태 확인 중…')
                        sync_status()
                    elif action == 'capacity':
                        try:
                            result = receiver.capacity()
                        except Exception as exc:
                            exc.sensor_context = 'capacity'
                            raise
                        # A successful SDINFO is only possible while stopped.
                        # It does not prove recovery from a storage fault.
                        board_mode = 'STOPPED'
                        live_supported = receiver.details.get('LIVE PROTOCOL') == '1'
                        next_preview = time.monotonic() + 1.5
                        events.put(('capacity_result', result))
                    elif (board_mode == 'STOPPED' and live_enabled):
                        now = time.monotonic()
                        if now - last_live > 3.0:
                            raise ProtocolError('실시간 센서 응답 중단 · 연결/상태를 확인하세요. / Live stream timed out.')
                        if now >= next_live_renew:
                            receiver.send('LIVE ON')
                            next_live_renew = now + 2.0
                        watching = True
                        expected = receiver.monitor()
                        watching = False
                        if expected:
                            post_mode('busy', 'STOP 감지 · 엑셀 자동 저장 중…')
                            events.put(('saved', session.save(expected)))
                    elif (board_mode == 'STOPPED' and receiver.protocol == 'PACKAGE_V2'
                          and not receiver.passive_stopped and time.monotonic() >= next_preview):
                        sync_status(automatic=True)
                    else:
                        if board_mode == 'RECORDING' and receiver.protocol == 'PACKAGE_V2' and time.monotonic() >= next_light:
                            receiver.send('LIGHT')
                            next_light = time.monotonic() + 1.0
                        watching = True
                        expected = receiver.monitor()
                        watching = False
                        if expected:
                            post_mode('busy', 'STOP 감지 · 엑셀 자동 저장 중…')
                            events.put(('saved', session.save(expected)))
                        elif receiver.passive_at and time.monotonic() - receiver.passive_at > receiver.command_timeout:
                            receiver.passive_at, receiver.passive_stopped = (None, False)
                            raise ProtocolError('STOP 뒤 FILE 응답이 없습니다. 상태 확인 또는 로그 다시 받기를 사용하세요.')
                    if board_mode == 'STOPPED':
                        resume_preview()
                    elif live_enabled:
                        pause_preview()
                except ProtocolError as exc:
                    try:
                        pause_preview()
                    except Exception:
                        pass  # Keep the original diagnosis if the connection also failed.
                    board_mode = None
                    post_problem(exc)
        except InterruptedError:
            emit('연결을 해제했습니다.')
        except Exception as exc:
            post_problem(exc, phase)
        finally:
            try:
                if port:
                    port.close()
            except Exception as exc:
                post_problem(exc)
            finally:
                try:
                    if journal:
                        journal.close()
                except OSError as exc:
                    post_problem(exc, 'save')
                finally:
                    events.put(('closed', None))

    def storage_guard():
        if 'storage_guard' not in state:
            state['storage_guard'] = StorageRecoveryGuard()
        return state['storage_guard']

    def render_problem():
        info = state.get('problem')
        if info:
            status.set(info['title'])
            tip.set(info['action'])
            if storage_guard().fault:
                tip.set(info['action'] + '\nSD 복구가 확인될 때까지 START를 사용할 수 없습니다.'
                        '\nSTART remains unavailable until SD recovery is verified.')
            status_label.config(foreground='#aa2b21')
        problem_btn.configure(state='normal' if info else 'disabled')

    def present_problem(info, mode='error'):
        state['capacity_running'] = False
        if info.get('code') == 'stop_required':
            state['board_state'] = 'RECORDING'
        storage_guard().remember(info)
        state['problem'] = info
        set_mode(mode, '', clear_problem=False)

    def show_problem():
        info = state.get('problem')
        if info:
            messagebox.showerror('오류 및 해결 방법 / Error and solution',
                '\n\n'.join((info['title'], info['reason'], info['action'],
                              '상세 정보 / Technical details\n' + info['detail'])))

    def set_mode(mode, text, clear_problem=True, *, text_is_bilingual=False):
        if clear_problem:
            state['problem'] = storage_guard().fault
        elif state.get('problem') is None and storage_guard().fault:
            state['problem'] = storage_guard().fault
        state['mode'] = mode
        if mode in ('stopped', 'recording'):
            state['board_state'] = mode.upper()
        elif mode == 'closed':
            state['board_state'] = None
            state['sd_initialized'] = None
            state['capacity_running'] = False
        refresh_test_controls()
        # Authored bilingual messages and saved display text must not be translated again.
        status.set(text if text_is_bilingual else bilingual(text))
        colors = {'recording': '#13743a', 'stopped': '#1d4e89', 'error': '#aa2b21'}
        status_label.config(foreground=colors.get(mode, '#44546a'))
        start_btn.config(state='normal' if mode == 'stopped' and storage_guard().start_allowed else 'disabled')
        stop_btn.config(state='normal' if mode in ('recording', 'error') else 'disabled')
        retry_btn.config(state='normal' if mode in ('stopped', 'error') else 'disabled')
        check_btn.config(state='normal' if mode in ('stopped', 'recording', 'error') else 'disabled')
        capacity_btn.config(state='normal' if capacity_query_available(state) else 'disabled',
                            text=('용량 확인 중…\nChecking capacity…' if state.get('capacity_running')
                                  else 'SD 카드 용량 확인\nCheck SD capacity'))
        tips = {'recording': '현재 측정값은 아래에 표시됩니다. STOP으로 종료·저장한 뒤 START로 다음 실험을 시작하세요.', 'stopped': 'START로 다음 실험을 시작하세요.', 'busy': '명령 처리 중입니다. 전원과 통신 연결을 유지해 주세요.', 'error': '오류 내용을 확인하세요. 전원이 끊겼다면 SD 파일 목록에서 이전 기록을 복구하세요.', 'closed': 'COM 포트 연결을 누르면 보드의 실제 기록 상태를 확인합니다.'}
        tip.set(bilingual(tips.get(mode, '보드 응답을 기다리고 있습니다.')))
        render_problem()

    def connect():
        if state['thread'] and state['thread'].is_alive():
            return
        cancel.clear()
        reset_live('첫 수신 대기 / Waiting for readings')
        while not commands.empty():
            commands.get_nowait()
        connect_btn.config(state='disabled')
        port_box.config(state='disabled')
        disconnect_btn.config(state='normal')
        set_mode('busy', '연결 및 기록 상태 확인 중…')
        state['thread'] = threading.Thread(target=worker, args=(port_name.get().strip(),), daemon=True)
        state['thread'].start()

    def command(action):
        if action == 'capacity':
            if not capacity_query_available(state):
                return
            state['capacity_previous'] = (state['mode'], status.get(), tip.get(), state.get('problem'))
            state['capacity_running'] = True
            set_mode('busy', 'SD 용량 확인 중 · 연결을 유지하세요.\nChecking SD capacity · Keep the connection active.',
                     clear_problem=False, text_is_bilingual=True)
            commands.put(action)
            return
        if action == 'start' and not storage_guard().start_allowed:
            info = storage_guard().fault or error_guidance('ERROR: SD NOT READY', 'status')
            present_problem(info, state['mode'])
            return
        set_mode('busy', '요청 처리 중…')
        commands.put(action)

    def disconnect():
        stop_test()
        cancel.set()
        set_mode('busy', '연결 종료 중…')
        disconnect_btn.config(state='disabled')
    connect_btn = ttk.Button(main, text=bilingual('COM 포트 연결'), command=connect)
    connect_btn.pack(side='left', padx=4)
    # One centered symbol beside the two language lines, independent of font glyph widths.
    def control_icon(shape):
        icon = tk.PhotoImage(master=root, width=42, height=36)
        if shape == 'play':
            for row in range(32):
                edge = 5 + round(27 * (1 - abs(row - 15.5) / 15.5))
                icon.put('white', to=(4, row + 2, edge + 1, row + 3))
        else:
            icon.put('white', to=(4, 4, 32, 32))
        return icon

    start_icon = control_icon('play')
    stop_icon = control_icon('stop')
    start_btn = tk.Button(main, text='기록 시작\nSTART', image=start_icon, compound='left', justify='left', command=lambda: command('start'), state='disabled', font=(ui_font, 12, 'bold'), bg='#168345', fg='white', disabledforeground='#dddddd', padx=16, pady=9)
    start_btn.pack(side='left', padx=(12, 6))
    stop_btn = tk.Button(main, text='종료·저장\nSTOP · Save', image=stop_icon, compound='left', justify='left', command=lambda: command('stop'), state='disabled', font=(ui_font, 12, 'bold'), bg='#ba3b35', fg='white', disabledforeground='#dddddd', padx=16, pady=9)
    stop_btn.pack(side='left', padx=6)
    check_btn = ttk.Button(secondary, text=bilingual('상태 확인'), command=lambda: command('status'), state='disabled')
    check_btn.pack(side='left', padx=(0, 4))
    retry_btn = ttk.Button(secondary, text=bilingual('로그 다시 받기'), command=lambda: command('get'), state='disabled')
    retry_btn.pack(side='left', padx=4)
    capacity_btn = ttk.Button(secondary, text='SD 카드 용량 확인\nCheck SD capacity',
                              command=lambda: command('capacity'), state='disabled')
    capacity_btn.pack(side='left', padx=4)
    disconnect_btn = ttk.Button(secondary, text=bilingual('연결 해제'), command=disconnect, state='disabled')
    disconnect_btn.pack(side='left', padx=4)
    problem_btn = ttk.Button(secondary, text='오류·해결 방법\nError details',
                             command=show_problem, state='disabled')

    def open_latest():
        try:
            if state['result']:
                show_file(state['result'].get('excel') or state['result']['전체데이터'])
            else:
                open_path(folder)
        except OSError as exc:
            present_problem(error_guidance(exc, 'open_file'), state['mode'])
    ttk.Button(secondary, text=bilingual('저장 폴더'), command=open_latest).pack(side='left', padx=4)

    def open_excel():
        if not state['result']:
            messagebox.showinfo(bilingual('보기용 Excel 열기'), bilingual('먼저 기록을 저장해 주세요.'))
        elif not state['result'].get('excel'):
            messagebox.showinfo(bilingual('보기용 Excel 열기'), bilingual('Excel 파일이 없습니다. 로그 다시 받기로 재시도해 주세요.'))
        else:
            try:
                open_path(state['result']['excel'])
            except OSError as exc:
                present_problem(error_guidance(exc, 'open_file'), state['mode'])
    ttk.Button(secondary, text=bilingual('보기용 Excel 열기'), command=open_excel).pack(side='left', padx=4)
    problem_btn.pack(side='left', padx=4)

    def pump():
        for _ in range(300):
            try:
                kind, value = events.get_nowait()
            except queue.Empty:
                break
            if kind in ('log', 'diagnostic_log'):
                log.config(state='normal')
                log.insert('end', (value if kind == 'diagnostic_log' else bilingual(value)) + '\n\n')
                if int(log.index('end-1c').split('.')[0]) > 1500:
                    log.delete('1.0', '300.0')
                log.see('end')
                log.config(state='disabled')
            elif kind == 'readings':
                update_live(*value)
            elif kind == 'preview':
                state['preview'] = value
                refresh_test_controls()
            elif kind == 'tilt_timing':
                state['tilt_stable_ms'] = value
            elif kind == 'board_uptime':
                storage_guard().observe_uptime(value)
            elif kind == 'board_restart':
                storage_guard().restarted = True
                state['board_state'] = None
                state['sd_initialized'] = None
            elif kind in ('storage_status', 'storage_fault_status'):
                if value.get('PROTOCOL') == 'PACKAGE_V2' and value.get('STATE') in ('STOPPED', 'RECORDING'):
                    state['board_state'] = value['STATE']
                    state['sd_initialized'] = (value.get('SD INITIALIZED') == '1'
                        if 'SD INITIALIZED' in value else value.get('SD READY') == '1')
                    if storage_guard().observe_status(value, allow_recovery=kind == 'storage_status'):
                        state['problem'] = None
            elif kind == 'capacity_result':
                state['capacity_running'] = False
                previous_mode, previous_status, previous_tip, previous_problem = state.pop(
                    'capacity_previous', ('stopped', bilingual('기록 정지'), '', state.get('problem')))
                state['problem'] = previous_problem
                set_mode(previous_mode, previous_status, clear_problem=False, text_is_bilingual=True)
                if not state.get('problem'):
                    tip.set(previous_tip)
                messagebox.showinfo('SD 카드 용량 / SD card capacity', capacity_summary(value))
            elif kind == 'storage_verified_start':
                storage_guard().verified_start()
                state['problem'] = None
            elif kind == 'live_warning':
                state['preview_warning'] = value
                refresh_test_controls()
                present_problem(error_guidance(value, 'live'), state['mode'])
            elif kind == 'reset_live':
                reset_live(value)
            elif kind == 'files':
                if not value:
                    messagebox.showinfo('SD 파일 / SD files', '저장된 RUN 파일이 없습니다. / No RUN files found.')
                else:
                    dialog = tk.Toplevel(root)
                    dialog.title('SD 기록 선택 / Select SD recording')
                    dialog.transient(root)
                    ttk.Label(dialog, text='전원 중단 기록은 미완료로 표시됩니다.\nPower-interrupted logs are marked incomplete.', padding=12).pack()
                    selected = tk.StringVar(value=value[0])
                    ttk.Combobox(dialog, textvariable=selected, values=value, state='readonly', width=30).pack(padx=12, pady=8)
                    def retrieve(selection=selected, window=dialog):
                        name = selection.get()
                        window.destroy()
                        command(('download', name))
                    ttk.Button(dialog, text='선택 파일 받기 / Download selected', command=retrieve).pack(padx=12, pady=12)
                    dialog.grab_set()
            elif kind == 'mode':
                set_mode(*value)
            elif kind == 'problem':
                present_problem(value)
            elif kind in ('saved', 'preserved'):
                storage_guard().verified_download()
                state['result'] = value
                if value.get('excel'):
                    emit(value['excel'])
                if value.get('excel_error'):
                    emit('Excel 생성 실패: ' + value['excel_error'] + '\n복구용 원본은 하위 폴더에 보존했습니다. / Raw data preserved.')
                if not value.get('정상종료', True):
                    emit('미완료 기록 복구: END 없음 / Recovered incomplete log: no END marker')
                if kind == 'saved':
                    set_mode('stopped', ('엑셀 생성 실패 · 원본 보존 / Excel failed; raw data preserved' if value.get('excel_error') else f"저장 완료 · {value['SD_파일명']} · 전체 {value['전체행수']}행 · Excel 1개 (한국어/English)"))
                    try:
                        show_file(value.get('excel') or value['전체데이터'])
                    except OSError as exc:
                        present_problem(error_guidance(exc, 'open_file'), state['mode'])
                if value.get('excel_error'):
                    present_problem(value.get('excel_problem') or
                                    error_guidance(value['excel_error'], 'excel'), state['mode'])
            elif kind == 'closed':
                stop_test()
                connect_btn.config(state='normal')
                port_box.config(state='normal')
                disconnect_btn.config(state='disabled')
                reset_live('연결 해제 / Disconnected')
                set_mode('closed', '연결 해제됨 · 수신창의 결과를 확인하세요.', clear_problem=False)
        for key, until in list(highlight_until.items()):
            if time.monotonic() >= until:
                table.item(key, tags=())
                del highlight_until[key]
        if state['closing'] and (not (state['thread'] and state['thread'].is_alive())):
            root.destroy()
            return
        root.after(50, pump)

    def close():
        if state['thread'] and state['thread'].is_alive():
            if not messagebox.askyesno(bilingual('프로그램 종료'), bilingual('수신을 종료할까요? Arduino 기록은 자동 중지되지 않습니다.\n엑셀이 필요하면 취소 후 STOP · 종료·저장을 누르세요.')):
                return
        state['closing'] = True
        disconnect()
    root.protocol('WM_DELETE_WINDOW', close)
    def callback_error(exception_type, exception, traceback):
        connected = state['thread'] and state['thread'].is_alive()
        present_problem(error_guidance(exception), 'error' if connected else 'closed')
    root.report_callback_exception = callback_error
    root.after(50, pump)
    root.mainloop()
