from fastapi import APIRouter
from pydantic import BaseModel

from app.services.hermes import HermesConfig, gateway_process

router = APIRouter(prefix="/gateway")


class TelegramConfigRequest(BaseModel):
    bot_token: str = ""
    allowed_users: str
    home_channel: str | None = None


@router.get("/status")
async def gateway_status():
    return gateway_process.status()


@router.post("/start")
async def start_gateway():
    return await gateway_process.start()


@router.post("/stop")
async def stop_gateway():
    return await gateway_process.stop()


@router.get("/telegram")
async def telegram_config_status():
    env = HermesConfig().read_env()
    return {
        "configured": bool(env.get("TELEGRAM_BOT_TOKEN")),
        "allowed_users": env.get("TELEGRAM_ALLOWED_USERS", ""),
        "home_channel": env.get("TELEGRAM_HOME_CHANNEL", ""),
    }


@router.post("/telegram")
async def save_telegram_config(req: TelegramConfigRequest):
    updates = {
        "TELEGRAM_ALLOWED_USERS": req.allowed_users.strip(),
        "TELEGRAM_HOME_CHANNEL": req.home_channel.strip() if req.home_channel else None,
    }
    if req.bot_token.strip():
        updates["TELEGRAM_BOT_TOKEN"] = req.bot_token.strip()
    HermesConfig().write_env_values(updates)
    return {"success": True}
