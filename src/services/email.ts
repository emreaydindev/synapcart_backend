/**
 * Transactional email through the Cloudflare Email Service `send_email` binding.
 * The sender domain (EMAIL_FROM, default noreply@synapcart.emreaydin.dev) must be
 * verified for Email Sending in the Cloudflare dashboard.
 */
import type { Env } from "../env";
import { settings } from "../config";
import { buildDeleteUrl, buildResetUrl } from "../lib/security";

// Brand tokens, kept in sync with the apps and web portal.
const BG = "#060B14";
const SURFACE = "#0E1624";
const OUTLINE = "#22304A";
const PRIMARY = "#2DD4B4";
const SECONDARY = "#33D6FF";
const ON_PRIMARY = "#032A23";
const TEXT = "#E8EEF8";
const TEXT_MUTED = "#9AA8C1";
const DANGER = "#F87171";

export class EmailError extends Error {}

const escape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;");

function html(title: string, intro: string, button: string, url: string, footer: string, danger = false): string {
  const href = escape(url);
  const buttonStyle = danger
    ? `background:${DANGER};color:#2A0707;`
    : `background:${PRIMARY};background-image:linear-gradient(135deg,${PRIMARY},${SECONDARY});color:${ON_PRIMARY};`;
  return `<!DOCTYPE html>
<html lang="tr">
  <body style="margin:0;padding:0;background:${BG};font-family:Arial,Helvetica,sans-serif;color:${TEXT};">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:${BG};padding:40px 16px;">
      <tr>
        <td align="center">
          <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:${SURFACE};border:1px solid ${OUTLINE};border-radius:20px;overflow:hidden;">
            <tr>
              <td style="padding:32px 32px 8px 32px;text-align:center;">
                <div style="font-size:20px;font-weight:800;color:${PRIMARY};">SynapCart</div>
                <h1 style="margin:16px 0 0 0;font-size:26px;line-height:34px;color:#ffffff;">${escape(title)}</h1>
                <p style="margin:16px 0 0 0;font-size:16px;line-height:26px;color:${TEXT_MUTED};">${escape(intro)}</p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:28px 32px 8px 32px;">
                <a href="${href}" style="display:inline-block;${buttonStyle}text-decoration:none;font-weight:700;font-size:16px;padding:14px 24px;border-radius:12px;">${escape(button)}</a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 8px 32px;text-align:center;">
                <p style="margin:0;font-size:14px;line-height:22px;color:${TEXT_MUTED};">Buton çalışmazsa aşağıdaki bağlantıyı kopyalayın:</p>
                <p style="margin:10px 0 0 0;word-break:break-all;font-size:13px;line-height:20px;">
                  <a href="${href}" style="color:${PRIMARY};text-decoration:underline;">${escape(url)}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 32px 32px;text-align:center;">
                <p style="margin:0;font-size:12px;line-height:18px;color:${TEXT_MUTED};">${escape(footer)}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
`;
}

export interface OutgoingEmail {
  to: string;
  subject: string;
  text: string;
  html: string;
}

/** Test hook: when set, emails are handed here instead of the binding. */
export const outbox: { capture?: (m: OutgoingEmail) => void | Promise<void> } = {};

async function send(env: Env, message: OutgoingEmail): Promise<void> {
  if (outbox.capture) return outbox.capture(message);
  if (env.RESEND_API_KEY) return sendWithResend(env, env.RESEND_API_KEY, message);
  if (!env.SEND_EMAIL) {
    if (settings(env).isProd) throw new EmailError("No email provider configured (RESEND_API_KEY or SEND_EMAIL)");
    console.log(`[email] no email provider; would send "${message.subject}"`);
    return;
  }
  try {
    await env.SEND_EMAIL.send({
      from: { email: settings(env).emailFrom, name: "SynapCart" },
      to: message.to,
      subject: message.subject,
      text: message.text,
      html: message.html,
    });
  } catch (e) {
    throw new EmailError(`Email send failed: ${(e as Error).message}`);
  }
}

/** Resend HTTP API (free tier: 3,000 emails/month, 100/day). The EMAIL_FROM domain must be verified there. */
async function sendWithResend(env: Env, apiKey: string, message: OutgoingEmail): Promise<void> {
  let res: Response;
  try {
    res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: `SynapCart <${settings(env).emailFrom}>`,
        to: [message.to],
        subject: message.subject,
        text: message.text,
        html: message.html,
      }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch (e) {
    throw new EmailError(`Email send failed: ${(e as Error).message}`);
  }
  if (!res.ok) throw new EmailError(`Email send failed: Resend returned ${res.status}`);
}

export async function sendResetEmail(env: Env, email: string, token: string) {
  const url = buildResetUrl(env, token);
  const footer = `Bu link ${settings(env).resetTokenHours} saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayabilirsiniz.`;
  const text = `Merhaba,\n\nŞifrenizi sıfırlamak için aşağıdaki linke tıklayın:\n\n${url}\n\n${footer}\n\nSynapCart\n`;
  await send(env, {
    to: email,
    subject: "SynapCart - Şifre Sıfırlama",
    text,
    html: html(
      "Şifre Sıfırlama Talebi",
      "Hesabınız için bir şifre sıfırlama isteği aldık. Devam etmek için aşağıdaki butona tıklayın.",
      "Şifremi Sıfırla",
      url,
      footer,
    ),
  });
}

export async function sendDeleteEmail(env: Env, email: string, token: string) {
  const url = buildDeleteUrl(env, token);
  const footer = `Bu link ${settings(env).deleteTokenHours} saat geçerlidir. Talebi siz oluşturmadıysanız bu maili yok sayın; hesabınız silinmez.`;
  const intro =
    "Hesabınızın silinmesi için bir talep aldık. Onaylarsanız hesabınız, sohbet geçmişiniz ve favorileriniz kalıcı olarak silinir. Bu işlem geri alınamaz.";
  const text = `Merhaba,\n\n${intro}\n\nSilme işlemini onaylamak için aşağıdaki linki açın:\n\n${url}\n\n${footer}\n\nSynapCart\n`;
  await send(env, {
    to: email,
    subject: "SynapCart - Hesap Silme Onayı",
    text,
    html: html("Hesap Silme Talebi", intro, "Hesabımı Sil", url, footer, true),
  });
}
