"""주간 화면과 같은 집계값을 한글 글꼴을 포함한 PDF로 내보냅니다."""
from io import BytesIO
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from django.utils import timezone
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak

FONT = 'HO-NanumGothic'
FONT_LOCK = Lock()
INK = colors.HexColor('#172538')
MUTED = colors.HexColor('#657486')
GREEN = colors.HexColor('#176447')
LINE = colors.HexColor('#dfe5eb')


def report_pdf(data, start, end, saved, display_name):
    with FONT_LOCK:
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT, str(Path(__file__).parent / 'pdf_fonts' / 'NanumGothic-Regular.ttf')))
    supported = pdfmetrics.getFont(FONT).face.charToGlyph

    def text(value):
        # PDF 문법으로 해석되는 태그와 글꼴에 없는 장식 문자를 처리합니다.
        plain = ''.join(c if ord(c) in supported and ord(c) >= 32 else ' ' for c in str(value))
        return escape(plain)

    body = ParagraphStyle('report-body', fontName=FONT, fontSize=9, leading=15, textColor=INK, wordWrap='CJK', spaceAfter=6)
    heading = ParagraphStyle('report-heading', parent=body, fontSize=14, leading=21, spaceBefore=14, spaceAfter=10)
    small = ParagraphStyle('report-small', parent=body, fontSize=8, leading=12, textColor=MUTED)
    center = ParagraphStyle('report-center', parent=body, alignment=TA_CENTER, fontSize=8, leading=13)
    title = ParagraphStyle('report-title', parent=body, fontSize=25, leading=35, spaceAfter=12)

    def p(value, style=body):
        return Paragraph(text(value), style)

    width = A4[0] - 84

    def table(rows, widths, header=True):
        result = Table([[p(cell, small if index == 0 and header else body) for cell in row]
                        for index, row in enumerate(rows)], colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LINEBELOW', (0, 0), (-1, -1), .4, LINE)]
        if header:
            commands.append(('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf3f8')))
        result.setStyle(TableStyle(commands))
        return result

    total = data['totals']
    change = total['weight_change']
    stats = [
        ['총 걸음 수', '운동 시간 / 횟수', '식사 기록', '체중 변화'],
        [f"{total['steps']:,}보" if total['step_days'] else '미기록',
         f"{total['minutes']:g}분 / {total['exercise_count']}건", f"{total['meal_days']}일 / {total['elapsed_days']}일",
         f'{change:+.1f} kg' if change is not None else '측정 2개 이상 필요'],
    ]
    story = [p('주간 건강 리포트', title), p(f'{start:%Y.%m.%d} - {end:%Y.%m.%d} | {display_name}'),
             p(f"한국 시간 월요일-일요일 / {data['source']['through']:%m.%d}까지 저장된 기록", small),
             Spacer(1, 12), table(stats, [width / 4] * 4), p('일주일 걸음 수', heading)]
    graph = Drawing(width, 145)
    slot = width / 7
    for index, day in enumerate(data['days']):
        x = slot * index + slot / 2
        height = day['bar_percent'] * .75
        graph.add(Rect(x-slot*.27, 30, slot*.54, 80, fillColor=colors.HexColor('#f3f6f8'), strokeColor=None))
        if height:
            graph.add(Rect(x-slot*.27, 30, slot*.54, height, fillColor=GREEN, strokeColor=None))
        value = '예정' if day['future'] else f"{day['steps']:,}" if day['known_steps'] else '미기록'
        graph.add(String(x, 12, value, fontName=FONT, fontSize=8, fillColor=INK, textAnchor='middle'))
        graph.add(String(x, 122, f"{day['weekday']} {day['date']:%m/%d}", fontName=FONT, fontSize=8, fillColor=MUTED, textAnchor='middle'))
    story.extend([graph, p('날짜별 기록 요약', heading)])
    rows = [['날짜', '걸음 수', '운동 기록', '식사 기록']]
    for day in data['days']:
        future = day['future']
        rows.append([f"{day['date']:%m/%d} ({day['weekday']})",
                     '예정' if future else f"{day['steps']:,}보" if day['known_steps'] else '미기록',
                     '예정' if future else f"{day['exercise_count']}건 / {day['minutes']:g}분",
                     '예정' if future else f"{day['meal_count']}건 / 주식사 {day['meal_slots']}끼"])
    story.extend([table(rows, [width*.2, width*.23, width*.28, width*.29]), Spacer(1, 10),
                  p('걸음 수는 수동·이전 Google Fit·Google Health 일일 집계 중 큰 값만 반영합니다. 운동 시간은 중복 구간을 제외하며, 시간 미기록 운동은 시간 합계에서 제외합니다.', small),
                  p('미기록은 미실천이나 0 섭취를 뜻하지 않습니다. 체중 변화는 이 주의 첫 측정값과 마지막 측정값의 차이입니다.', small)])
    if data['weights']:
        story.append(p('체중 측정: ' + ' / '.join(f'{w.date:%m/%d} {w.weight:g}kg' for w in data['weights']), small))
    story.extend([PageBreak(), p('목표 실천과 AI 코멘트', title), p(f'{start:%Y.%m.%d} - {end:%Y.%m.%d}', small),
                  p('저장된 목표와 운동 기록', heading)])
    if data['plan']:
        rows = [['날짜', '계획', '같은 종목의 기록']]
        for row in data['plan_rows']:
            rows.append([f"{row['date']:%m/%d}", '휴식일' if row['rest'] else f"{row['exercise_name']} {row['target_minutes']}분",
                         '예정' if row['future'] else '-' if row['rest'] else f"{row['minutes']:g}분"])
        story.extend([table(rows, [width*.2, width*.5, width*.3]),
                      p('선택한 주의 최신 저장 계획 기준입니다. 이전 실천도 현재 계획과 비교하며, 기록만으로 식단 준수 여부를 판정하지 않습니다.', small)])
    else:
        story.append(p('이 주에 생성한 실천 계획이 없습니다.'))
    story.append(p('AI 주간 코멘트', heading))
    if saved:
        when = timezone.localtime(saved.updated_at, ZoneInfo('Asia/Seoul'))
        story.append(p(f'{when:%Y.%m.%d %H:%M} 분석 (한국 시간)', small))
        if saved.source_hash != data['fingerprint']:
            story.append(p('분석 이후 기록이나 계획이 바뀌었습니다. 아래 코멘트는 이전 기록 기준입니다.', small))
        for key, label in [('highlights', '잘한 점'), ('improvements', '보완할 점'), ('next_steps', '다음 주 실천 제안')]:
            story.append(p(label, heading))
            for item in saved.analysis.get(key, []):
                story.append(p('- ' + item))
    else:
        story.append(p('저장된 AI 분석이 없습니다. 리포트 화면에서 분석을 생성한 뒤 다시 다운로드할 수 있습니다.'))
    story.extend([Spacer(1, 12), p('AI 코멘트는 일부 기록에 대한 참고 의견이며 의학적 진단·처방이 아닙니다. 다음 주 제안은 저장된 목표를 자동으로 변경하지 않습니다.', small)])
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=55, bottomMargin=48,
                                 title=f'Health Overview Weekly Report {start}', author='Health Overview')

    def page_frame(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(42, A4[1]-30, 'HEALTH OVERVIEW / WEEKLY REPORT')
        canvas.setStrokeColor(LINE)
        canvas.line(42, 35, A4[0]-42, 35)
        canvas.drawString(42, 23, f'{start:%Y.%m.%d} - {end:%Y.%m.%d}')
        canvas.drawRightString(A4[0]-42, 23, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return output.getvalue()
