"""PDF expense report: a summary (totals by category, then every receipt) followed by the
receipt images. Receipts uploaded as PDFs have their pages appended as-is.

Pure-ish: takes already-loaded rows and file bytes, returns PDF bytes; no I/O.
"""

import io
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Receipt photos can be 10 MB each; downscale before embedding so big reports stay small.
MAX_IMAGE_PX = 1600
JPEG_QUALITY = 80
# Past this many receipts, the report keeps the tables but leaves out attachments.
MAX_ATTACHMENTS = 100

# The built-in PDF fonts are Latin-1 only; map common typography first, replace the rest.
_ASCII = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."})


def latin1(text: str | None) -> str:
    return (text or "").translate(_ASCII).encode("latin-1", "replace").decode("latin-1")


@dataclass
class ReportReceipt:
    purchase_date: date | None
    merchant: str | None
    category: str | None
    total: Decimal | None
    content_type: str
    file: bytes | None = None  # None when not loaded (or over MAX_ATTACHMENTS)


def _money(value: Decimal | None, currency: str) -> str:
    return "" if value is None else f"{value:,.2f} {currency}"


def _downscale(data: bytes) -> bytes:
    """Re-encode an image as a bounded-size JPEG. Raises if it isn't a readable image."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


class _Report(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self.report_title = title
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("helvetica", size=8)
        self.set_text_color(120)
        self.cell(0, 5, latin1(f"{self.report_title} - page {self.page_no()}"), align="R")


def build_report(
    receipts: list[ReportReceipt],
    *,
    currency: str,
    date_from: date | None,
    date_to: date | None,
    generated: date,
    owner: str,
) -> bytes:
    span = (
        f"{date_from or 'the beginning'} to {date_to or generated}"
        if date_from or date_to
        else "all dates"
    )
    pdf = _Report("Stub receipt report")
    pdf.add_page()

    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, "Stub receipt report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    pdf.set_text_color(90)
    pdf.cell(
        0, 5, latin1(f"{owner} - {span} - generated {generated}"), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_text_color(0)
    pdf.ln(4)

    total = sum((r.total or Decimal(0) for r in receipts), Decimal(0))
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(
        0, 7, latin1(f"Total {_money(total, currency)} across {len(receipts)} receipts"),
        new_x="LMARGIN", new_y="NEXT",
    )  # fmt: skip
    pdf.ln(2)

    # Summary by category.
    by_cat: dict[str, list[Decimal]] = defaultdict(list)
    for r in receipts:
        by_cat[r.category or "Uncategorized"].append(r.total or Decimal(0))
    pdf.set_font("helvetica", size=10)
    with pdf.table(
        col_widths=(60, 20, 30), text_align=("LEFT", "RIGHT", "RIGHT"), first_row_as_headings=True
    ) as table:
        table.row(["Category", "Receipts", "Total"])
        for name, totals in sorted(by_cat.items(), key=lambda kv: -sum(kv[1])):
            table.row([latin1(name), str(len(totals)), _money(sum(totals, Decimal(0)), currency)])
    pdf.ln(6)

    # Every receipt.
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 7, "Receipts", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    with pdf.table(
        col_widths=(22, 60, 30, 26),
        text_align=("LEFT", "LEFT", "LEFT", "RIGHT"),
        first_row_as_headings=True,
    ) as table:
        table.row(["Date", "Merchant", "Category", "Total"])
        for r in receipts:
            table.row(
                [
                    str(r.purchase_date or ""),
                    latin1(r.merchant or "(no merchant)"),
                    latin1(r.category or ""),
                    _money(r.total, currency),
                ]
            )
    if len(receipts) > MAX_ATTACHMENTS:
        pdf.ln(4)
        pdf.set_font("helvetica", "I", 9)
        pdf.multi_cell(
            0, 5,
            f"Receipt images are included for the first {MAX_ATTACHMENTS} receipts only. "
            "Export a shorter date range to include the rest.",
        )  # fmt: skip

    # One page per image receipt.
    attached_pdfs: list[bytes] = []
    for r in receipts[:MAX_ATTACHMENTS]:
        if r.file is None:
            continue
        if r.content_type == "application/pdf":
            attached_pdfs.append(r.file)
            continue
        pdf.add_page()
        _attachment_header(pdf, r, currency)
        try:
            image = _downscale(r.file)
        except (UnidentifiedImageError, OSError, ValueError):
            logger.warning("Skipping unreadable image in PDF report")
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 8, "The image for this receipt couldn't be read.")
            continue
        top = pdf.get_y() + 2
        pdf.image(
            io.BytesIO(image),
            x=pdf.l_margin,
            y=top,
            w=pdf.epw,
            h=pdf.h - top - pdf.b_margin - 5,
            keep_aspect_ratio=True,
        )

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(bytes(pdf.output()))))
    for data in attached_pdfs:
        try:
            writer.append(PdfReader(io.BytesIO(data)))
        except Exception:
            logger.warning("Skipping unreadable PDF attachment in report")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _attachment_header(pdf: FPDF, r: ReportReceipt, currency: str) -> None:
    title = f"{r.purchase_date or ''}  {r.merchant or '(no merchant)'}  {_money(r.total, currency)}"
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 7, latin1(title), new_x="LMARGIN", new_y="NEXT")
