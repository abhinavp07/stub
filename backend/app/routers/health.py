from fastapi import APIRouter

from app.auth import SettingsDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: SettingsDep) -> dict[str, str]:
    # textract_mode lets the UI warn that demo mode doesn't actually read receipts.
    return {"status": "ok", "textract_mode": settings.textract_mode}
