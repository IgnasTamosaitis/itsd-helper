from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from docx import Document


_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "leaver_return_template.docx"
_OUTPUT_DIR = Path(__file__).resolve().parent / "generated_docs"
_RECEIVER_ROLE = "IT engineer"

_ASSET_CATEGORY_ORDER = {
    "laptop": 0,
    "notebook": 0,
    "monitor": 1,
    "phone": 2,
    "mobile": 2,
    "sim": 3,
    "headset": 4,
    "keyboard": 5,
    "mouse": 6,
    "dock": 7,
}


def _format_date(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*]+', "_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "leaver"


def _replace_paragraph_text(paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _asset_name(asset: dict) -> str:
    return (
        (asset.get("category") or {}).get("name")
        or asset.get("name")
        or (asset.get("model") or {}).get("name")
        or "IT asset"
    )


def _manufacturer_model(asset: dict) -> str:
    model = (asset.get("model") or {}).get("name", "").strip()
    manufacturer = ((asset.get("model") or {}).get("manufacturer") or {}).get("name", "").strip()
    if manufacturer and model:
        if manufacturer.casefold() in model.casefold():
            return model
        return f"{manufacturer} {model}"
    return model or manufacturer or asset.get("name", "")


def _asset_sort_key(asset: dict) -> tuple[int, str, str]:
    category = ((asset.get("category") or {}).get("name") or "").casefold()
    order = 99
    for keyword, rank in _ASSET_CATEGORY_ORDER.items():
        if keyword in category:
            order = rank
            break
    return (order, category, (asset.get("asset_tag") or asset.get("name") or "").casefold())


def _ensure_asset_rows(table, wanted_rows: int) -> None:
    while len(table.rows) - 1 < wanted_rows:
        table.add_row()


def _fill_asset_table(table, assets: list[dict]) -> None:
    _ensure_asset_rows(table, max(4, len(assets)))

    row_count = len(table.rows) - 1
    for idx in range(row_count):
        cells = table.rows[idx + 1].cells
        if idx < len(assets):
            asset = assets[idx]
            cells[0].text = str(idx + 1)
            cells[1].text = _asset_name(asset)
            cells[2].text = _manufacturer_model(asset)
            cells[3].text = (asset.get("asset_tag") or asset.get("serial") or "").strip()
            cells[4].text = "+"
            cells[5].text = "Def. nėra"
        else:
            for cell in cells:
                cell.text = ""


def generate_leaver_return_document(ticket: dict, snipeit=None) -> tuple[Path, list[str]]:
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {_TEMPLATE_PATH}")

    warnings: list[str] = []
    today = date.today()
    snipe_user: dict = {}
    snipe_assets: list[dict] = []

    if snipeit:
        try:
            user = snipeit.find_user(ticket.get("first_name", ""), ticket.get("last_name", ""))
            if user:
                snipe_user = snipeit.get_user_details(user["id"])
                snipe_assets = snipeit.get_user_assets(user["id"])
                if not snipe_assets:
                    warnings.append("No assigned Snipe-IT assets were found for this user.")
            else:
                warnings.append("Could not find this leaver in Snipe-IT.")
        except Exception as exc:
            warnings.append(f"Snipe-IT lookup failed: {exc}")
    else:
        warnings.append("Snipe-IT is not configured, so the asset list could not be filled.")

    assets = sorted(snipe_assets, key=_asset_sort_key)
    employee_role = ticket.get("job_title") or snipe_user.get("jobtitle") or ""
    location = (
        ticket.get("office")
        or ((snipe_user.get("location") or {}).get("name") if snipe_user else "")
        or ticket.get("company")
        or ""
    )
    employee_contact = ticket.get("email") or snipe_user.get("email") or ""
    receiver_name = ticket.get("assignee_name") or ""
    document_date = _format_date(today)
    return_date = _format_date(ticket.get("last_day") or today)

    doc = Document(_TEMPLATE_PATH)

    _replace_paragraph_text(
        doc.paragraphs[3],
        f"Data: {document_date}\nVieta: {location}",
    )
    _replace_paragraph_text(
        doc.paragraphs[5],
        "Darbuotojo vardas, pavardė: "
        f"{ticket.get('name', '')}\n"
        f"Pareigos: {employee_role}\n"
        f"Grąžinimo data: {return_date}",
    )
    _replace_paragraph_text(
        doc.paragraphs[6],
        "Priimančio asmens vardas, pavardė: "
        f"{receiver_name}\n"
        f"Pareigos: {_RECEIVER_ROLE}",
    )
    _replace_paragraph_text(
        doc.paragraphs[10],
        f"Jira ticket: {ticket.get('key', '')}",
    )
    _replace_paragraph_text(
        doc.paragraphs[16],
        "Darbuotojas (grąžinantis įrangą):\n"
        "Parašas: ____________________________\n"
        f"Vardas, pavardė: {ticket.get('name', '')}\n"
        f"Data: {return_date}",
    )
    _replace_paragraph_text(
        doc.paragraphs[17],
        "Kontaktai, kuriais pageidauju gauti dokumentus: "
        f"{employee_contact}",
    )
    _replace_paragraph_text(
        doc.paragraphs[18],
        "Priėmė (atsakingas asmuo):\n"
        "Parašas: ____________________________\n"
        f"Vardas, pavardė: {receiver_name}\n"
        f"Data: {document_date}",
    )

    _fill_asset_table(doc.tables[0], assets)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ticket.get('key', 'leaver')}_{_safe_filename(ticket.get('name', 'leaver'))}_return_act.docx"
    output_path = _OUTPUT_DIR / filename
    doc.save(output_path)
    return output_path, warnings
