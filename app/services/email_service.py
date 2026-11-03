import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from aiosmtplib import SMTP

from app.core.config import settings
from app.core.security import build_reset_url

logger = logging.getLogger(__name__)


async def send_reset_email(email: str, token: str):
    reset_url = build_reset_url(token)
    hours = settings.RESET_TOKEN_EXPIRE_HOURS

    message = MIMEMultipart("alternative")
    message["Subject"] = "SynapCart - Şifre Sıfırlama"
    message["From"] = settings.SMTP_USER
    message["To"] = email

    text = f"""Merhaba,

Şifrenizi sıfırlamak için aşağıdaki linke tıklayın:

{reset_url}

Bu link {hours} saat geçerlidir.

SynapCart Team
"""

    html_body = f"""
<!DOCTYPE html>
<html lang="tr">
  <body style="margin:0;padding:0;background:#0f1115;font-family:Arial,Helvetica,sans-serif;color:#e8eef8;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1115;padding:40px 16px;">
      <tr>
        <td align="center">
          <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#151923;border:1px solid #242b3a;border-radius:20px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 8px 32px;text-align:center;">
                <div style="font-size:14px;letter-spacing:2px;text-transform:uppercase;color:#6bdcff;font-weight:700;">SynapCart</div>
                <h1 style="margin:16px 0 0 0;font-size:28px;line-height:36px;color:#ffffff;">Şifre Sıfırlama Talebi</h1>
                <p style="margin:16px 0 0 0;font-size:16px;line-height:26px;color:#b7c3d9;">
                  Hesabınız için bir şifre sıfırlama isteği aldık. Devam etmek için aşağıdaki butona tıklayın.
                </p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:28px 32px 8px 32px;">
                <a href="{reset_url}"
                   style="display:inline-block;background:linear-gradient(135deg,#33d6ff,#55f0c4);color:#0b1020;text-decoration:none;font-weight:700;font-size:16px;padding:14px 24px;border-radius:12px;">
                  Şifremi Sıfırla
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 8px 32px;text-align:center;">
                <p style="margin:0;font-size:14px;line-height:22px;color:#8e9bb3;">
                  Buton çalışmazsa aşağıdaki bağlantıyı kopyalayın:
                </p>
                <p style="margin:10px 0 0 0;word-break:break-all;font-size:13px;line-height:20px;color:#6bdcff;">
                  <a href="{reset_url}" style="color:#6bdcff;text-decoration:underline;">{reset_url}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 32px 32px;text-align:center;">
                <p style="margin:0;font-size:12px;line-height:18px;color:#71819b;">
                  Bu link {hours} saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayabilirsiniz.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    async with SMTP(hostname=settings.SMTP_SERVER, port=settings.SMTP_PORT, timeout=20) as smtp:
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        await smtp.sendmail(settings.SMTP_USER, email, message.as_string())