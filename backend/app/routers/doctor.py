from fastapi import APIRouter

from app.services.hermes import HermesDoctor

router = APIRouter(prefix="/doctor")


@router.get("")
async def get_doctor_status():
    return HermesDoctor().summary()
