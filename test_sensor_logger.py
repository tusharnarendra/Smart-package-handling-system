import csv
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import sensor_logger as s
from sensor_data import HEADER, KHEAD, EHEAD, LEGACY_HEADER, REFERENCE_HEADER, display_rows


def payload(complete=True):
    rows = [
        [5000,'START',200,0,1,0,0,0,0,0,0,0,0,0,0,200,0,0,-1],
        [6000,'SNAPSHOT',202,0,1,0,0,0,0,0,0,0,0,0,0,200,2,1000,-1],
        [6500,'REED09_OPEN',205,1,1,0,0,0,1,0,0,0,0,0,0,200,5,1500,-1],
        [7000,'WALL2_PRESSED',800,1,1,0,1,0,1,0,0,0,1,0,1,200,600,2000,-1],
        [7500,'TILT_DETECTED',810,1,0,0,1,0,1,1,1,0,1,0,1,200,610,2500,-1],
        [8000,'SHOCK_EVENT',811,1,0,1,1,0,1,1,1,0,1,0,1,200,611,3000,-1],
        [9000,'END',815,1,0,1,1,0,1,1,1,0,1,0,1,200,615,4000,-1],
    ]
    if not complete: rows.pop()
    out = io.StringIO(newline='')
    w = csv.writer(out); w.writerow(HEADER.split(',')); w.writerows(rows)
    return out.getvalue().encode('ascii')

PAYLOAD = payload()
def checksum(data):
    n=2166136261
    for value in data: n=((n^value)*16777619)&0xffffffff
    return n

def frame(data=PAYLOAD, name='RUN03.CSV', bad_hash=False):
    return (f'BEGIN_LOG {name}\r\n'.encode()+data+b'\r\n'+
            f'LOG_BYTES: {len(data)}\r\nLOG_FNV32: {checksum(data) + int(bad_hash):X}\r\nEND_LOG\r\n'.encode())

def status(mode='STOPPED', file='-', sd=1):
    return f'PROTOCOL: PACKAGE_V2\nSTATE: {mode}\nFILE: {file}\nSD READY: {sd}\nEND_STATUS\n'.encode()

class FakeSerial:
    def __init__(self,responses=None,initial=b'',chunk=7):
        self.responses=responses or {};self.buffer=bytearray(initial);self.commands=[];self.chunk=chunk
    @property
    def in_waiting(self): return min(len(self.buffer),self.chunk)
    def read(self,size):
        if not self.buffer: time.sleep(.001);return b''
        result=bytes(self.buffer[:size]);del self.buffer[:size];return result
    def write(self,data):
        self.commands.append(data);r=self.responses.get(data,b'')
        if isinstance(r,list): r=r.pop(0) if r else b''
        self.buffer.extend(r);return len(data)
    @property
    def dtr(self): raise AssertionError('START must never use reset')
    @dtr.setter
    def dtr(self,value): raise AssertionError('START must never use reset')

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.mock=patch.object(s,'create_readable_workbook',return_value=None);self.mock.start()
    def tearDown(self): self.mock.stop();self.tmp.cleanup()
    def rx(self,fake,**kw):
        r=s.Receiver(fake,self.folder,lambda x:None,command_timeout=.06,idle_timeout=.04,total_timeout=.3,start_timeout=.04,**kw)
        r.protocol='PACKAGE_V2';return r
    def test_start_uses_command_without_reset(self):
        f=FakeSerial({b'STATUS\n':[status(),status('RECORDING','RUN03.CSV')],b'START\n':b'RECORDING FILE: RUN03.CSV\nRECORDING STARTED\n'})
        self.assertEqual(s.RecordingSession(self.rx(f)).start(),'RUN03.CSV')
        self.assertEqual(f.commands,[b'STATUS\n',b'START\n',b'STATUS\n'])
    def test_lost_start_ack_queries_status_no_repeat(self):
        f=FakeSerial({b'STATUS\n':status('RECORDING','RUN03.CSV')})
        self.assertEqual(self.rx(f).begin_new(),'RUN03.CSV')
        self.assertEqual(f.commands.count(b'START\n'),1)
    def test_already_recording_keeps_run(self):
        f=FakeSerial({b'STATUS\n':status('RECORDING','RUN03.CSV')})
        self.assertEqual(s.RecordingSession(self.rx(f)).start(),'RUN03.CSV')
        self.assertNotIn(b'START\n',f.commands)
    def test_sd_not_ready_blocks_start(self):
        f=FakeSerial({b'STATUS\n':status(sd=0)})
        with self.assertRaises(s.ProtocolError):s.RecordingSession(self.rx(f)).start()
        self.assertNotIn(b'START\n',f.commands)
    def test_old_firmware_cannot_trigger_reset(self):
        f=FakeSerial({b'STATUS\n':b'STOPPED\nFILE: RUN03.CSV\n'})
        with self.assertRaises(s.ProtocolError):s.RecordingSession(self.rx(f)).start()
        self.assertEqual(f.commands,[b'STATUS\n'])
    def test_stop_and_bilingual_exports(self):
        f=FakeSerial({b'STOP\n':b'RECORDING STOPPED\nFILE: RUN03.CSV\n',b'GET_LOG RUN03.CSV\n':frame()})
        r=self.rx(f);result=r.download(r.stop())
        self.assertTrue(result['정상종료']);self.assertEqual(result['전체행수'],7)
        ko=list(csv.reader(io.StringIO(Path(result['한국어CSV']).read_text(encoding='utf-8-sig'))))
        en=list(csv.reader(io.StringIO(Path(result['영어CSV']).read_text(encoding='utf-8-sig'))))
        self.assertEqual(ko[0],KHEAD);self.assertEqual(en[0],EHEAD)
        self.assertEqual(ko[1][:2],['0.000','00:00:00.000'])
        self.assertEqual(ko[3][10],'미감지');self.assertEqual(ko[4][13],'눌림')
        self.assertEqual(ko[6][17],'있음');self.assertEqual(ko[7][17],'없음')
        self.assertEqual(ko[1][8],'미보정');self.assertIn('CDS 미보정',ko[1][3])
        self.assertEqual(ko[7][7],'615');self.assertEqual(ko[1][20],'5000')
        self.assertEqual(len(list(self.folder.glob('*.csv'))),2)
        self.assertFalse(any('가'<=c<='힣' for row in en for cell in row for c in cell))
        self.assertTrue(Path(result['한국어CSV']).read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual(Path(result['원본']).read_bytes(),PAYLOAD)
        self.assertFalse(any('접점' in c or 'edges' in c for c in ko[0]+en[0]))
    def test_named_download_after_reboot(self):
        f=FakeSerial({b'LIST\n':b'FILES_BEGIN\nRUN00.CSV\nRUN03.CSV\nFILES_END\n',b'GET_LOG RUN03.CSV\n':frame()})
        r=self.rx(f);self.assertEqual(r.list_files(),['RUN03.CSV','RUN00.CSV']);self.assertEqual(r.download('RUN03.CSV')['전체행수'],7)
    def test_incomplete_recovery_explicitly_marked(self):
        with self.assertRaises(s.ProtocolError): s.parse_csv(payload(False))
        result=s.save_result(self.folder,'RUN03.CSV',payload(False),allow_incomplete=True)
        self.assertFalse(result['정상종료'])
        self.assertIn('Incomplete',Path(result['영어CSV']).read_text(encoding='utf-8-sig'))
    def test_power_cut_partial_row_is_preserved(self):
        raw=payload(False)+b'8500,SNAPSHOT,2'
        result=s.save_result(self.folder,'RUN03.CSV',raw,allow_incomplete=True)
        self.assertEqual(result['전체행수'],6);self.assertEqual(Path(result['원본']).read_bytes(),raw)
    def test_corrupt_checksum_rejected(self):
        f=FakeSerial({b'GET_LOG RUN03.CSV\n':frame(bad_hash=True)})
        with self.assertRaises(s.ProtocolError):self.rx(f,attempts=1).download('RUN03.CSV')
        self.assertFalse(list(self.folder.glob('*.csv')));self.assertTrue(list(self.folder.rglob('*.partial')))
    def test_checksum_required_on_v2(self):
        f=FakeSerial({b'GET_LOG RUN03.CSV\n':b'BEGIN_LOG RUN03.CSV\n'+PAYLOAD+b'END_LOG\n'})
        with self.assertRaises(s.ProtocolError):self.rx(f,attempts=1).download('RUN03.CSV')
    def test_no_newline_in_interrupted_file(self):
        raw=payload(False).rstrip(b'\r\n')
        f=FakeSerial({b'GET_LOG RUN03.CSV\n':frame(raw)})
        result=self.rx(f).download('RUN03.CSV',allow_incomplete=True)
        self.assertEqual(Path(result['원본']).read_bytes(),raw)
    def test_wrong_file_rejected(self):
        with self.assertRaises(s.ProtocolError):self.rx(FakeSerial({b'GET_LOG RUN03.CSV\n':frame(name='RUN04.CSV')}),attempts=1).download('RUN03.CSV')
    def test_missing_transfer_end_preserved(self):
        with self.assertRaises(s.ProtocolError):self.rx(FakeSerial({b'GET_LOG RUN03.CSV\n':frame()[:-10]}),attempts=1).download('RUN03.CSV')
        self.assertTrue(list(self.folder.rglob('*.partial')))
    def test_already_stopped_is_idempotent(self):
        f=FakeSerial({b'STOP\n':b'ALREADY STOPPED\nFILE: RUN03.CSV\n'})
        self.assertEqual(self.rx(f).stop(),'RUN03.CSV')
    def test_invalid_sensor_delta_and_time(self):
        for bad in [PAYLOAD.replace(b'200,0,0,-1',b'200,1,0,-1'),PAYLOAD.replace(b'200,2,1000,-1',b'200,2,999,-1'),PAYLOAD.replace(b'202,0,1',b'1024,0,1'),PAYLOAD.replace(b'START',b'=SUM(A1)')]:
            with self.subTest(bad=bad[:30]),self.assertRaises(s.ProtocolError):s.parse_csv(bad)
    def test_cds_not_assumed_from_large_delta(self):
        data,w=s.parse_csv(PAYLOAD);rows=display_rows(data,w)
        self.assertEqual(rows[-1][8],'미보정');self.assertEqual(rows[-1][4],'리드 2')
    def test_legacy_7_column_missing_values_not_invented(self):
        data,w=s.parse_csv((LEGACY_HEADER+'\n100,START,20,0,1,0,0\n200,END,25,0,1,0,0\n').encode())
        row=display_rows(data,w)[0];self.assertEqual(row[10],'기록 없음');self.assertIsNone(row[14])
    def test_reference_16_column_without_edges_display(self):
        raw=(REFERENCE_HEADER+'\n100,START,20,0,1,0,0,0,0,0,0,0,0,0,0,0\n200,END,25,0,1,0,0,0,0,0,0,0,0,0,0,0\n').encode()
        data,w=s.parse_csv(raw);self.assertEqual(len(display_rows(data,w)[0]),25)
    def test_rollover_is_elapsed_since_start(self):
        raw=(LEGACY_HEADER+'\n4294967290,START,20,0,1,0,0\n5,END,25,0,1,0,0\n').encode()
        data,w=s.parse_csv(raw);self.assertEqual(display_rows(data,w)[1][0],'0.011')
    def test_no_overwrite(self):
        a=s.save_result(self.folder,'RUN03.CSV',PAYLOAD);b=s.save_result(self.folder,'RUN03.CSV',PAYLOAD)
        self.assertNotEqual(a['한국어CSV'],b['한국어CSV'])
    def test_excel_failure_keeps_csvs(self):
        with patch.object(s,'create_readable_workbook',side_effect=RuntimeError('test')):r=s.save_result(self.folder,'RUN03.CSV',PAYLOAD)
        self.assertIn('excel_error',r);self.assertEqual(len(list(self.folder.glob('*.csv'))),2)
    def test_path_safety(self):
        for name in ['../RUN03.CSV','C:\\RUN03.CSV','=test.csv']:
            with self.assertRaises(s.ProtocolError):s.safe_name(name)
    def test_cancel_does_not_send(self):
        f=FakeSerial();r=self.rx(f);r.cancel.set()
        with self.assertRaises(InterruptedError):r.download()
        self.assertFalse(f.commands)

if __name__=='__main__':unittest.main()
