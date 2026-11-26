"""One bilingual XLSX per run, with no Node or Microsoft Office dependency."""
from pathlib import Path
import math
import tempfile
import sys
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

WIDTHS = [17, 16, 19, 21, 21, 16, 20]


def create_readable_workbook(path, khead, korean_rows, english_data, preview=False, *, totals=None):
    from sensor_data import EHEAD, NUMERIC_COLUMNS
    font_name = 'Apple SD Gothic Neo' if sys.platform == 'darwin' else 'Malgun Gothic'
    destination = Path(path)
    if destination.exists(): raise FileExistsError(str(destination))
    wb = Workbook(); wb.remove(wb.active)
    wb.properties.title = 'Package and Cargo Sensor Report'
    wb.properties.description = 'Sensor readings from the original Arduino log.'
    try:
        for name, headers, rows, table_name in (
            ('한국어', khead, korean_rows, 'KoreanSensorData'),
            ('English', EHEAD, english_data, 'EnglishSensorData')):
            if len(headers) != len(WIDTHS): raise ValueError('Expected 7 report columns')
            ws = wb.create_sheet(name)
            ws.freeze_panes = 'B2'
            ws.sheet_view.showGridLines = False
            ws.sheet_view.zoomScale = 85
            for col, header in enumerate(headers, 1):
                cell = ws.cell(1,col,str(header)); cell.data_type = 's'
                cell.font = Font(name=font_name,size=11,bold=True,color='FFFFFF')
                cell.fill = PatternFill('solid',fgColor='203C59')
                cell.alignment = Alignment(horizontal='center',vertical='center',wrap_text=True)
                ws.column_dimensions[get_column_letter(col)].width = WIDTHS[col-1]
            ws.row_dimensions[1].height = 60
            previous = None
            for rownum, raw in enumerate(rows,2):
                if len(raw)!= len(headers): raise ValueError('Report row must have 7 values')
                height = 30
                for col, value in enumerate(raw):
                    cell = ws.cell(rownum,col+1)
                    if value is not None:
                        if col in NUMERIC_COLUMNS:
                            cell.value = int(value)
                            cell.number_format = '0'
                        else:
                            cell.value = str(value); cell.data_type='s'
                            cell.number_format = '@'
                    cell.font = Font(name=font_name,size=11)
                    cell.alignment = Alignment(vertical='center',wrap_text=True,
                                               horizontal='center')
                    if rownum % 2: cell.fill=PatternFill('solid',fgColor='F2F5F8')
                    if previous is not None and col > 0 and value!=previous[col]:
                        cell.fill=PatternFill('solid',fgColor='FFF2CC')
                    length=sum(2 if ord(c)>255 else 1 for c in str(value or ''))
                    height=max(height, math.ceil(length/max(8,WIDTHS[col]-2))*16+8)
                ws.row_dimensions[rownum].height=min(409,height)
                previous=raw
            table=Table(displayName=table_name,ref=f'A1:{get_column_letter(len(headers))}{ws.max_row}')
            table.tableStyleInfo=TableStyleInfo(name='TableStyleMedium2',showRowStripes=False)
            ws.add_table(table)
            # Keep totals outside the data table so sorting/filtering never moves
            # the summary into the measured rows. Old direct callers may omit
            # raw-derived totals; display missing values rather than guess.
            footer_row = ws.max_row + 1
            english = name == 'English'
            footer = ['Total counts' if english else '누적합계']
            for key in ('reed_count', 'shock_count', 'wall1_cycles', 'wall2_cycles', 'tilt_cycles'):
                value = None if totals is None else totals.get(key)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f'Invalid total count: {key}')
                footer.append(value if value is not None else ('Not recorded' if english else '기록 없음'))
            footer.append('—')
            for col, value in enumerate(footer, 1):
                cell = ws.cell(footer_row, col, value)
                cell.font = Font(name=font_name,size=11,bold=True,color='FFFFFF')
                cell.fill = PatternFill('solid',fgColor='203C59')
                cell.alignment = Alignment(horizontal='center',vertical='center',wrap_text=True)
                if type(value) is int:
                    cell.number_format = ('[=1]0" time";0" times"' if english else '0" 회"')
                else:
                    cell.data_type = 's'; cell.number_format = '@'
            ws.row_dimensions[footer_row].height = 30
            ws.print_title_rows='1:1'
            ws.sheet_properties.pageSetUpPr.fitToPage=True
            ws.page_setup.orientation='landscape'
            ws.page_setup.paperSize=ws.PAPERSIZE_A3
            ws.page_setup.fitToWidth=1; ws.page_setup.fitToHeight=0
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.sensor_excel_',suffix='.xlsx',dir=destination.parent,delete=False) as f:
            temp=Path(f.name)
        try:
            wb.save(temp)
            temp.rename(destination)
        finally:
            if temp.exists(): temp.unlink()
        return str(destination)
    finally:
        wb.close()
