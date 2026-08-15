import asyncio
from routers.sync import send_fcm_notifications
from models import Alert

async def test_fcm():
    a = Alert(id=1, disc_perc=50.0, ih_code="INV-TEST")
    await send_fcm_notifications([a], "Test Branch", 1)

asyncio.run(test_fcm())
