from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.models.schemas import TestNotificationRequest
from app.routers.auth import get_current_user
from app.notifications.telegram import send_telegram_message
from app.notifications.email import send_resend_email

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/test", status_code=status.HTTP_200_OK)
async def send_test_notification(
    request: TestNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a test notification to the specified channel."""
    
    if request.channel == "telegram":
        if not settings.TELEGRAM_BOT_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telegram bot token not configured"
            )
        
        success = await send_telegram_message(
            chat_id=request.destination,
            message=f"🎉 Travel Scout test message! Your notifications are working."
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send Telegram message. Check the chat ID."
            )
            
    elif request.channel == "email":
        if not settings.RESEND_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Resend API key not configured"
            )
        
        success = await send_resend_email(
            to=request.destination,
            subject="Travel Scout - Test Notification",
            body="🎉 Your Travel Scout email notifications are working!"
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send email"
            )
    
    return {"success": True, "message": f"Test {request.channel} notification sent"}