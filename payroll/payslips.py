"""Finalized payroll statement data and PDF payslip rendering.

This module is intentionally a presentation layer.  It reads the immutable
statement snapshot and persisted payroll lines, validates their reconciliation,
and renders them without recalculating payroll.
"""

from collections import OrderedDict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from io import BytesIO

from django.utils.text import slugify

from .models import PayrollLine, PayrollRun


MONEY_ZERO = Decimal("0.00")
MONEY_QUANTUM = Decimal("0.01")


class PayslipError(ValueError):
    """Raised when a finalized statement cannot safely produce a payslip."""


def _money(value):
    try:
        return Decimal(str(value if value is not None else "0")).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PayslipError("A finalized payslip contains an invalid monetary amount.") from error


def _safe_text(value, fallback=""):
    return " ".join(str(value or fallback).split())


def _money_label(amount):
    return f"PHP {_money(amount):,.2f}"


def _rate(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PayslipError("A finalized payslip contains an invalid approved pay rate.") from error


def _rate_label(amount):
    return f"PHP {_rate(amount):,.4f}"


def _pay_basis_label(value):
    labels = {
        "HOURLY": "Hourly",
        "DAILY": "Daily",
        "MONTHLY": "Monthly",
        "MIXED": "Mixed",
    }
    normalized = _safe_text(value).upper()
    return labels.get(normalized, _safe_text(value, "Not recorded"))


def _classification_label(employee_snapshot):
    labels = {
        "REGULAR": "Regular",
        "PROBATION": "Probation",
        "PART_TIME": "Part-time",
        "OTHER": "Other",
    }
    status = _safe_text(employee_snapshot.get("employment_status")).upper()
    return _safe_text(
        employee_snapshot.get("employment_status_label"),
        labels.get(status, "Not recorded in finalized snapshot"),
    )


def _snapshot_compensation_rates(snapshot):
    """Return approved rate labels without deriving earnings from the rate."""
    sources = snapshot.get("compensation_versions") or snapshot.get("rate_versions") or {}
    if not isinstance(sources, dict):
        return []

    rates = OrderedDict()
    for source in sources.values():
        if not isinstance(source, dict):
            continue
        amount = source.get("amount") or source.get("hourly_rate")
        basis = _pay_basis_label(source.get("basis"))
        if amount in (None, ""):
            continue
        try:
            key = (basis, _rate(amount))
        except PayslipError:
            continue
        rates[key] = f"{_rate_label(key[1])} / {basis.lower()}"
    return list(rates.values())


def _snapshot_pay_basis(snapshot):
    direct_basis = _safe_text(snapshot.get("pay_basis"))
    if direct_basis:
        return _pay_basis_label(direct_basis)
    sources = snapshot.get("compensation_versions") or snapshot.get("rate_versions") or {}
    if isinstance(sources, dict):
        for source in sources.values():
            if isinstance(source, dict) and _safe_text(source.get("basis")):
                return _pay_basis_label(source["basis"])
    return "Not recorded"


def _line_matches(line, *terms):
    candidate = f"{line.code} {line.label}".lower().replace("-", " ")
    return any(term in candidate for term in terms)


def _sum_lines(lines):
    return sum((_money(line.amount) for line in lines), MONEY_ZERO)


def _group_rows(lines, definitions):
    """Group confirmed lines while preserving unclassified labels verbatim."""
    grouped = OrderedDict((label, []) for label, _matcher in definitions)
    other = []
    for line in lines:
        for label, matcher in definitions:
            if matcher(line):
                grouped[label].append(line)
                break
        else:
            other.append(line)

    rows = []
    for label, matched in grouped.items():
        if matched:
            rows.append({"label": label, "amount": _sum_lines(matched)})
    rows.extend({"label": _safe_text(line.label, "Other item"), "amount": _money(line.amount)} for line in other)
    return rows


def _earnings_rows(lines):
    return _group_rows(
        lines,
        (
            ("Basic pay", lambda line: line.code == "REGULAR_PAY"),
            ("Holiday pay", lambda line: line.code == "DAY_PREMIUM"),
            ("Overtime pay", lambda line: line.code == "OVERTIME_PREMIUM"),
            ("Night differential", lambda line: line.code == "NIGHT_DIFFERENTIAL"),
            (
                "Allowance / COLA",
                lambda line: line.source == "CALCULATED_COMPONENT"
                or _line_matches(line, "allowance", "cola"),
            ),
        ),
    )


def _deduction_rows(lines):
    return _group_rows(
        lines,
        (
            ("SSS", lambda line: _line_matches(line, "sss") and not _line_matches(line, "loan")),
            ("PhilHealth", lambda line: _line_matches(line, "philhealth", "phil health")),
            ("Pag-IBIG", lambda line: _line_matches(line, "pag ibig", "pagibig") and not _line_matches(line, "loan")),
            ("BIR withholding tax", lambda line: _line_matches(line, "withholding", "bir tax")),
            ("Cash advance", lambda line: _line_matches(line, "cash advance", "advance repayment")),
            ("Charges", lambda line: _line_matches(line, "charge")),
            ("SSS loan", lambda line: _line_matches(line, "sss loan")),
            ("Pag-IBIG loan", lambda line: _line_matches(line, "pag ibig loan", "pagibig loan")),
            ("Company loan", lambda line: _line_matches(line, "company loan")),
            ("Adjustment", lambda line: _line_matches(line, "adjustment")),
        ),
    )


def _work_adjustment_note(snapshot):
    period_inputs = snapshot.get("period_inputs") or []
    if not isinstance(period_inputs, list):
        return ""
    absence_units = Decimal("0")
    undertime_minutes = 0
    for row in period_inputs:
        if not isinstance(row, dict):
            continue
        try:
            absence_units += Decimal(str(row.get("absence_units") or "0"))
            undertime_minutes += int(row.get("undertime_minutes") or 0)
        except (InvalidOperation, TypeError, ValueError):
            continue
    notes = []
    if absence_units > 0:
        notes.append("approved absence quantities")
    if undertime_minutes > 0:
        notes.append("approved undertime")
    if not notes:
        return ""
    return (
        f"{', '.join(notes).capitalize()} are already reflected in the approved basic-pay "
        "calculation and are not deducted again."
    )


def build_finalized_payslip_data(statement):
    """Build display-only data for one finalized payroll statement."""
    if statement.run.status != PayrollRun.Status.FINALIZED:
        raise PayslipError("A PDF payslip is available only after payroll is finalized.")

    statement_lines = list(statement.lines.all())
    earnings = [line for line in statement_lines if line.kind == PayrollLine.Kind.EARNING]
    deductions = [line for line in statement_lines if line.kind == PayrollLine.Kind.DEDUCTION]
    employer_contributions = [
        line for line in statement_lines if line.kind == PayrollLine.Kind.EMPLOYER_CONTRIBUTION
    ]

    gross = _money(statement.gross_amount)
    deduction_total = _money(statement.deduction_amount)
    net = _money(statement.net_amount)
    employer_total = _money(statement.employer_contribution_amount)
    if gross - deduction_total != net:
        raise PayslipError("The finalized gross pay, deductions, and net pay do not reconcile.")
    if _sum_lines(earnings) != gross:
        raise PayslipError("The finalized earnings lines do not reconcile to gross pay.")
    if _sum_lines(deductions) != deduction_total:
        raise PayslipError("The finalized deduction lines do not reconcile to total deductions.")
    if _sum_lines(employer_contributions) != employer_total:
        raise PayslipError("The finalized employer contribution lines do not reconcile.")

    snapshot = statement.snapshot or {}
    employee_snapshot = snapshot.get("employee") or {}
    employee_code = _safe_text(employee_snapshot.get("code"), "EMPLOYEE")
    employee_name = _safe_text(employee_snapshot.get("name"), "Employee name not recorded")
    rates = _snapshot_compensation_rates(snapshot)

    compensation_rows = _earnings_rows(earnings)
    allowance_total = sum(
        (row["amount"] for row in compensation_rows if row["label"] == "Allowance / COLA"),
        MONEY_ZERO,
    )
    compensation_subtotal = gross - allowance_total

    return {
        "organization_name": _safe_text(statement.run.organization.name, "Organization"),
        "run_reference": _safe_text(statement.run.reference, "Payroll run"),
        "currency": _safe_text(statement.run.currency, "PHP"),
        "period_start": statement.run.period_start,
        "period_end": statement.run.period_end,
        "pay_date": statement.run.pay_date,
        "employee": {
            "name": employee_name,
            "code": employee_code,
            "classification": _classification_label(employee_snapshot),
            "pay_basis": _snapshot_pay_basis(snapshot),
            "rates": rates,
        },
        "compensation_rows": compensation_rows,
        "deduction_rows": _deduction_rows(deductions),
        "employer_contribution_rows": _group_rows(
            employer_contributions,
            (
                ("SSS employer contribution", lambda line: _line_matches(line, "sss") and not _line_matches(line, "loan")),
                ("PhilHealth employer contribution", lambda line: _line_matches(line, "philhealth", "phil health")),
                ("Pag-IBIG employer contribution", lambda line: _line_matches(line, "pag ibig", "pagibig")),
            ),
        ),
        "compensation_subtotal": compensation_subtotal,
        "allowance_total": allowance_total,
        "gross": gross,
        "deductions": deduction_total,
        "employer_contributions": employer_total,
        "net": net,
        "work_adjustment_note": _work_adjustment_note(snapshot),
    }


def payslip_filename(data):
    employee_code = slugify(data["employee"]["code"]).upper() or "EMPLOYEE"
    return f"Shiftly_Payslip_{employee_code}_{data['period_end']:%Y-%m}.pdf"


def build_payslip_pdf(data):
    """Return an A4, selectable-text PDF for validated finalized payslip data."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as error:
        raise PayslipError("PDF generation is unavailable because the document renderer is not installed.") from error

    navy = colors.HexColor("#0F172A")
    blue = colors.HexColor("#2563EB")
    muted = colors.HexColor("#64748B")
    border = colors.HexColor("#E2E8F0")
    pale_blue = colors.HexColor("#EFF6FF")
    pale_gray = colors.HexColor("#F8FAFC")
    pale_green = colors.HexColor("#DCFCE7")

    styles = getSampleStyleSheet()
    title = ParagraphStyle("PayslipTitle", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=navy, alignment=TA_RIGHT, spaceAfter=2)
    company = ParagraphStyle("PayslipCompany", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=navy)
    eyebrow = ParagraphStyle("PayslipEyebrow", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=blue)
    body = ParagraphStyle("PayslipBody", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=navy)
    muted_body = ParagraphStyle("PayslipMuted", parent=body, textColor=muted)
    label = ParagraphStyle("PayslipLabel", parent=body, fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=muted)
    amount = ParagraphStyle("PayslipAmount", parent=body, alignment=TA_RIGHT)
    amount_bold = ParagraphStyle("PayslipAmountBold", parent=amount, fontName="Helvetica-Bold")
    section = ParagraphStyle("PayslipSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=navy, spaceBefore=2, spaceAfter=6)
    net_label = ParagraphStyle("PayslipNetLabel", parent=body, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=navy)
    net_amount = ParagraphStyle("PayslipNetAmount", parent=amount_bold, fontSize=14, leading=17, textColor=navy)

    def paragraph(value, style=body):
        return Paragraph(escape(_safe_text(value, "—")), style)

    def amount_detail_table(rows, total_label, total, width=175 * mm, section_heading=None):
        table_rows = []
        column_header_row = 0
        if section_heading:
            table_rows.append([paragraph(section_heading, section), ""])
            column_header_row = 1
        table_rows.append([
            paragraph("Item", label),
            paragraph("Amount", ParagraphStyle("table_amount_label", parent=label, alignment=TA_RIGHT)),
        ])
        for row in rows:
            table_rows.append([paragraph(row["label"]), paragraph(_money_label(row["amount"]), amount)])
        if not rows:
            table_rows.append([paragraph("No recorded items", muted_body), paragraph("—", amount)])
        table_rows.append([paragraph(total_label, ParagraphStyle("total_label", parent=body, fontName="Helvetica-Bold")), paragraph(_money_label(total), amount_bold)])
        amount_width = min(55 * mm, width * 0.38)
        table = Table(
            table_rows,
            colWidths=[width - amount_width, amount_width],
            repeatRows=column_header_row + 1,
            hAlign="LEFT",
        )
        table_style = [
            ("BACKGROUND", (0, column_header_row), (-1, column_header_row), pale_gray),
            ("LINEBELOW", (0, column_header_row), (-1, column_header_row), 0.5, border),
            ("LINEBELOW", (0, -1), (-1, -1), 0.75, blue),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        if section_heading:
            table_style.extend([
                ("SPAN", (0, 0), (-1, 0)),
                ("TOPPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("LEFTPADDING", (0, 0), (-1, 0), 0),
            ])
        table.setStyle(TableStyle(table_style))
        return table

    def amount_table(heading, rows, total_label, total):
        return [amount_detail_table(rows, total_label, total, section_heading=heading)]

    def page_footer(canvas, document):
        canvas.saveState()
        if document.page > 1:
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.setFillColor(muted)
            canvas.drawRightString(A4[0] - document.rightMargin, A4[1] - 10 * mm, "PAYSLIP · CONTINUED")
        canvas.setStrokeColor(border)
        canvas.setLineWidth(0.4)
        canvas.line(document.leftMargin, 12 * mm, A4[0] - document.rightMargin, 12 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(document.leftMargin, 7.5 * mm, "Finalized Shiftly payroll record")
        canvas.drawRightString(A4[0] - document.rightMargin, 7.5 * mm, f"Page {document.page}")
        canvas.restoreState()

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=19 * mm,
        title=f"Payslip {data['employee']['code']}",
        author=data["organization_name"],
    )
    story = []
    header = Table(
        [[
            [paragraph(data["organization_name"], company), paragraph("FINALIZED PAYROLL", eyebrow)],
            [paragraph("PAYSLIP", title), paragraph(data["run_reference"], ParagraphStyle("reference", parent=muted_body, alignment=TA_RIGHT))],
        ]],
        colWidths=[103 * mm, 72 * mm],
        hAlign="LEFT",
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, blue),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([header, Spacer(1, 9)])

    employee = data["employee"]
    pay_basis_value = employee["pay_basis"]
    if pay_basis_value == "Not recorded" and employee["rates"]:
        pay_basis_value = "Approved rate in finalized snapshot"
    pay_details = "<br/>".join(escape(rate) for rate in employee["rates"]) or "Not recorded in finalized snapshot"
    info_rows = [
        [paragraph("EMPLOYEE", label), paragraph("CLASSIFICATION", label), paragraph("PAY BASIS", label)],
        [paragraph(employee["name"], body), paragraph(employee["classification"], body), paragraph(pay_basis_value, body)],
        [paragraph("EMPLOYEE CODE", label), paragraph("PAY PERIOD", label), paragraph("PAY DATE", label)],
        [paragraph(employee["code"], body), paragraph(f"{data['period_start']:%b %d, %Y} – {data['period_end']:%b %d, %Y}", body), paragraph(f"{data['pay_date']:%b %d, %Y}", body)],
        [paragraph("APPROVED SALARY RATE", label), "", ""],
        [Paragraph(pay_details, body), "", ""],
    ]
    info = Table(info_rows, colWidths=[58 * mm, 58 * mm, 59 * mm], hAlign="LEFT")
    info.setStyle(TableStyle([
        ("SPAN", (0, 4), (-1, 4)),
        ("SPAN", (0, 5), (-1, 5)),
        ("BACKGROUND", (0, 0), (-1, -1), pale_blue),
        ("BOX", (0, 0), (-1, -1), 0.6, border),
        ("INNERGRID", (0, 0), (-1, 3), 0.35, border),
        ("LINEABOVE", (0, 4), (-1, 4), 0.35, border),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([info, Spacer(1, 12)])

    compact_sections = len(data["compensation_rows"]) <= 8 and len(data["deduction_rows"]) <= 8
    if compact_sections:
        paired_headings = Table(
            [[paragraph("Compensation", section), paragraph("Deductions", section)]],
            colWidths=[85.5 * mm, 85.5 * mm],
            hAlign="LEFT",
        )
        paired_headings.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ]))
        paired_tables = Table(
            [[
                amount_detail_table(data["compensation_rows"], "Gross earnings", data["gross"], 83.5 * mm),
                amount_detail_table(data["deduction_rows"], "Total employee deductions", data["deductions"], 83.5 * mm),
            ]],
            colWidths=[85.5 * mm, 85.5 * mm],
            hAlign="LEFT",
        )
        paired_tables.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([paired_headings, paired_tables])
        if data["work_adjustment_note"]:
            story.extend([Spacer(1, 5), paragraph(data["work_adjustment_note"], muted_body)])
    else:
        story.extend(amount_table("Compensation", data["compensation_rows"], "Gross earnings", data["gross"]))
        if data["work_adjustment_note"]:
            story.extend([Spacer(1, 5), paragraph(data["work_adjustment_note"], muted_body)])
        story.extend([Spacer(1, 12)])
        story.extend(amount_table("Deductions", data["deduction_rows"], "Total employee deductions", data["deductions"]))

    summary_rows = [
        [paragraph("Compensation subtotal", body), paragraph(_money_label(data["compensation_subtotal"]), amount)],
    ]
    if data["allowance_total"]:
        summary_rows.append([paragraph("Allowance / COLA", body), paragraph(_money_label(data["allowance_total"]), amount)])
    summary_rows.extend([
        [paragraph("Gross earnings", body), paragraph(_money_label(data["gross"]), amount_bold)],
        [paragraph("Total employee deductions", body), paragraph(_money_label(data["deductions"]), amount_bold)],
        [paragraph("NET PAY", net_label), paragraph(_money_label(data["net"]), net_amount)],
    ])
    summary = Table(summary_rows, colWidths=[120 * mm, 55 * mm], hAlign="LEFT")
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale_gray),
        ("LINEABOVE", (0, 2 if data["allowance_total"] else 1), (-1, 2 if data["allowance_total"] else 1), 0.5, border),
        ("BACKGROUND", (0, -1), (-1, -1), pale_green),
        ("BOX", (0, 0), (-1, -1), 0.75, border),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(KeepTogether([Spacer(1, 12), paragraph("Pay summary", section), summary]))

    if data["employer_contributions"] or data["employer_contribution_rows"]:
        employer_section = [Spacer(1, 12)]
        employer_section.extend(amount_table(
            "Employer statutory contributions",
            data["employer_contribution_rows"],
            "Total employer contributions",
            data["employer_contributions"],
        ))
        employer_section.append(paragraph("Employer contributions are informational and do not reduce the employee's net pay.", muted_body))
        story.append(KeepTogether(employer_section))

    acknowledgment = Table(
        [[
            paragraph("Employee acknowledgment", label), paragraph("Date", label),
        ], [
            "\n\n____________________________________________", "\n\n________________________",
        ]],
        colWidths=[123 * mm, 52 * mm],
        hAlign="LEFT",
    )
    acknowledgment.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, border),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([Spacer(1, 18), KeepTogether([acknowledgment, Spacer(1, 5), paragraph("This payslip records finalized payroll amounts. It is not proof that payment has been transferred.", muted_body)])])

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()
