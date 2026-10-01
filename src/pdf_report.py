"""Generate a per-student PDF marking report with a source badge per question."""

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# comment_source values stored in the DB, mapped to a badge label/colour.
SOURCE_BADGES = {
    "ai": {"abbr": "AI", "label": "AI generated", "color": colors.HexColor("#2563eb")},
    "ai_human_approved": {
        "abbr": "AI+H",
        "label": "AI generated, approved by human",
        "color": colors.HexColor("#7c3aed"),
    },
    "human": {"abbr": "H", "label": "Human", "color": colors.HexColor("#15803d")},
}
DEFAULT_BADGE = {"abbr": "?", "label": "Not marked", "color": colors.HexColor("#9ca3af")}


def _badge_table(source):
    info = SOURCE_BADGES.get(source, DEFAULT_BADGE)
    style = ParagraphStyle(
        "badge", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, alignment=TA_CENTER
    )
    cell = Table([[Paragraph(info["abbr"], style)]], colWidths=[13 * mm], rowHeights=[6 * mm])
    cell.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), info["color"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return cell, info["label"]


def parse_numeric_score(raw_score):
    """Extract a numeric score from free-text values like '4', '4/5', or '4 / 5'."""
    text = str(raw_score or "").strip()
    if not text:
        return None
    head = text.split("/")[0].strip()
    try:
        return float(head)
    except ValueError:
        return None


def compute_question_percentage(numeric_score, max_score):
    if numeric_score is None or not max_score:
        return None
    try:
        return round((numeric_score / float(max_score)) * 100, 1)
    except (TypeError, ZeroDivisionError):
        return None


def compute_totals(question_entries, total_max_override=None, final_mark_max=None):
    """Sum scored/max marks across questions (unmarked questions count as 0).

    total_max_override lets the marking template define the assignment total
    independently of the summed question marks (some questions may be bonus).
    final_mark_max, if given, rescales the achieved score to a mark out of
    that value (e.g. out of 2.5) alongside the raw total.
    """
    total_score = 0.0
    total_max = 0.0
    marked_count = 0
    for entry in question_entries:
        max_score = entry.get("max_score")
        numeric_score = entry.get("numeric_score")
        if max_score:
            total_max += float(max_score)

        if numeric_score is not None:
            total_score += numeric_score
            marked_count += 1

    if total_max_override:
        total_max = float(total_max_override)

    percentage = round((total_score / total_max) * 100, 1) if total_max else None
    final_mark = (
        round((total_score / total_max) * float(final_mark_max), 2)
        if total_max and final_mark_max
        else None
    )
    return {
        "total_score": total_score,
        "total_max": total_max,
        "percentage": percentage,
        "marked_count": marked_count,
        "question_count": len(question_entries),
        "final_mark": final_mark,
        "final_mark_max": float(final_mark_max) if final_mark_max else None,
    }


def build_submission_report(submission, question_entries, assignment_title, total_max_override=None, final_mark_max=None, generated_at=None):
    """Render a marking report PDF for one submission. Returns PDF bytes."""
    generated_at = generated_at or datetime.now()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=2
    )
    meta_style = ParagraphStyle("ReportMeta", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor("#374151"))
    question_heading_style = ParagraphStyle(
        "QuestionHeading", parent=styles["Heading3"], fontSize=11.5, spaceAfter=2, textColor=colors.HexColor("#111827")
    )
    body_style = ParagraphStyle("ReportBody", parent=styles["Normal"], fontSize=9.5, leading=13)
    reasoning_style = ParagraphStyle(
        "ReasoningNote", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#4b5563"), leftIndent=4
    )
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#6b7280"))

    story = []
    story.append(Paragraph(assignment_title or "Assignment Marking Report", title_style))
    story.append(Spacer(1, 4))

    meta_rows = [
        ["Student", submission.get("name", "")],
        ["Student ID", submission.get("student_id", "")],
        ["Submission code", submission.get("code", "")],
        ["Submitted at", submission.get("submitted_at", "")],
        ["Status", submission.get("status", "")],
    ]
    if submission.get("marking_excluded"):
        meta_rows.append(["Marking", "Excluded from marking pool"])
    meta_table = Table(meta_rows, colWidths=[38 * mm, 120 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#374151")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 8))

    totals = compute_totals(question_entries, total_max_override=total_max_override, final_mark_max=final_mark_max)
    summary_cells = [
        Paragraph(f"<b>Total: {totals['total_score']:g} / {totals['total_max']:g}</b>", body_style),
        Paragraph(
            f"<b>Overall: {totals['percentage']}%</b>" if totals["percentage"] is not None else "<b>Overall: n/a</b>",
            body_style,
        ),
        Paragraph(f"Marked: {totals['marked_count']} / {totals['question_count']} questions", small_style),
    ]
    if totals["final_mark"] is not None:
        summary_cells.append(
            Paragraph(f"<b>Final mark: {totals['final_mark']:g} / {totals['final_mark_max']:g}</b>", body_style)
        )
    summary_table = Table([summary_cells], colWidths=[45 * mm, 40 * mm, 45 * mm, 45 * mm][: len(summary_cells)])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Marking source legend: "
            '<font color="#2563eb"><b>AI</b></font> = AI generated, '
            '<font color="#7c3aed"><b>AI+H</b></font> = AI generated &amp; approved by human, '
            '<font color="#15803d"><b>H</b></font> = Human',
            small_style,
        )
    )
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#d1d5db")))
    story.append(Spacer(1, 8))

    for entry in question_entries:
        badge, badge_label = _badge_table(entry.get("comment_source"))
        max_score = entry.get("max_score")
        numeric_score = entry.get("numeric_score")
        raw_score = entry.get("score") or ""
        pct = entry.get("percentage")

        if raw_score:
            score_text = raw_score if not max_score else f"{raw_score} / {max_score:g}"
        else:
            score_text = "Not yet marked"
        if pct is not None:
            score_text += f"  ({pct}%)"

        header_row = Table(
            [[Paragraph(f"<b>{entry['question_id']}</b> &mdash; {score_text}", question_heading_style), badge]],
            colWidths=[142 * mm, 16 * mm],
        )
        header_row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )

        block = [header_row, Paragraph(f"<i>Marked by: {badge_label}</i>", small_style), Spacer(1, 3)]

        prompt = str(entry.get("prompt") or "").strip()
        if prompt:
            block.append(Paragraph(f"<b>Question:</b> {prompt}", body_style))
            block.append(Spacer(1, 3))

        comment = str(entry.get("comment") or "").strip()
        block.append(Paragraph(f"<b>Feedback:</b> {comment or 'No feedback provided.'}", body_style))

        ai_reasoning = str(entry.get("ai_reasoning") or "").strip()
        if ai_reasoning:
            block.append(Spacer(1, 3))
            block.append(Paragraph(f"AI reasoning: {ai_reasoning}", reasoning_style))

        block.append(Spacer(1, 6))
        block.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#e5e7eb")))
        block.append(Spacer(1, 8))

        story.append(KeepTogether(block))

    general_comment = str(submission.get("general_comment") or "").strip()
    if general_comment:
        heading_style = ParagraphStyle(
            "GeneralCommentHeading", parent=styles["Heading3"], fontSize=11.5, spaceAfter=4, textColor=colors.HexColor("#111827")
        )
        story.append(Spacer(1, 4))
        story.append(Paragraph("General comment", heading_style))
        story.append(Paragraph(general_comment, body_style))
        story.append(Spacer(1, 8))

    story.append(Spacer(1, 6))
    story.append(
        Paragraph(f"Generated on {generated_at.strftime('%Y-%m-%d %H:%M')}", small_style)
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=f"Marking report - {submission.get('name', '')}",
    )
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
