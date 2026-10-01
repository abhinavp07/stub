import io
import uuid
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from httpx import AsyncClient
from PIL import Image
from pypdf import PdfReader

from app.services.pdf_report import ReportReceipt, build_report, latin1
from tests.conftest import ClientFactory, upload_receipt, use_sample


def png_bytes(w: int = 3000, h: int = 4000) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (240, 240, 230)).save(out, "PNG")
    return out.getvalue()


def pdf_bytes(pages: int = 2) -> bytes:
    doc = FPDF()
    for i in range(pages):
        doc.add_page()
        doc.set_font("helvetica", size=12)
        doc.cell(0, 10, f"attached receipt page {i + 1}")
    return bytes(doc.output())


def text_of(data: bytes) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(data))
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


def test_report_layout() -> None:
    d, R = Decimal, ReportReceipt
    receipts = [
        R(date(2024, 3, 1), "Kroger", "Groceries", d("100.10"), "image/png", png_bytes()),
        R(date(2024, 3, 2), "Café Müller", "Dining", d("12.50"), "application/pdf", pdf_bytes(2)),
        R(date(2024, 3, 3), "Corner “Store”", None, d("-5.00"), "image/jpeg", b"not an image"),
        R(None, None, "Groceries", None, "image/jpeg", None),
    ]
    data = build_report(
        receipts,
        currency="USD",
        date_from=date(2024, 3, 1),
        date_to=date(2024, 3, 31),
        generated=date(2024, 4, 1),
        owner="alice@example.com",
    )
    pages, text = text_of(data)
    # Summary (1) + image page (1) + unreadable-image page (1) + attached PDF (2).
    assert pages == 5
    assert "Total 107.60 USD across 4 receipts" in text
    assert "2024-03-01 to 2024-03-31" in text
    for expected in ("Groceries", "100.10 USD", "Café Müller", 'Corner "Store"', "Uncategorized"):
        assert expected in text
    assert "couldn't be read" in text
    assert "attached receipt page 2" in text
    # The 3000x4000 PNG was downscaled, so the report stays small.
    assert len(data) < 400_000


def test_latin1_never_raises() -> None:
    assert latin1("Joe’s — “Diner” …") == 'Joe\'s - "Diner" ...'
    assert latin1("東京 ☕") == "?? ?"
    assert latin1(None) == ""


async def test_export_pdf_endpoint(client: AsyncClient, make_client: ClientFactory) -> None:
    use_sample("grocery")
    mine = await upload_receipt(client, png_bytes(40, 60), "image/png", "r.png")
    await client.patch(f"/api/receipts/{mine['id']}", json={"merchant": "My Store"})
    other = await make_client("bob@example.com")
    theirs = await upload_receipt(other)
    await other.patch(f"/api/receipts/{theirs['id']}", json={"merchant": "Bob Secret Shop"})

    resp = await client.get("/api/export/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith('attachment; filename="receipt-report-')
    pages, text = text_of(resp.content)
    assert pages == 2  # summary + one image
    assert "My Store" in text
    assert "Bob Secret Shop" not in text

    empty = await client.get("/api/export/pdf", params={"from": "2030-01-01"})
    assert "across 0 receipts" in text_of(empty.content)[1]
    bad = await client.get("/api/export/pdf", params={"category_id": str(uuid.uuid4())[:8]})
    assert bad.status_code == 422


async def test_export_pdf_requires_auth(make_client: ClientFactory) -> None:
    anon = await make_client()
    assert (await anon.get("/api/export/pdf")).status_code == 401
