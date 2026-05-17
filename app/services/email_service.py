from aiosmtplib import SMTP
from app.core.config import settings

async def send_email(to: str, subject: str, body: str):
    async with SMTP(hostname=settings.SMTP_SERVER, port=settings.SMTP_PORT) as smtp:
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        await smtp.sendmail(
            settings.SMTP_USER,
            to,
            f"Subject: {subject}\n\n{body}"
        )