from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class AIRewriteError(Exception):
    """Base error for provider rewrite failures."""


class AIConfigurationError(AIRewriteError):
    pass


class AITemporaryError(AIRewriteError):
    pass


class AIPermanentError(AIRewriteError):
    pass


@dataclass(frozen=True)
class AIRewriteResult:
    content: str
    model: str
    provider: str
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0


class AIRewriteClient(Protocol):
    def rewrite_news_item(
        self,
        *,
        segment_name: str,
        base_knowledge: str | None,
        disclaimer: str | None,
        original_content: str,
        external_url: str | None,
        author_handle: str | None,
    ) -> AIRewriteResult:
        pass


class FallbackAIRewriteClient:
    def rewrite_news_item(
        self,
        *,
        segment_name: str,
        base_knowledge: str | None,
        disclaimer: str | None,
        original_content: str,
        external_url: str | None,
        author_handle: str | None,
    ) -> AIRewriteResult:
        author = (author_handle or "fonte").strip().lstrip("@") or "fonte"
        suffix = f"\n\n{disclaimer.strip()}" if disclaimer else ""
        url = external_url or ""
        content = (
            f"**Atualizacao de @{author}.** {original_content[:800].strip()}"
            f"\n\nFonte: {url}{suffix}"
        )
        return AIRewriteResult(content=content, model="fallback-editorial", provider="fallback")


class OpenAIResponsesRewriteClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        input_cost_per_million_tokens: float = 0.0,
        output_cost_per_million_tokens: float = 0.0,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.input_cost_per_million_tokens = max(input_cost_per_million_tokens, 0.0)
        self.output_cost_per_million_tokens = max(output_cost_per_million_tokens, 0.0)
        self.base_url = base_url.rstrip("/")

    def rewrite_news_item(
        self,
        *,
        segment_name: str,
        base_knowledge: str | None,
        disclaimer: str | None,
        original_content: str,
        external_url: str | None,
        author_handle: str | None,
    ) -> AIRewriteResult:
        payload = {
            "model": self.model,
            "instructions": _rewrite_instructions(segment_name),
            "input": _rewrite_prompt(
                segment_name=segment_name,
                base_knowledge=base_knowledge,
                disclaimer=disclaimer,
                original_content=original_content,
                external_url=external_url,
                author_handle=author_handle,
            ),
            "max_output_tokens": 700,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AITemporaryError("Timeout na IA") from exc
        except httpx.TransportError as exc:
            raise AITemporaryError(str(exc)) from exc

        if response.status_code in {401, 403}:
            raise AIConfigurationError("Credencial de IA invalida ou sem permissao")
        if response.status_code == 429 or response.status_code >= 500:
            raise AITemporaryError(f"Provider IA indisponivel: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise AIPermanentError(f"Provider IA rejeitou a request: HTTP {response.status_code}")

        data = response.json()
        content = _extract_response_text(data).strip()
        if not content:
            raise AITemporaryError("Provider IA retornou resposta vazia")

        usage = data.get("usage") or {}
        input_tokens = _int_or_none(usage.get("input_tokens"))
        output_tokens = _int_or_none(usage.get("output_tokens"))
        return AIRewriteResult(
            content=content,
            model=str(data.get("model") or self.model),
            provider="openai",
            provider_response_id=str(data.get("id")) if data.get("id") else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost_usd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_per_million_tokens=self.input_cost_per_million_tokens,
                output_cost_per_million_tokens=self.output_cost_per_million_tokens,
            ),
        )


def make_ai_rewrite_client(settings: Settings) -> AIRewriteClient:
    provider = settings.ai_provider.strip().lower()
    if provider in {"fallback", "none", "disabled"}:
        return FallbackAIRewriteClient()
    if provider != "openai":
        raise AIConfigurationError(f"Provider IA nao suportado: {settings.ai_provider}")
    if not settings.ai_api_key:
        raise AIConfigurationError("LABBY_AI_API_KEY nao configurada")
    return OpenAIResponsesRewriteClient(
        api_key=settings.ai_api_key,
        model=settings.ai_model_default,
        timeout_seconds=settings.ai_timeout_seconds,
        input_cost_per_million_tokens=settings.ai_input_cost_per_million_tokens,
        output_cost_per_million_tokens=settings.ai_output_cost_per_million_tokens,
        base_url=settings.ai_base_url,
    )


def _rewrite_instructions(segment_name: str) -> str:
    return (
        "Voce e editor de noticias da Labby. Reescreva posts capturados para um digest "
        f"do segmento {segment_name}. Seja factual, conciso, sem inventar detalhes, e "
        "mantenha tom profissional em portugues do Brasil. Preserve links e fontes. "
        "Nao use clickbait."
    )


def _rewrite_prompt(
    *,
    segment_name: str,
    base_knowledge: str | None,
    disclaimer: str | None,
    original_content: str,
    external_url: str | None,
    author_handle: str | None,
) -> str:
    parts = [
        f"Segmento: {segment_name}",
        f"Autor no X: @{(author_handle or 'fonte').strip().lstrip('@')}",
        f"URL da fonte: {external_url or ''}",
        "",
        "Post original:",
        original_content.strip(),
    ]
    if base_knowledge:
        parts.extend(["", "Contexto editorial do segmento:", base_knowledge.strip()])
    if disclaimer:
        parts.extend(["", "Disclaimer obrigatorio:", disclaimer.strip()])
    parts.extend(
        [
            "",
            "Entregue apenas o texto final do item do digest. Use no maximo 2 paragrafos.",
        ]
    )
    return "\n".join(parts)


def _extract_response_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text

    texts: list[str] = []
    for output in data.get("output") or []:
        for content in output.get("content") or []:
            text_value = content.get("text")
            if isinstance(text_value, str):
                texts.append(text_value)
    return "\n".join(texts)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _estimate_cost_usd(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    input_cost_per_million_tokens: float,
    output_cost_per_million_tokens: float,
) -> float:
    input_cost = (input_tokens or 0) * input_cost_per_million_tokens / 1_000_000
    output_cost = (output_tokens or 0) * output_cost_per_million_tokens / 1_000_000
    return round(input_cost + output_cost, 8)
