"""Generate the demo receipts in demo-receipts/ from the mock Textract responses.

    cd backend && uv run python -m scripts.make_demo_receipts

Each image is drawn from its mock response (same merchant, items and totals), so it looks
right next to what the mock extractor returns, and real Textract reads the same values.
Dates are set relative to today (this month, plus one last month) so the dashboard has data;
rerun the script to refresh them. It also writes mock_responses/demo_index.json, which lets
the mock extractor recognize a demo file by its bytes.
"""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from app.services.textract import MOCK_RESPONSES_DIR

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "demo-receipts"
INDEX = MOCK_RESPONSES_DIR / "demo_index.json"


def demo_dates(today: date) -> dict[str, date]:
    """Spread across the current month (never before the 1st), plus one last month."""
    first = today.replace(day=1)

    def this_month(days_ago: int) -> date:
        return max(first, today - timedelta(days=days_ago))

    last_month = (first - timedelta(days=1)).replace(day=20)
    return {
        "grocery": this_month(2),
        "restaurant": this_month(5),
        "gas_station": this_month(9),
        "coffee": today,
        "pharmacy": last_month,
    }


# sample -> (output file, format)
DEMOS: dict[str, tuple[str, str]] = {
    "grocery": ("kroger-groceries.png", "png"),
    "restaurant": ("joes-diner.jpg", "jpg"),
    "gas_station": ("shell-gas.png", "png"),
    "coffee": ("starbucks-needs-review.jpg", "jpg"),
    "pharmacy": ("cvs-pharmacy.pdf", "pdf"),
}


def _fields(doc: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in doc["SummaryFields"]:
        t, v = f["Type"]["Text"], (f.get("ValueDetection") or {}).get("Text")
        if v and t not in out:
            out[t] = v
    return out


def receipt_lines(sample: dict[str, Any], when: date) -> list[tuple[str, str]]:
    """(style, text) lines; style is "title", "center", "row" or "rule"."""
    doc = sample["ExpenseDocuments"][0]
    f = _fields(doc)
    lines: list[tuple[str, str]] = [("title", f.get("VENDOR_NAME") or f.get("NAME", ""))]
    lines += [("center", part) for part in f.get("ADDRESS", "").split("\n") if part]
    lines += [
        ("center", f"Date: {when:%m/%d/%Y}  {'08:12' if 'STARBUCKS' in lines[0][1] else '14:32'}"),
        ("rule", ""),
    ]
    for li in doc["LineItemGroups"][0]["LineItems"]:
        lf = {x["Type"]["Text"]: x["ValueDetection"]["Text"] for x in li["LineItemExpenseFields"]}
        name = lf["ITEM"]
        if "QUANTITY" in lf and "UNIT_PRICE" in lf:
            name = f"{lf['QUANTITY']} x {lf['UNIT_PRICE']} {name}"
        price = lf.get("PRICE") or f"{float(lf['UNIT_PRICE']) * float(lf.get('QUANTITY', 1)):.2f}"
        lines.append(("row", f"{name}\t{price.lstrip('$')}"))
    lines.append(("rule", ""))
    for label, key in (("SUBTOTAL", "SUBTOTAL"), ("TAX", "TAX"), ("TIP", "GRATUITY")):
        if key in f:
            lines.append(("row", f"{label}\t{f[key].lstrip('$')}"))
    total = f.get("TOTAL") or f.get("AMOUNT_PAID", "")
    lines += [("row", f"TOTAL\t${total.lstrip('$')}"), ("rule", ""), ("center", "THANK YOU!")]
    return lines


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render_image(lines: list[tuple[str, str]], path: Path, fmt: str) -> None:
    width, pad, line_h = 640, 40, 38
    body, title = _font(24), _font(34)
    height = pad * 2 + line_h * (len(lines) + 2)
    paper = Image.new("RGB", (width, height), (252, 251, 246))
    d = ImageDraw.Draw(paper)
    y = pad
    for style, text in lines:
        if style == "title":
            w = d.textlength(text, font=title)
            d.text(((width - w) / 2, y), text, font=title, fill=(20, 20, 20))
            y += line_h + 12
            continue
        if style == "rule":
            d.text((pad, y), "-" * 38, font=body, fill=(110, 110, 110))
        elif style == "center":
            w = d.textlength(text, font=body)
            d.text(((width - w) / 2, y), text, font=body, fill=(40, 40, 40))
        else:
            left, right = text.split("\t")
            d.text((pad, y), left, font=body, fill=(30, 30, 30))
            w = d.textlength(right, font=body)
            d.text((width - pad - w, y), right, font=body, fill=(30, 30, 30))
        y += line_h
    # A fake barcode, for looks.
    for i in range(0, 300, 6):
        d.rectangle((170 + i, y + 10, 170 + i + (2 if i % 18 else 4), y + 60), fill=(30, 30, 30))
    # JPG demos sit on a darker "table" like a phone photo.
    if fmt == "jpg":
        photo = Image.new("RGB", (width + 120, height + 120), (92, 84, 74))
        photo.paste(paper, (60, 60))
        photo.save(path, "JPEG", quality=88)
    else:
        paper.save(path, "PNG", optimize=True)


def render_pdf(lines: list[tuple[str, str]], path: Path) -> None:
    pdf = FPDF(format=(90, 30 + 7 * len(lines)))
    pdf.set_margins(6, 8, 6)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    for style, text in lines:
        if style == "title":
            pdf.set_font("courier", "B", 14)
            pdf.cell(0, 9, text, align="C", new_x="LMARGIN", new_y="NEXT")
        elif style == "rule":
            pdf.set_font("courier", size=9)
            pdf.cell(0, 6, "-" * 40, new_x="LMARGIN", new_y="NEXT")
        elif style == "center":
            pdf.set_font("courier", size=9)
            pdf.cell(0, 6, text, align="C", new_x="LMARGIN", new_y="NEXT")
        else:
            left, right = text.split("\t")
            pdf.set_font("courier", size=9)
            pdf.cell(55, 6, left)
            pdf.cell(0, 6, right, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def main(today: date | None = None) -> None:
    today = today or date.today()
    OUT.mkdir(exist_ok=True)
    index: dict[str, dict[str, str]] = {}
    for sample, when in demo_dates(today).items():
        filename, fmt = DEMOS[sample]
        data = json.loads((MOCK_RESPONSES_DIR / f"{sample}.json").read_text())
        lines = receipt_lines(data, when)
        path = OUT / filename
        if fmt == "pdf":
            render_pdf(lines, path)
        else:
            render_image(lines, path, fmt)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        index[digest] = {"sample": sample, "date": when.isoformat(), "file": filename}
        print(f"{filename:32} {sample:12} {when}")
    INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
