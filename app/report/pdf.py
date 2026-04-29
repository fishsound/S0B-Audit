"""
ReportLab PDF report builder.

Generates a fully text-searchable PDF (Ctrl+F works in any viewer).
Dark sci-fi theme matching the web UI palette.

Corp report structure:
  Page 1 — Cover + Summary stats
  Page 2+ — Full roster table (landscape, dynamic month columns)

Alliance report structure:
  Page 1 — Cover + Alliance summary table (all corps)
  Subsequent pages — one compact summary per corp
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from app.config import MONTH_ABBRS
from app.models import Character, Corp

# ─── Palette ──────────────────────────────────────────────────────────────────
C_BG_DARK   = HexColor("#0D1117")
C_BG_MID    = HexColor("#161B22")
C_BG_LIGHT  = HexColor("#1F2937")
C_CYAN      = HexColor("#00BFFF")
C_TEAL      = HexColor("#00E5CC")
C_GOLD      = HexColor("#FFD700")
C_RED       = HexColor("#C0392B")
C_GREEN     = HexColor("#27AE60")
C_GREY      = HexColor("#8B949E")
C_WHITE     = HexColor("#FFFFFF")
C_HEADER_BG = HexColor("#0A3D62")
C_ORANGE    = HexColor("#F39C12")

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 10 * mm
USABLE_W = PAGE_W - 2 * MARGIN


# ─── Styles ───────────────────────────────────────────────────────────────────
def _ps(name, **kw) -> ParagraphStyle:
    defaults = dict(fontName="Helvetica", textColor=C_WHITE, backColor=C_BG_DARK)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


STYLE_TITLE    = _ps("Title",    fontSize=20, leading=26, alignment=TA_CENTER,
                      textColor=C_CYAN, spaceAfter=4)
STYLE_SUBTITLE = _ps("Subtitle", fontSize=9,  leading=12, alignment=TA_CENTER,
                      textColor=C_GREY, spaceAfter=10)
STYLE_SECTION  = _ps("Section",  fontSize=11, leading=14, alignment=TA_CENTER,
                      textColor=C_GOLD, backColor=C_HEADER_BG, spaceAfter=4)
STYLE_BODY     = _ps("Body",     fontSize=8,  leading=11, textColor=C_WHITE)
STYLE_SMALL    = _ps("Small",    fontSize=7,  leading=9,  textColor=C_GREY,
                      alignment=TA_CENTER)


# ─── Page template with dark background ───────────────────────────────────────
def _dark_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_BG_DARK)
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
    canvas.restoreState()


def _make_doc(path: Path, title: str) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=title,
        author="SONS of BANE Audit Tool",
        subject="Alliance Compliance Audit",
        creator="SoB-Audit-Tool/2.0",
    )
    frame = Frame(MARGIN, MARGIN, USABLE_W, PAGE_H - 2 * MARGIN, id="main")
    doc.addPageTemplates([PageTemplate(id="dark", frames=[frame],
                                       onPage=_dark_bg)])
    return doc


# ─── Table helpers ─────────────────────────────────────────────────────────────
def _hdr_cell(text: str, color=C_CYAN) -> Paragraph:
    s = ParagraphStyle("hc", fontName="Helvetica-Bold", fontSize=7,
                       textColor=color, backColor=C_HEADER_BG,
                       alignment=TA_CENTER, leading=9)
    return Paragraph(text, s)


def _cell(text: str, color=C_WHITE, align=TA_LEFT, bold=False) -> Paragraph:
    fn = "Helvetica-Bold" if bold else "Helvetica"
    s = ParagraphStyle("dc", fontName=fn, fontSize=7, textColor=color,
                       alignment=align, leading=9, backColor=None)
    return Paragraph(str(text), s)


def _tier_info(total_fats: int) -> tuple[str, HexColor]:
    if total_fats >= 8:
        return "★ ELITE", C_TEAL
    if total_fats >= 4:
        return "◆ ACTIVE", C_GREEN
    if total_fats >= 1:
        return "▷ PARTIAL", C_GOLD
    return "○ GHOST", C_RED


def _fat_color(n: int) -> HexColor:
    if n >= 8:
        return C_TEAL
    if n >= 4:
        return C_GREEN
    if n >= 1:
        return C_GOLD
    return C_RED


def _row_bg(i: int) -> HexColor:
    return C_BG_MID if i % 2 == 0 else C_BG_LIGHT


def _base_table_style(n_rows: int, n_cols: int) -> list:
    return [
        ("BACKGROUND",  (0, 0), (-1, 0), C_HEADER_BG),
        ("TEXTCOLOR",   (0, 0), (-1, 0), C_CYAN),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 7),
        ("LEADING",     (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_BG_MID, C_BG_LIGHT]),
        ("GRID",        (0, 0), (-1, -1), 0.3, HexColor("#2D3748")),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]


# ─── Active months helper ─────────────────────────────────────────────────────
def _year_months(year: int) -> list[str]:
    """Return month abbreviations for the given year (up to today if current year)."""
    today = date.today()
    limit = today.month if year == today.year else 12
    return MONTH_ABBRS[:limit]


# ─── Corp roster table ────────────────────────────────────────────────────────
def _roster_table(members: list[Character], year: int) -> Table:
    months = _year_months(year)

    # Column widths (mm) — fixed base + dynamic monthly cols
    fixed_w = [5, 35, 20, 25, 12, 25, 10, 12, 15]   # #,name,joined,alliance,sp,login,sec,total,rating
    mo_w    = [max(6, int((USABLE_W/mm - sum(fixed_w)) / len(months))) for _ in months]
    col_w   = [w * mm for w in fixed_w[:8]] + [w * mm for w in mo_w] + [fixed_w[-1] * mm]

    hdr = (
        [_hdr_cell("#"), _hdr_cell("PILOT NAME"), _hdr_cell("CORP\nJOINED"),
         _hdr_cell("IN ALLIANCE"), _hdr_cell("SP\n(M)"), _hdr_cell("LAST\nLOGIN"),
         _hdr_cell("SEC"), _hdr_cell("FATs")]
        + [_hdr_cell(f"{mo}\n'{str(year)[-2:]}") for mo in months]
        + [_hdr_cell("RATING")]
    )

    rows = [hdr]
    for i, m in enumerate(members):
        tier, tier_color = _tier_info(m.total_fats)
        fat_c = _fat_color(m.total_fats)
        sp_c = C_TEAL if m.skillpoints_m >= 80 else (C_GOLD if m.skillpoints_m >= 30 else C_WHITE)
        sec_c = C_RED if m.sec_status < 0 else (C_GOLD if m.sec_status < 2 else C_GREEN)

        sp_str = f"{m.skillpoints_m:.1f}" if m.skillpoints_m else "—"
        monthly = [
            _cell(str(m.fats_by_month.get(f"{year}-{mo}", 0) or "—"),
                  color=C_GREY if not m.fats_by_month.get(f"{year}-{mo}") else C_TEAL,
                  align=TA_CENTER)
            for mo in months
        ]

        row = (
            [_cell(str(i + 1), color=C_GREY, align=TA_CENTER),
             _cell(m.name, bold=True),
             _cell(m.join_date or "—", color=C_GREY, align=TA_CENTER),
             _cell(m.time_in_corp or m.born or "—", color=C_GREY, align=TA_CENTER),
             _cell(sp_str, color=sp_c, align=TA_CENTER),
             _cell(m.last_login or "—", color=C_GREY, align=TA_CENTER),
             _cell(f"{m.sec_status:.1f}", color=sec_c, align=TA_CENTER),
             _cell(str(m.total_fats), color=fat_c, bold=True, align=TA_CENTER)]
            + monthly
            + [_cell(tier, color=tier_color, bold=True, align=TA_CENTER)]
        )
        rows.append(row)

    style = TableStyle(_base_table_style(len(rows), len(col_w)))
    return Table(rows, colWidths=col_w, repeatRows=1, style=style)


# ─── Summary stats table ──────────────────────────────────────────────────────
def _summary_table(members: list[Character], year: int) -> Table:
    n = len(members)
    any_fats = sum(1 for m in members if m.total_fats > 0)
    ghosts   = n - any_fats
    total    = sum(m.total_fats for m in members)
    ytd      = sum(m.fats_by_year.get(year, 0) for m in members)
    prev_yr  = sum(m.fats_by_year.get(year - 1, 0) for m in members)
    elite    = sum(1 for m in members if m.total_fats >= 8)
    active   = sum(1 for m in members if 4 <= m.total_fats < 8)
    partial  = sum(1 for m in members if 1 <= m.total_fats < 4)
    pct      = f"{any_fats / n * 100:.0f}%" if n else "—"

    def row(label, value, vc=C_WHITE):
        return [_cell(label, color=C_GREY), _cell(str(value), color=vc, bold=True)]

    data = [
        [_hdr_cell("METRIC"), _hdr_cell("VALUE")],
        row("Total Mains",              n,        C_TEAL),
        row("FAT Participation Rate",   pct,      C_GOLD),
        row("Members with ANY FATs",    any_fats, C_GREEN),
        row("Ghost Members (0 FATs)",   ghosts,   C_RED),
        row("★ Elite (8+ FATs)",        elite,    C_TEAL),
        row("◆ Active (4–7 FATs)",      active,   C_GREEN),
        row("▷ Partial (1–3 FATs)",     partial,  C_GOLD),
        row("Total FATs (3-yr window)", total,    C_TEAL),
        row(f"FATs {year - 1}",         prev_yr,  C_WHITE),
        row(f"FATs {year} YTD",         ytd,      C_TEAL),
        row("Audit Date",               str(date.today()), C_GREY),
    ]
    col_w = [60 * mm, 35 * mm]
    return Table(data, colWidths=col_w, style=TableStyle(_base_table_style(len(data), 2)))


# ─── Top performers table ─────────────────────────────────────────────────────
def _top_table(members: list[Character], n: int = 10) -> Table:
    data = [[_hdr_cell("PILOT"), _hdr_cell("FATs"), _hdr_cell("RATING")]]
    for m in members[:n]:
        tier, tc = _tier_info(m.total_fats)
        data.append([
            _cell(m.name, bold=True),
            _cell(str(m.total_fats), color=_fat_color(m.total_fats), bold=True, align=TA_CENTER),
            _cell(tier, color=tc, align=TA_CENTER),
        ])
    col_w = [50 * mm, 20 * mm, 25 * mm]
    return Table(data, colWidths=col_w, style=TableStyle(_base_table_style(len(data), 3)))


def _ghost_table(members: list[Character]) -> Table:
    ghosts = [m for m in members if m.total_fats == 0][:15]
    data = [[_hdr_cell("PILOT"), _hdr_cell("LAST LOGIN")]]
    for m in ghosts:
        data.append([_cell(m.name, color=C_GREY), _cell(m.last_login or "—", color=C_RED)])
    col_w = [50 * mm, 35 * mm]
    return Table(data, colWidths=col_w, style=TableStyle(_base_table_style(len(data), 2)))


# ─── Corp report ──────────────────────────────────────────────────────────────
def build_corp_pdf(
    corp_name: str,
    members: list[Character],
    year: int,
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(members, key=lambda c: -c.total_fats)

    doc = _make_doc(out_path, f"{corp_name} — SoB Audit Report")
    story: list = []

    # Cover / summary page
    story.append(Paragraph(f"◈  {corp_name.upper()}  ·  CORP AUDIT REPORT  ◈", STYLE_TITLE))
    story.append(Paragraph(
        f"Sons of Bane Alliance  ·  EVE Online  ·  "
        f"Audit Date: {date.today()}  ·  {len(members)} Mains  ·  Year: {year}",
        STYLE_SUBTITLE,
    ))
    story.append(Spacer(1, 4 * mm))

    # Two-column layout: summary stats | top performers + ghosts
    summary  = _summary_table(members, year)
    top      = _top_table(members)
    ghost    = _ghost_table(members)

    side_data = [[
        [Paragraph("CORP STATISTICS", STYLE_SECTION), Spacer(1, 2*mm), summary],
        [Paragraph("🏆 TOP PERFORMERS", STYLE_SECTION), Spacer(1, 2*mm), top,
         Spacer(1, 4*mm),
         Paragraph("⚠ GHOST MEMBERS (0 FATs)", STYLE_SECTION), Spacer(1, 2*mm), ghost],
    ]]
    side_tbl = Table(side_data, colWidths=[USABLE_W * 0.42, USABLE_W * 0.55])
    side_tbl.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("TOPPADDING",  (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0),(-1, -1), 0),
        ("BACKGROUND",  (0, 0), (-1, -1), C_BG_DARK),
    ]))
    story.append(side_tbl)

    # Roster page
    story.append(PageBreak())
    story.append(Paragraph(f"◈  {corp_name.upper()}  ·  FULL ROSTER  ◈", STYLE_TITLE))
    story.append(Paragraph(
        f"Fleet Activity Tracking — {year} (showing {len(_year_months(year))} months)  ·  "
        "★ ELITE 8+  ◆ ACTIVE 4–7  ▷ PARTIAL 1–3  ○ GHOST 0",
        STYLE_SUBTITLE,
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(_roster_table(members, year))

    # Legend
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "IN ALLIANCE = time since character joined corp OR corp joined SoB (whichever is more recent)  ·  "
        "Data sources: Alliance Auth (Member Audit + AFAT) + ESI",
        STYLE_SMALL,
    ))

    doc.build(story)
    return out_path


# ─── Alliance report ──────────────────────────────────────────────────────────
def _alliance_summary_table(corps: list[Corp], year: int) -> Table:
    data = [[
        _hdr_cell("#", C_GOLD), _hdr_cell("CORPORATION", C_GOLD),
        _hdr_cell("MAINS", C_GOLD), _hdr_cell("TOTAL\nFATs", C_GOLD),
        _hdr_cell(f"{year}\nFATs", C_GOLD), _hdr_cell("★\nELITE", C_GOLD),
        _hdr_cell("◆\nACTIVE", C_GOLD), _hdr_cell("▷\nPARTIAL", C_GOLD),
        _hdr_cell("○\nGHOST", C_GOLD),
    ]]
    sorted_corps = sorted(corps, key=lambda c: -sum(m.total_fats for m in c.members))
    for i, corp in enumerate(sorted_corps):
        ms = corp.members
        total = sum(m.total_fats for m in ms)
        ytd   = sum(m.fats_by_year.get(year, 0) for m in ms)
        elite   = sum(1 for m in ms if m.total_fats >= 8)
        active  = sum(1 for m in ms if 4 <= m.total_fats < 8)
        partial = sum(1 for m in ms if 1 <= m.total_fats < 4)
        ghost   = sum(1 for m in ms if m.total_fats == 0)
        fat_c = C_TEAL if total >= 50 else (C_GREEN if total >= 20 else C_WHITE)
        data.append([
            _cell(str(i + 1), color=C_GREY, align=TA_CENTER),
            _cell(corp.name, bold=True),
            _cell(str(len(ms)), align=TA_CENTER),
            _cell(str(total), color=fat_c, bold=True, align=TA_CENTER),
            _cell(str(ytd),   color=C_TEAL if ytd > 0 else C_GREY, align=TA_CENTER),
            _cell(str(elite),   color=C_TEAL  if elite   else C_GREY, align=TA_CENTER),
            _cell(str(active),  color=C_GREEN  if active  else C_GREY, align=TA_CENTER),
            _cell(str(partial), color=C_GOLD   if partial else C_GREY, align=TA_CENTER),
            _cell(str(ghost),   color=C_RED    if ghost   else C_GREY, align=TA_CENTER),
        ])
    col_w = [8*mm, 55*mm, 14*mm, 16*mm, 14*mm, 14*mm, 14*mm, 14*mm, 14*mm]
    return Table(data, colWidths=col_w, style=TableStyle(_base_table_style(len(data), 9)))


def build_alliance_pdf(corps: list[Corp], year: int, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_members = [m for corp in corps for m in corp.members]

    doc = _make_doc(out_path, "SONS of BANE — Alliance Audit Report")
    story: list = []

    # Alliance cover
    story.append(Paragraph("◈  SONS OF BANE  ·  ALLIANCE AUDIT REPORT  ◈", STYLE_TITLE))
    story.append(Paragraph(
        f"EVE Online  ·  Audit Date: {date.today()}  ·  "
        f"{len(corps)} Corps  ·  {len(all_members)} Mains  ·  Year: {year}",
        STYLE_SUBTITLE,
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("ALLIANCE STANDINGS — CORPS BY FLEET ACTIVITY", STYLE_SECTION))
    story.append(Spacer(1, 2 * mm))
    story.append(_alliance_summary_table(corps, year))

    # Per-corp pages
    sorted_corps = sorted(corps, key=lambda c: -sum(m.total_fats for m in c.members))
    for corp in sorted_corps:
        if not corp.members:
            continue
        ms = sorted(corp.members, key=lambda c: -c.total_fats)
        story.append(PageBreak())
        story.append(Paragraph(f"◈  {corp.name.upper()}  ◈", STYLE_TITLE))
        story.append(Paragraph(
            f"{len(ms)} Mains  ·  "
            f"Total FATs: {sum(m.total_fats for m in ms)}  ·  "
            f"{year} YTD: {sum(m.fats_by_year.get(year, 0) for m in ms)}",
            STYLE_SUBTITLE,
        ))
        story.append(Spacer(1, 3 * mm))
        story.append(_roster_table(ms, year))

    doc.build(story)
    return out_path
