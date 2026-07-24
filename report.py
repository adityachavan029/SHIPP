import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import encoding as enc

# ── Colour palette ────────────────────────────────────────────────────────────
RED   = colors.HexColor("#C0392B")
BLUE  = colors.HexColor("#1A5276")
GREEN = colors.HexColor("#1E8449")
DARK  = colors.HexColor("#1C2833")
GREY  = colors.HexColor("#F2F3F4")
MID   = colors.HexColor("#D5D8DC")
WHITE = colors.white
BLACK = colors.black

# ── Helpers ───────────────────────────────────────────────────────────────────
def _seg_xml(code, type_id):
    """
    Colour-encode the binary code string (x-y-type-angle) for a Paragraph.
    Segments separated by '-'.  Colour scheme:
        x     → BLUE
        y     → GREEN
        type  → RED
        angle → DARK
    """
    segs = code.split("-")
    pal  = [BLUE, GREEN, RED, DARK]
    parts = []
    for i, seg in enumerate(segs):
        col = pal[i % len(pal)].hexval() if i < len(pal) else DARK.hexval()
        parts.append(f'<font color="{col}">{seg}</font>')
    return "-".join(parts)


def _bitstream_xml(bs, table_rows):
    """
    Rebuild the bitstream with colour-coded segments matching the table rows.
    Each minutia's bits alternate colours: BLUE / RED (matching the reference).
    """
    palette = [BLUE, RED, GREEN, DARK]
    parts   = []
    idx     = 0
    for i, row in enumerate(table_rows):
        length = row["bit_count"]
        chunk  = bs[idx: idx + length]
        col    = palette[i % len(palette)].hexval()
        parts.append(f'<font color="{col}">{chunk}</font>')
        idx   += length
    return "".join(parts)


# ── Main generator ────────────────────────────────────────────────────────────
def generate_pdf(stats, image_path, output_path="output_images/fingerprint_report.pdf"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=2*cm,    bottomMargin=2*cm,
    )

    W, H   = A4
    styles = getSampleStyleSheet()
    story  = []

    # ── Title ─────────────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=DARK,
        spaceAfter=4,
        spaceBefore=0,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    sub_style = ParagraphStyle(
        "SubTitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#717D7E"),
        alignment=TA_CENTER,
        spaceAfter=14,
    )
    story.append(Paragraph("Fingerprint Minutiae Extraction Report", title_style))
    story.append(Paragraph(
        f"Input image: <b>{image_path}</b> &nbsp;|&nbsp; "
        f"Total minutiae: <b>{len(stats['table_rows'])}</b>",
        sub_style
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=MID, spaceAfter=10))

    # ── Minutiae Table ────────────────────────────────────────────────────────
    cell_style = ParagraphStyle(
        "CellCenter",
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_CENTER,
        leading=11,
    )
    hdr_style = ParagraphStyle(
        "HDR",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
        textColor=WHITE,
        leading=11,
    )
    bin_style = ParagraphStyle(
        "BinCode",
        parent=styles["Normal"],
        fontSize=7.5,
        alignment=TA_CENTER,
        leading=11,
    )

    headers = [
        Paragraph("No.",                  hdr_style),
        Paragraph("x",                    hdr_style),
        Paragraph("y",                    hdr_style),
        Paragraph("Minutiae\ntype\nnumber",hdr_style),
        Paragraph("Angle\nin\ndegree",    hdr_style),
        Paragraph("Binary",               hdr_style),
        Paragraph("bits",                 hdr_style),
    ]
    table_data = [headers]

    for row in stats["table_rows"]:
        xml_code = _seg_xml(row["binary_code"], row["type_num"])
        table_data.append([
            Paragraph(str(row["no"]),          cell_style),
            Paragraph(str(row["x"]),           cell_style),
            Paragraph(str(row["y"]),           cell_style),
            Paragraph(str(row["type_num"]),    cell_style),
            Paragraph(str(row["angle_deg"]),   cell_style),
            Paragraph(xml_code,                bin_style),
            Paragraph(str(row["bit_count"]),   cell_style),
        ])

    # Column widths: No | x | y | type | angle | binary | bits
    col_widths = [1.0*cm, 1.4*cm, 1.4*cm, 1.8*cm, 1.6*cm, 8.2*cm, 1.2*cm]

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header row
        ("BACKGROUND",   (0,0), (-1,0),  DARK),
        ("TEXTCOLOR",    (0,0), (-1,0),  WHITE),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,0),  8),
        ("ALIGN",        (0,0), (-1,0),  "CENTER"),
        ("VALIGN",       (0,0), (-1,0),  "MIDDLE"),
        ("ROWBACKGROUND",(0,0), (-1,0),  DARK),
        # Data rows alternating background
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, GREY]),
        ("ALIGN",        (0,1), (-1,-1), "CENTER"),
        ("VALIGN",       (0,1), (-1,-1), "MIDDLE"),
        ("FONTSIZE",     (0,1), (-1,-1), 8),
        # Grid
        ("GRID",         (0,0), (-1,-1), 0.4, MID),
        ("LINEBELOW",    (0,0), (-1,0),  1.2, DARK),
        # Padding
        ("TOPPADDING",   (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ("LEFTPADDING",  (0,0), (-1,-1), 3),
        ("RIGHTPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 18))

    # ── Final Bitstream Section ───────────────────────────────────────────────
    section_hdr = ParagraphStyle(
        "SecHdr",
        parent=styles["Normal"],
        fontSize=10,
        fontName="Helvetica-Bold",
        textColor=DARK,
        spaceBefore=4,
        spaceAfter=6,
    )
    bs_style = ParagraphStyle(
        "BitstreamPara",
        parent=styles["Normal"],
        fontSize=8,
        leading=13,
        wordWrap="CJK",
        alignment=TA_JUSTIFY,
    )
    stats_style = ParagraphStyle(
        "Stats",
        parent=styles["Normal"],
        fontSize=10,
        leading=18,
        textColor=DARK,
    )

    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=8))
    story.append(Paragraph("Final Bitstream", section_hdr))

    bs_xml = _bitstream_xml(stats["bitstream"], stats["table_rows"])
    story.append(Paragraph(bs_xml, bs_style))
    story.append(Spacer(1, 14))

    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=8))
    story.append(Paragraph("Statistics", section_hdr))

    story.append(Paragraph(
        f'Total bits = <b>{stats["total_bits"]}</b>', stats_style))
    story.append(Paragraph(
        f'#0s = <b>{stats["count_0s"]}</b>', stats_style))
    story.append(Paragraph(
        f'#1s = <b>{stats["count_1s"]}</b>', stats_style))

    doc.build(story)
    print(f"[+] PDF report saved → {output_path}")
    return output_path
