import logging
import asyncio
import firebase_admin
from firebase_admin import messaging

logger = logging.getLogger(__name__)

async def send_push_notification(token: str, title: str, body: str):
    if not firebase_admin._apps:
        logger.warning("Firebase app not initialized, skipping push notification.")
        return False
        
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=token,
        )
        response = await asyncio.to_thread(messaging.send, message)
        logger.info(f"Successfully sent FCM message: {response}")
        return True
    except Exception as e:
        logger.error(f"Error sending FCM message: {e}")
        return False
