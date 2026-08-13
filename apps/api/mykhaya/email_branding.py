"""Branded HTML wrapper for outbound MyKhaya email.

Renders one conservative, table-based, inline-styled layout shared by every
transactional email — no external CSS, no web fonts, no JavaScript, no
tracking pixels — so it degrades gracefully in Outlook's Word rendering
engine as well as Gmail/Apple Mail/iOS/Android clients. The plain-text
version (mykhaya.notifications.templates.render_notification) remains the
source of truth for wording; this only adds presentation around the same
resolved subject/body text, so an admin's template override is reflected in
both without a second content-authoring path.

The logo is a small HTTPS-hosted static PNG on the public MyKhaya web
domain (apps/web/public/mykhaya-email-logo.png, served by whatever serves
the rest of that domain's static assets) — reachable by an unauthenticated
external mail client, unlike anything on the admin/API hosts. It reproduces
apps/web/components/logo.tsx's existing mark/colours exactly; nothing new
was invented.
"""

from __future__ import annotations

from html import escape

from mykhaya.config import Settings

# Mirrors packages/design-tokens/src/tokens.css — the same palette used
# throughout the app, not a separate email colour scheme.
_TERRACOTTA = "#e07a5f"
_SAGE_DARK = "#566b58"
_SLATE = "#233028"
_MUTED = "#62706f"
_CREAM = "#f2ede3"
_WHITE = "#fffefb"

_FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# The label for each template type's primary call-to-action button — the
# body text's own {{link}} line still appears underneath as the fallback URL.
CTA_LABELS: dict[str, str] = {
    "email_verification": "Verify email address",
    "password_reset": "Reset password",
    "household_invitation": "Join Home",
    "platform_administrator_invitation": "Accept invitation",
}


def logo_url(settings: Settings) -> str:
    return f"{settings.public_web_url.rstrip('/')}/mykhaya-email-logo.png"


def _paragraphs_html(body_text: str) -> str:
    blocks = [block.strip() for block in body_text.split("\n\n") if block.strip()]
    rendered = []
    for block in blocks:
        safe = escape(block).replace("\n", "<br>")
        rendered.append(
            f'<p style="margin:0 0 16px;color:{_SLATE};font-size:15px;line-height:1.55;'
            f'font-family:{_FONT_STACK};">{safe}</p>'
        )
    return "".join(rendered)


def render_html(
    settings: Settings,
    *,
    subject: str,
    body_text: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
) -> str:
    """`subject`/`body_text` are the already-resolved (override-aware) plain
    text produced by mykhaya.notifications.templates.render_notification —
    this only wraps them. User-controlled values (display names, Home
    names) reach here only inside `body_text`, already interpolated by
    `templates.substitute`, and are HTML-escaped here before being placed in
    markup — malicious HTML in a display name cannot be injected."""
    safe_subject = escape(subject)
    safe_logo = escape(logo_url(settings))

    cta_html = ""
    if cta_label and cta_url:
        safe_label = escape(cta_label)
        safe_url = escape(cta_url)
        cta_html = f"""
        <tr>
          <td align="center" style="padding:8px 0 24px;">
            <a href="{safe_url}" target="_blank" rel="noopener"
               style="background:{_TERRACOTTA};color:{_WHITE};display:inline-block;
                      padding:12px 28px;border-radius:8px;font-family:{_FONT_STACK};
                      font-size:15px;font-weight:600;text-decoration:none;">{safe_label}</a>
          </td>
        </tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{safe_subject}</title>
</head>
<body style="margin:0;padding:0;background:{_CREAM};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{safe_subject}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:{_CREAM};">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0"
             style="width:480px;max-width:100%;background:{_WHITE};border-radius:12px;">
        <tr>
          <td align="center" style="padding:32px 32px 8px;">
            <img src="{safe_logo}" width="56" height="58" alt="MyKhaya"
                 style="display:block;width:56px;height:58px;">
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:0 32px 8px;">
            <h1 style="margin:0;color:{_SLATE};font-family:{_FONT_STACK};
                       font-size:20px;font-weight:700;">{safe_subject}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px 0;">
            {_paragraphs_html(body_text)}
          </td>
        </tr>
        {cta_html}
        <tr>
          <td style="padding:0 32px 32px;border-top:1px solid {_CREAM};">
            <p style="margin:20px 0 4px;color:{_MUTED};font-family:{_FONT_STACK};
                      font-size:12px;line-height:1.5;"
              >MyKhaya helps families stay connected and organised.</p>
            <p style="margin:0;color:{_MUTED};font-family:{_FONT_STACK};
                      font-size:12px;line-height:1.5;"
              >This is an automated service message from MyKhaya &middot; mykhaya.app</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def render_email_html(
    settings: Settings, template_type: str, subject: str, body_text: str, cta_url: str | None
) -> str:
    """Convenience wrapper used by every real send site — resolves the
    per-type CTA label (if any) and delegates to render_html."""
    return render_html(
        settings,
        subject=subject,
        body_text=body_text,
        cta_label=CTA_LABELS.get(template_type),
        cta_url=cta_url,
    )
