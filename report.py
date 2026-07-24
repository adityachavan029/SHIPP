import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
import encoding as enc

RED   = colors.HexColor("#C0392B")
BLUE  = colors.HexColor("#1A5276")
GREEN = colors.HexColor("#1E8449")
DARK  = colors.HexColor("#1C2833")
GREY  = colors.HexColor("#F2F3F4")
MID   = colors.HexColor("#D5D8DC")
WHITE = colors.white
BLACK = colors.black
CELL_RED  = colors.HexColor("#FADBD8")
CELL_BLUE = colors.HexColor("#D6EAF8")

PAGE_W, PAGE_H = A4
USABLE_W = PAGE_W - 3.6 * cm


def _seg_xml(code, type_id):
    segs = code.split("-")
    pal  = [BLUE, GREEN, RED, DARK]
    parts = []
    for i, seg in enumerate(segs):
        col = pal[i % len(pal)].hexval() if i < len(pal) else DARK.hexval()
        parts.append(f'<font color="{col}">{seg}</font>')
    return "-".join(parts)


def _bitstream_xml(bs, table_rows):
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


def _load_image(path, max_w, max_h):
    if not os.path.exists(path):
        return None
    img = Image(path)
    iw, ih = img.imageWidth, img.imageHeight
    scale  = min(max_w / iw, max_h / ih)
    img.drawWidth  = iw * scale
    img.drawHeight = ih * scale
    return img


def _pipeline_grid(image_path, styles):
    """
    Returns a Table that lays out 4 pipeline images in a 2×2 grid
    with directional arrows, matching the reference screenshot.
    """
    IMG_W = USABLE_W / 2 - 1.2 * cm
    IMG_H = 5.5 * cm

    orig   = _load_image(image_path,                           IMG_W, IMG_H)
    binary = _load_image("output_images/step1_binary.png",     IMG_W, IMG_H)
    skel   = _load_image("output_images/step2_skeleton.png",   IMG_W, IMG_H)
    annot  = _load_image("output_images/annotated_skeleton.png", IMG_W, IMG_H)

    cap = ParagraphStyle("cap", parent=styles["Normal"],
                         fontSize=8, alignment=TA_CENTER,
                         textColor=colors.HexColor("#555555"), spaceBefore=3)
    arr = ParagraphStyle("arr", parent=styles["Normal"],
                         fontSize=22, alignment=TA_CENTER,
                         textColor=BLUE, leading=IMG_H + 22)

    # Row 1 : Original  →  Binary
    # Row 2 : Minutiae  ←  Thinned
    row1 = [
        [orig   or Paragraph("(original)",      cap), Paragraph("⇒", arr), binary or Paragraph("(binary)", cap)],
        [Paragraph("Original Image",             cap), Paragraph("",  arr), Paragraph("Binary Image",              cap)],
    ]
    row2 = [
        [annot  or Paragraph("(annotated)",      cap), Paragraph("⇐", arr), skel   or Paragraph("(skeleton)", cap)],
        [Paragraph("Minutiae Points",            cap), Paragraph("",  arr), Paragraph("Thinned Image",             cap)],
    ]

    def _make(rows):
        t = Table(rows, colWidths=[IMG_W, 1.2*cm, IMG_W])
        t.setStyle(TableStyle([
            ("ALIGN",       (0,0), (-1,-1), "CENTER"),
            ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",  (0,0), (-1,-1), 2),
            ("BOTTOMPADDING",(0,0),(-1,-1), 2),
        ]))
        return t

    outer = Table([[_make(row1)], [Spacer(1, 10)], [_make(row2)]])
    outer.setStyle(TableStyle([
        ("ALIGN",  (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    return outer


def _overview_table(rows, styles):
    """
    Produces the overview table:
    No. | x | y | Type# | Type Name | Type Color | Angle (rad) | Angle (deg)
    """
    hdr = ParagraphStyle("HDR2", parent=styles["Normal"],
                         fontSize=8, fontName="Helvetica-Bold",
                         alignment=TA_CENTER, textColor=WHITE, leading=11)
    cel = ParagraphStyle("CEL2", parent=styles["Normal"],
                         fontSize=8, alignment=TA_CENTER, leading=11)
    col = ParagraphStyle("COL2", parent=styles["Normal"],
                         fontSize=8, alignment=TA_CENTER, leading=11,
                         fontName="Helvetica-Bold")

    header_row = [
        Paragraph("No.",               hdr),
        Paragraph("x",                 hdr),
        Paragraph("y",                 hdr),
        Paragraph("Minutiae\ntype\nnumber", hdr),
        Paragraph("Minutiae\ntype name",   hdr),
        Paragraph("Minutiae\ntype color",  hdr),
        Paragraph("Angle in\nradian",  hdr),
        Paragraph("Angle in\ndegree",  hdr),
    ]
    data = [header_row]

    for row in rows:
        is_ending = row["type_num"] == 1
        color_name = "Red"   if is_ending else "Blue"
        color_obj  = RED     if is_ending else BLUE
        data.append([
            Paragraph(str(row["no"]),                        cel),
            Paragraph(str(row["x"]),                         cel),
            Paragraph(str(row["y"]),                         cel),
            Paragraph(str(row["type_num"]),                  cel),
            Paragraph(row["type_name"],                      cel),
            Paragraph(f'<font color="{color_obj.hexval()}"><b>{color_name}</b></font>', col),
            Paragraph(f'{row["angle_rad"]:.6f}',             cel),
            Paragraph(str(row["angle_deg"]),                 cel),
        ])

    col_w = [1.0*cm, 1.2*cm, 1.2*cm, 1.8*cm, 2.4*cm, 2.2*cm, 2.6*cm, 2.0*cm]
    tbl = Table(data, colWidths=col_w, repeatRows=1)

    row_bg = []
    for i, row in enumerate(rows):
        bg = CELL_RED if row["type_num"] == 1 else CELL_BLUE
        row_bg.append(("BACKGROUND", (0, i+1), (-1, i+1), bg))

    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("GRID",          (0,0), (-1,-1), 0.4, MID),
        ("LINEBELOW",     (0,0), (-1,0),  1.2, DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 3),
        ("RIGHTPADDING",  (0,0), (-1,-1), 3),
        *row_bg,
    ]))
    return tbl


def _encoding_table(rows, styles):
    """Original binary encoding table."""
    hdr = ParagraphStyle("HDR3", parent=styles["Normal"],
                         fontSize=8, fontName="Helvetica-Bold",
                         alignment=TA_CENTER, textColor=WHITE, leading=11)
    cel = ParagraphStyle("CEL3", parent=styles["Normal"],
                         fontSize=8, alignment=TA_CENTER, leading=11)
    bin_s = ParagraphStyle("BIN3", parent=styles["Normal"],
                           fontSize=7.5, alignment=TA_CENTER, leading=11)

    header_row = [
        Paragraph("No.",          hdr),
        Paragraph("x",            hdr),
        Paragraph("y",            hdr),
        Paragraph("Type\nnumber", hdr),
        Paragraph("Angle\n(deg)", hdr),
        Paragraph("Binary Code",  hdr),
        Paragraph("bits",         hdr),
    ]
    data = [header_row]
    for row in rows:
        data.append([
            Paragraph(str(row["no"]),                        cel),
            Paragraph(str(row["x"]),                         cel),
            Paragraph(str(row["y"]),                         cel),
            Paragraph(str(row["type_num"]),                  cel),
            Paragraph(str(row["angle_deg"]),                 cel),
            Paragraph(_seg_xml(row["binary_code"], row["type_num"]), bin_s),
            Paragraph(str(row["bit_count"]),                 cel),
        ])

    col_w = [1.0*cm, 1.4*cm, 1.4*cm, 1.8*cm, 1.6*cm, 8.2*cm, 1.2*cm]
    tbl = Table(data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, GREY]),
        ("GRID",          (0,0), (-1,-1), 0.4, MID),
        ("LINEBELOW",     (0,0), (-1,0),  1.2, DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 3),
        ("RIGHTPADDING",  (0,0), (-1,-1), 3),
    ]))
    return tbl


def generate_pdf(stats, image_path,
                 output_path="output_images/fingerprint_report.pdf"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=2*cm,    bottomMargin=2*cm,
    )
    styles  = getSampleStyleSheet()
    story   = []
    rows    = stats["table_rows"]
    bs      = stats["bitstream"]

    title_s = ParagraphStyle("T", parent=styles["Heading1"],
                              fontSize=16, textColor=DARK, spaceAfter=4,
                              alignment=TA_CENTER, fontName="Helvetica-Bold")
    sub_s   = ParagraphStyle("S", parent=styles["Normal"],
                              fontSize=9, textColor=colors.HexColor("#717D7E"),
                              alignment=TA_CENTER, spaceAfter=12)
    sec_s   = ParagraphStyle("SEC", parent=styles["Normal"],
                              fontSize=10, fontName="Helvetica-Bold",
                              textColor=DARK, spaceBefore=4, spaceAfter=6)
    bs_s    = ParagraphStyle("BS", parent=styles["Normal"],
                              fontSize=8, leading=13, wordWrap="CJK",
                              alignment=TA_JUSTIFY)
    stat_s  = ParagraphStyle("ST", parent=styles["Normal"],
                              fontSize=10, leading=18, textColor=DARK)

    # ── Title ────────────────────────────────────────────────────────
    story.append(Paragraph("Fingerprint Minutiae Extraction Report", title_s))
    story.append(Paragraph(
        f"Input image: <b>{image_path}</b> &nbsp;|&nbsp; "
        f"Total minutiae: <b>{len(rows)}</b>",
        sub_s))
    story.append(HRFlowable(width="100%", thickness=1, color=MID, spaceAfter=10))

    # ── Section 1: Pipeline Image Grid ───────────────────────────────
    story.append(Paragraph("Pipeline Stages", sec_s))
    story.append(_pipeline_grid(image_path, styles))
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=10))

    # ── Section 2: Minutiae Overview Table ───────────────────────────
    story.append(Paragraph("Minutiae Overview", sec_s))
    story.append(_overview_table(rows, styles))
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=10))

    # ── Section 3: Binary Encoding Table ─────────────────────────────
    story.append(Paragraph("Binary Encoding Table", sec_s))
    story.append(_encoding_table(rows, styles))
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=10))

    # ── Section 4: Final Bitstream ────────────────────────────────────
    story.append(Paragraph("Final Bitstream", sec_s))
    story.append(Paragraph(_bitstream_xml(bs, rows), bs_s))
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MID, spaceAfter=8))

    # ── Section 5: Statistics ─────────────────────────────────────────
    story.append(Paragraph("Statistics", sec_s))
    story.append(Paragraph(f'Total bits = <b>{stats["total_bits"]}</b>', stat_s))
    story.append(Paragraph(f'#0s = <b>{stats["count_0s"]}</b>',         stat_s))
    story.append(Paragraph(f'#1s = <b>{stats["count_1s"]}</b>',         stat_s))

    doc.build(story)
    print(f"[+] PDF report saved → {output_path}")
    return output_path
