import html
import secrets

import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
from app.core.config import settings

from aiosmtplib import SMTP
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  #available for 1 week

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_password.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_byte = plain_password.encode('utf-8')
    hashed_byte = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte, hashed_byte)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)

def build_reset_url(token: str) -> str:
    base_url = settings.APP_FRONTEND_URL.rstrip("/")
    return f"{base_url}/reset-password?token={html.escape(token)}"

async def send_reset_email(email: str, token: str):
    reset_url = build_reset_url(token)

    message = MIMEMultipart("alternative")
    message["Subject"] = "SynapCart - Şifre Sıfırlama"
    message["From"] = settings.SMTP_USER
    message["To"] = email

    text = f"""Merhaba,

Şifrenizi sıfırlamak için aşağıdaki linke tıklayın:

{reset_url}

Bu link 1 saat geçerlidir.

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
                  Bu link 1 saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayabilirsiniz.
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

    async with SMTP(hostname=settings.SMTP_SERVER, port=settings.SMTP_PORT) as smtp:
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        await smtp.sendmail(settings.SMTP_USER, email, message.as_string())