from dataclasses import dataclass
from html import escape

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class EmailDeliveryResult:
    sent: bool
    error: str | None = None


class EmailService:
    def send_team_invite(
        self,
        *,
        to_email: str,
        to_name: str,
        tenant_name: str,
        invite_url: str,
    ) -> EmailDeliveryResult:
        settings = get_settings()
        if not settings.resend_api_key:
            return EmailDeliveryResult(sent=False, error="RESEND_API_KEY nao configurada")

        payload = {
            "from": settings.email_from,
            "to": [to_email],
            "subject": f"Convite para acessar {tenant_name} na Labby",
            "html": self._team_invite_html(
                to_name=to_name,
                tenant_name=tenant_name,
                invite_url=invite_url,
            ),
        }

        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return EmailDeliveryResult(sent=False, error=str(exc))

        return EmailDeliveryResult(sent=True)

    @staticmethod
    def _team_invite_html(*, to_name: str, tenant_name: str, invite_url: str) -> str:
        safe_name = escape(to_name)
        safe_tenant = escape(tenant_name)
        safe_url = escape(invite_url, quote=True)
        return f"""
        <div style="background:#070a0f;padding:32px;font-family:Arial,sans-serif;color:#f5f7fb">
          <div style="max-width:560px;margin:0 auto;background:#101720;
                      border:1px solid #1d2a36;border-radius:14px;padding:28px">
            <h1 style="margin:0 0 12px;font-size:24px">Voce foi convidado para a Labby</h1>
            <p style="color:#b8c2cc;line-height:1.6">
              Ola, {safe_name}. Voce recebeu acesso ao workspace <strong>{safe_tenant}</strong>.
            </p>
            <p style="color:#b8c2cc;line-height:1.6">
              Aceite o convite para entrar na plataforma e acessar os modulos liberados.
            </p>
            <a href="{safe_url}"
               style="display:inline-block;margin-top:16px;background:#00d4aa;color:#001b17;
                      text-decoration:none;font-weight:700;padding:12px 18px;border-radius:10px">
              Aceitar convite
            </a>
            <p style="margin-top:24px;color:#6f7b86;font-size:12px">
              Se voce nao esperava este convite, pode ignorar este email.
            </p>
          </div>
        </div>
        """
