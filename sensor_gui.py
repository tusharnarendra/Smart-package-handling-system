"""Start/stop desktop controls for the existing MEGA firmware."""
import queue
import re
import threading
import time
import uuid
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from serial.tools import list_ports
from sensor_i18n import bilingual
from sensor_data import EVENT_NAMES
from sensor_logger import Receiver, RecordingSession, ProtocolError, open_port, show_file, datetime, KST

def gui(folder):
    root = tk.Tk()
    root.title('센서 기록 시작/종료 · Sensor Logging Start / Stop')
    root.geometry('1080x780')
    root.minsize(980, 720)
    style = ttk.Style(root)
    style.configure('TButton', font=('맑은 고딕', 10), padding=7)
    style.configure('TLabel', font=('맑은 고딕', 10))
    outer = ttk.Frame(root, padding=16)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text=bilingual('박스 센서 기록 시작/종료'), font=('맑은 고딕', 16, 'bold')).pack(anchor='w')
    ttk.Label(outer, text=bilingual('① 연결 → ② 시작 → ③ 실험 → ④ 종료·저장'), font=('맑은 고딕', 11)).pack(anchor='w', pady=(10, 6))
    ttk.Label(outer, text=bilingual('전원 연결만으로 기록하지 않습니다. USB 또는 블루투스로 연결하세요. 시리얼 모니터는 닫아 주세요.'), foreground='#8b4513').pack(anchor='w', pady=(0, 8))
    main = ttk.Frame(outer)
    main.pack(fill='x')
    port_name = tk.StringVar(value='COM4')
    port_box = ttk.Combobox(main, textvariable=port_name, width=8, values=[p.device for p in list_ports.comports()], postcommand=lambda: port_box.configure(values=[p.device for p in list_ports.comports()]))
    port_box.pack(side='left', padx=(0, 8))
    secondary = ttk.Frame(outer)
    secondary.pack(fill='x', pady=(8, 0))
    status = tk.StringVar(value=bilingual('연결 대기 · COM4 / 9600 baud'))
    status_label = ttk.Label(outer, textvariable=status, font=('맑은 고딕', 11, 'bold'), wraplength=1030, foreground='#44546a')
    status_label.pack(anchor='w', pady=(12, 4))
    tip = tk.StringVar(value=bilingual('COM 포트 연결을 누르면 보드의 실제 기록 상태를 확인합니다.'))
    ttk.Label(outer, textvariable=tip, wraplength=1030).pack(anchor='w', pady=(0, 10))
    light_value = tk.StringVar(value='CDS: 연결 대기 · 임계값 미설정 / Awaiting connection · threshold not set')
    ttk.Label(outer, textvariable=light_value, foreground='#1d4e89', wraplength=1030).pack(anchor='w', pady=(0, 6))
    log = scrolledtext.ScrolledText(outer, font=('맑은 고딕', 10), height=7, wrap='word', state='disabled')
    log.pack(fill='both', expand=True)
    ttk.Label(outer, text=f'저장 폴더 / Output folder: {folder}', wraplength=1030).pack(anchor='w', pady=(8, 0))
    ttk.Label(outer, text='한국어·영어 CSV 2개 + 보기용 Excel / Korean & English CSVs + formatted Excel').pack(anchor='w')
    events, commands, cancel = (queue.Queue(), queue.Queue(), threading.Event())
    state = {'thread': None, 'result': None, 'closing': False}

    def emit(text):
        events.put(('log', text))

    def post_mode(mode, text):
        events.put(('mode', (mode, text)))

    def worker(name):
        port, journal = (None, None)
        try:
            logs = Path(folder) / '원본_및_수신기록'
            logs.mkdir(parents=True, exist_ok=True)
            journal = (logs / f'통신_START_{datetime.now(KST):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.txt').open('x', encoding='utf-8')
            watching = False
            next_light = time.monotonic()

            def record(text):
                journal.write(f'[PC {datetime.now(KST).isoformat()}] {text}\n')
                journal.flush()
                if text.startswith('LIGHT: '):
                    events.put(('light', text.split(': ', 1)[1]))
                    return
                if text == 'READY: SEND START':
                    post_mode('error', '보드 재시작 감지 · 상태 확인 후 SD 파일을 복구하세요.')
                if re.match(r'^[0-9]+,[A-Z_]+,', text):
                    parts = text.split(',')
                    if len(parts) == 19:
                        event = EVENT_NAMES.get(parts[1], (parts[1], parts[1]))
                        magnet_ko = lambda v: '미감지' if v == '1' else '감지'
                        press_ko = lambda v: '눌림' if v == '1' else '해제'
                        magnet_en = lambda v: 'not detected' if v == '1' else 'detected'
                        press_en = lambda v: 'pressed' if v == '1' else 'released'
                        ko = f"{event[0]} · CDS {parts[2]} (변화 {parts[16]}) · 뚜껑 자석 1 {magnet_ko(parts[7])}, 2 {magnet_ko(parts[8])} · 꼭짓점 1 {press_ko(parts[11])}, 2 {press_ko(parts[12])} · 누적 충격 {parts[5]}"
                        en = f"{event[1]} · CDS {parts[2]} (delta {parts[16]}) · Lid magnets 1 {magnet_en(parts[7])}, 2 {magnet_en(parts[8])} · Corners 1 {press_en(parts[11])}, 2 {press_en(parts[12])} · Shock count {parts[5]}"
                        events.put(('display', ko + '\n' + en))
                        return
                emit(text)
                if watching and re.match('^[0-9]+,(START|SNAPSHOT),', text):
                    post_mode('recording', '기록 중 · STOP을 누르면 종료하고 CSV로 저장합니다.')
            record(f'{name} / 9600 연결. PC 시각은 통신 시각이며 이벤트 발생 시각이 아닙니다.')
            port = open_port(name)
            receiver = Receiver(port, folder, record, cancel)
            session = RecordingSession(receiver)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                receiver.monitor()

            def sync_status():
                mode, filename = receiver.status()
                if mode == 'RECORDING':
                    post_mode('recording', f'기록 중 · {filename}')
                else:
                    post_mode('stopped', f'기록 정지 · {filename or chr(45)} · START로 새 기록을 시작하세요.')
            try:
                sync_status()
            except ProtocolError as exc:
                record(str(exc))
                post_mode('error', '상태 미확인 · 상태 확인 또는 STOP을 사용하세요.')
            while not cancel.is_set():
                try:
                    action = commands.get_nowait()
                except queue.Empty:
                    action = None
                try:
                    watching = False
                    selected_file = None
                    if isinstance(action, tuple): action, selected_file = action
                    if action == 'start':
                        post_mode('busy', '새 기록 시작 중 · 이전 기록 보존 및 START 응답 확인…')
                        filename = session.start(lambda result: events.put(('preserved', result)))
                        post_mode('recording', f'기록 중 · {filename} · 센서를 조작하며 실험하세요.')
                    elif action == 'stop':
                        post_mode('busy', '기록 종료 및 CSV 저장 중…')
                        events.put(('saved', session.stop_save()))
                    elif action == 'get':
                        post_mode('busy', '종료된 로그를 다시 받는 중…')
                        mode, filename = receiver.status()
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
                    else:
                        if receiver.protocol == 'PACKAGE_V2' and time.monotonic() >= next_light:
                            receiver.send('LIGHT')
                            next_light = time.monotonic() + 1.0
                        watching = True
                        expected = receiver.monitor()
                        watching = False
                        if expected:
                            post_mode('busy', 'STOP 감지 · CSV 자동 저장 중…')
                            events.put(('saved', session.save(expected)))
                        elif receiver.passive_at and time.monotonic() - receiver.passive_at > receiver.command_timeout:
                            receiver.passive_at, receiver.passive_stopped = (None, False)
                            raise ProtocolError('STOP 뒤 FILE 응답이 없습니다. 상태 확인 또는 로그 다시 받기를 사용하세요.')
                except ProtocolError as exc:
                    record(str(exc))
                    post_mode('error', '작업 실패 · 수신창을 확인하고 상태 확인/STOP/로그 다시 받기를 사용하세요.')
        except InterruptedError:
            emit('연결을 해제했습니다.')
        except Exception as exc:
            emit(f'연결/저장 오류: {exc}\nUSB 또는 블루투스 연결, 시리얼 모니터 종료, 저장 공간을 확인해 주세요.')
        finally:
            try:
                if port:
                    port.close()
            finally:
                if journal:
                    journal.close()
                events.put(('closed', None))

    def set_mode(mode, text):
        status.set(bilingual(text))
        colors = {'recording': '#13743a', 'stopped': '#1d4e89', 'error': '#aa2b21'}
        status_label.config(foreground=colors.get(mode, '#44546a'))
        start_btn.config(state='normal' if mode == 'stopped' else 'disabled')
        stop_btn.config(state='normal' if mode in ('recording', 'error') else 'disabled')
        retry_btn.config(state='normal' if mode in ('stopped', 'error') else 'disabled')
        check_btn.config(state='normal' if mode in ('stopped', 'recording', 'error') else 'disabled')
        tips = {'recording': '현재 측정값은 아래에 표시됩니다. STOP으로 종료·저장한 뒤 START로 다음 실험을 시작하세요.', 'stopped': '뚜껑을 닫고 기준 자세로 둔 뒤 START를 누르세요. CDS 임계값은 실측 후 설정합니다.', 'busy': '명령 처리 중입니다. 전원과 통신 연결을 유지해 주세요.', 'error': '오류 내용을 확인하세요. 전원이 끊겼다면 SD 파일 목록에서 이전 기록을 복구하세요.', 'closed': 'COM 포트 연결을 누르면 보드의 실제 기록 상태를 확인합니다.'}
        tip.set(bilingual(tips.get(mode, '보드 응답을 기다리고 있습니다.')))

    def connect():
        if state['thread'] and state['thread'].is_alive():
            return
        cancel.clear()
        while not commands.empty():
            commands.get_nowait()
        connect_btn.config(state='disabled')
        port_box.config(state='disabled')
        disconnect_btn.config(state='normal')
        set_mode('busy', '연결 및 기록 상태 확인 중…')
        state['thread'] = threading.Thread(target=worker, args=(port_name.get().strip(),), daemon=True)
        state['thread'].start()

    def command(action):
        set_mode('busy', '요청 처리 중…')
        commands.put(action)

    def disconnect():
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
    start_btn = tk.Button(main, text='기록 시작\nSTART', image=start_icon, compound='left', justify='left', command=lambda: command('start'), state='disabled', font=('맑은 고딕', 12, 'bold'), bg='#168345', fg='white', disabledforeground='#dddddd', padx=16, pady=9)
    start_btn.pack(side='left', padx=(12, 6))
    stop_btn = tk.Button(main, text='종료·저장\nSTOP · Save', image=stop_icon, compound='left', justify='left', command=lambda: command('stop'), state='disabled', font=('맑은 고딕', 12, 'bold'), bg='#ba3b35', fg='white', disabledforeground='#dddddd', padx=16, pady=9)
    stop_btn.pack(side='left', padx=6)
    check_btn = ttk.Button(secondary, text=bilingual('상태 확인'), command=lambda: command('status'), state='disabled')
    check_btn.pack(side='left', padx=(0, 4))
    retry_btn = ttk.Button(secondary, text=bilingual('로그 다시 받기'), command=lambda: command('get'), state='disabled')
    retry_btn.pack(side='left', padx=4)
    disconnect_btn = ttk.Button(secondary, text=bilingual('연결 해제'), command=disconnect, state='disabled')
    disconnect_btn.pack(side='left', padx=4)

    def open_latest():
        if state['result']:
            show_file(state['result'].get('excel') or state['result']['전체데이터'])
        else:
            os.startfile(str(folder))
    ttk.Button(secondary, text=bilingual('저장 폴더'), command=open_latest).pack(side='left', padx=4)

    def open_excel():
        if not state['result']:
            messagebox.showinfo(bilingual('보기용 Excel 열기'), bilingual('먼저 기록을 저장해 주세요.'))
        elif not state['result'].get('excel'):
            messagebox.showinfo(bilingual('보기용 Excel 열기'), bilingual('Excel 파일이 없습니다. CSV를 다시 내려받아 생성해 주세요.'))
        else:
            os.startfile(state['result']['excel'])
    ttk.Button(secondary, text=bilingual('보기용 Excel 열기'), command=open_excel).pack(side='left', padx=4)

    def pump():
        for _ in range(300):
            try:
                kind, value = events.get_nowait()
            except queue.Empty:
                break
            if kind in ('log', 'display'):
                log.config(state='normal')
                log.insert('end', (bilingual(value) if kind == 'log' else value) + '\n\n')
                if int(log.index('end-1c').split('.')[0]) > 1500:
                    log.delete('1.0', '300.0')
                log.see('end')
                log.config(state='disabled')
            elif kind == 'light':
                try:
                    adc, baseline, delta = map(int, value.split(','))
                    if baseline < 0:
                        light_value.set(f'CDS 현재 / Current: {adc} · 시작 기준값 대기 / Baseline pending · 미보정 / Uncalibrated')
                    else:
                        light_value.set(f'CDS 현재 / Current: {adc} · 시작 기준 / Baseline: {baseline} · 변화 / Delta: {delta:+d} · 미보정 / Uncalibrated')
                except ValueError:
                    emit('Invalid LIGHT response / CDS 응답 오류')
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
            elif kind in ('saved', 'preserved'):
                state['result'] = value
                emit(value['한국어CSV'])
                emit(value['영어CSV'])
                if value.get('excel'):
                    emit(value['excel'])
                if value.get('excel_error'):
                    emit('Excel 생성 실패: ' + value['excel_error'] + '\nCSV 2개는 저장됐습니다.')
                if not value.get('정상종료', True):
                    emit('미완료 기록 복구: END 없음 / Recovered incomplete log: no END marker')
                if kind == 'saved':
                    set_mode('stopped', f"저장 완료 · {value['SD_파일명']} · 전체 {value['전체행수']}행 · KO CSV + EN CSV + Excel")
                    try:
                        show_file(value.get('excel') or value['전체데이터'])
                    except OSError as exc:
                        emit(f'저장은 완료됐지만 탐색기를 열지 못했습니다: {exc}')
            elif kind == 'closed':
                connect_btn.config(state='normal')
                port_box.config(state='normal')
                disconnect_btn.config(state='disabled')
                light_value.set('CDS: 연결 해제 · 값 갱신 중지 / Disconnected · readings not updating')
                set_mode('closed', '연결 해제됨 · 수신창의 결과를 확인하세요.')
        if state['closing'] and (not (state['thread'] and state['thread'].is_alive())):
            root.destroy()
            return
        root.after(100, pump)

    def close():
        if state['thread'] and state['thread'].is_alive():
            if not messagebox.askyesno(bilingual('프로그램 종료'), bilingual('수신을 종료할까요? Arduino 기록은 자동 중지되지 않습니다.\nCSV가 필요하면 취소 후 STOP · 종료·저장을 누르세요.')):
                return
        state['closing'] = True
        disconnect()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, pump)
    root.mainloop()
