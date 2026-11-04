import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from aiosmtplib import SMTP

from app.core.config import settings
from app.core.security import build_delete_url, build_reset_url

logger = logging.getLogger(__name__)

# Brand tokens, kept in sync with the mobile app and web portal.
BG = "#060B14"
SURFACE = "#0E1624"
OUTLINE = "#22304A"
PRIMARY = "#2DD4B4"
SECONDARY = "#33D6FF"
ON_PRIMARY = "#032A23"
TEXT = "#E8EEF8"
TEXT_MUTED = "#9AA8C1"
DANGER = "#F87171"


def _html(title: str, intro: str, button: str, url: str, footer: str, danger: bool = False) -> str:
    title, intro, button, footer = (escape(x) for x in (title, intro, button, footer))
    href = escape(url, quote=True)
    if danger:
        button_style = f"background:{DANGER};color:#2A0707;"
    else:
        button_style = f"background:{PRIMARY};background-image:linear-gradient(135deg,{PRIMARY},{SECONDARY});color:{ON_PRIMARY};"
    return f"""<!DOCTYPE html>
<html lang="tr">
  <body style="margin:0;padding:0;background:{BG};font-family:Arial,Helvetica,sans-serif;color:{TEXT};">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:{BG};padding:40px 16px;">
      <tr>
        <td align="center">
          <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:{SURFACE};border:1px solid {OUTLINE};border-radius:20px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 8px 32px;text-align:center;">
                <div style="font-size:20px;font-weight:800;color:{PRIMARY};">SynapCart</div>
                <h1 style="margin:16px 0 0 0;font-size:26px;line-height:34px;color:#ffffff;">{title}</h1>
                <p style="margin:16px 0 0 0;font-size:16px;line-height:26px;color:{TEXT_MUTED};">{intro}</p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:28px 32px 8px 32px;">
                <a href="{href}" style="display:inline-block;{button_style}text-decoration:none;font-weight:700;font-size:16px;padding:14px 24px;border-radius:12px;">{button}</a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 8px 32px;text-align:center;">
                <p style="margin:0;font-size:14px;line-height:22px;color:{TEXT_MUTED};">Buton çalışmazsa aşağıdaki bağlantıyı kopyalayın:</p>
                <p style="margin:10px 0 0 0;word-break:break-all;font-size:13px;line-height:20px;">
                  <a href="{href}" style="color:{PRIMARY};text-decoration:underline;">{escape(url)}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 32px 32px;text-align:center;">
                <p style="margin:0;font-size:12px;line-height:18px;color:{TEXT_MUTED};">{footer}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


async def _send(email: str, subject: str, text: str, html_body: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.SMTP_USER
    message["To"] = email
    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    async with SMTP(hostname=settings.SMTP_SERVER, port=settings.SMTP_PORT, timeout=20) as smtp:
        await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        await smtp.sendmail(settings.SMTP_USER, email, message.as_string())


async def send_reset_email(email: str, token: str):
    url = build_reset_url(token)
    hours = settings.RESET_TOKEN_EXPIRE_HOURS
    footer = f"Bu link {hours} saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayabilirsiniz."
    text = f"""Merhaba,

Şifrenizi sıfırlamak için aşağıdaki linke tıklayın:

{url}

{footer}

SynapCart
"""
    html_body = _html(
        "Şifre Sıfırlama Talebi",
        "Hesabınız için bir şifre sıfırlama isteği aldık. Devam etmek için aşağıdaki butona tıklayın.",
        "Şifremi Sıfırla",
        url,
        footer,
    )
    await _send(email, "SynapCart - Şifre Sıfırlama", text, html_body)


async def send_delete_email(email: str, token: str):
    url = build_delete_url(token)
    hours = settings.DELETE_TOKEN_EXPIRE_HOURS
    footer = (
        f"Bu link {hours} saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayın; "
        "hesabınız silinmez."
    )
    intro = (
        "Hesabınızın silinmesi için bir talep aldık. Onaylarsanız hesabınız, sohbet geçmişiniz ve "
        "favorileriniz kalıcı olarak silinir. Bu işlem geri alınamaz."
    )
    text = f"""Merhaba,

{intro}

Silme işlemini onaylamak için aşağıdaki linki açın:

{url}

{footer}

SynapCart
"""
    html_body = _html("Hesap Silme Talebi", intro, "Hesabımı Sil", url, footer, danger=True)
    await _send(email, "SynapCart - Hesap Silme Onayı", text, html_body)
