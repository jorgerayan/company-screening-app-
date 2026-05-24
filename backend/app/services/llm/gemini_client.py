"""
Gemini client — only instantiated in backend. API key never leaves this module.
All LLM modules use this client. Responses are forced to JSON via system prompt.
"""
import asyncio
import json
import time
from typing import Optional, List
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

genai.configure(api_key=settings.gemini_api_key)


class GeminiQuotaError(RuntimeError):
    """Raised when Gemini returns 429 Resource Exhausted after all retries."""


class GeminiTimeoutError(RuntimeError):
    """Raised when a Gemini call exceeds llm_timeout_seconds.

    Wraps asyncio.TimeoutError so str(e) is never empty and the orchestrator
    can store a meaningful error_message instead of a blank string.
    """


def _quota_error_callback(retry_state):
    """
    tenacity retry_error_callback — called when all retry attempts are exhausted.
    Converts ResourceExhausted (429) into a clean GeminiQuotaError so the
    orchestrator can surface a human-readable message instead of a raw RetryError.
    For other exceptions, re-raises the original error directly.
    """
    exc = retry_state.outcome.exception()
    if isinstance(exc, ResourceExhausted):
        raise GeminiQuotaError(
            "Gemini API quota exhausted (429 Resource Exhausted). "
            "The free-tier rate limit has been reached. "
            "Wait a few minutes and try again, or upgrade your Gemini plan."
        ) from exc
    raise exc


_FORMAT_INSTRUCTIONS = {
    "es": "IMPORTANTE: Responde ÚNICAMENTE con un objeto JSON válido. Sin markdown, sin explicaciones, sin bloques de código. Solo JSON puro.",
    "en": "IMPORTANT: Respond ONLY with a valid JSON object. No markdown, no explanation, no code fences. Pure JSON.",
    "fr": "IMPORTANT: Répondez UNIQUEMENT avec un objet JSON valide. Pas de markdown, pas d'explication, pas de blocs de code. JSON pur uniquement.",
    "de": "WICHTIG: Antworte NUR mit einem gültigen JSON-Objekt. Kein Markdown, keine Erklärung, keine Code-Blöcke. Nur reines JSON.",
    "it": "IMPORTANTE: Rispondi SOLO con un oggetto JSON valido. Nessun markdown, nessuna spiegazione, nessun blocco di codice. Solo JSON puro.",
}

# Appended at the END of every prompt (highest recency weight).
# Forces all free-text fields to the target language regardless of source language.
_LANG_FINAL_REMINDER = {
    "es": (
        "\n\n---\nRECORDATORIO FINAL OBLIGATORIO: Escribe TODOS los campos de texto del JSON en español. "
        "Incluye sin excepción narrativas, análisis, descripciones, razonamientos, señales, "
        "interpretaciones, resúmenes y notas. Si el material fuente está en otro idioma, redacta en español.\n"
        "DISCIPLINA EPISTÉMICA: Presenta como hecho solo lo observado directamente en fuentes. "
        "Lo deducido debe ir precedido de 'aparentemente', 'parece que' o similar. "
        "Nunca escribas 'es líder', 'tiene alta tracción', 'base de clientes consolidada' como hecho "
        "sin evidencia externa verificable. Si un dato es desconocido, dilo explícitamente."
    ),
    "en": (
        "\n\n---\n"
        "EPISTEMIC DISCIPLINE: Present as fact only what is directly observed in sources. "
        "Prefix inferences with 'apparently', 'seems to', 'based on self-reported data'. "
        "Never write 'is a leader', 'has strong traction', 'established client base' as fact "
        "without verifiable external evidence. If data is unknown, state it explicitly."
    ),
    "fr": (
        "\n\n---\nRAPPEL FINAL OBLIGATOIRE: Rédigez TOUS les champs de texte du JSON en français. "
        "Incluez sans exception narratives, analyses, descriptions, raisonnements, signaux, "
        "interprétations, résumés et notes. Si le matériau source est dans une autre langue, rédigez en français.\n"
        "DISCIPLINE ÉPISTÉMIQUE: Présentez comme fait uniquement ce qui est directement observé dans les sources. "
        "Préfixez les inférences avec 'apparemment', 'semble', 'selon les données autodéclarées'. "
        "N'écrivez jamais 'est leader', 'a une forte traction' comme fait sans preuve externe vérifiable."
    ),
    "de": (
        "\n\n---\nABSCHLIESSENDE PFLICHT-ERINNERUNG: Schreibe ALLE Textfelder im JSON auf Deutsch. "
        "Umfasst ausnahmslos Narrative, Analysen, Beschreibungen, Begründungen, Signale, "
        "Interpretationen, Zusammenfassungen und Notizen. Quellmaterial in anderen Sprachen auf Deutsch verfassen.\n"
        "EPISTEMISCHE DISZIPLIN: Stelle nur als Fakt dar, was direkt in Quellen beobachtet wurde. "
        "Schlussfolgerungen mit 'offenbar', 'scheint' oder 'laut eigenen Angaben' einleiten. "
        "Niemals 'ist Marktführer', 'hat starke Zugkraft' als Fakt ohne externe Belege schreiben."
    ),
    "it": (
        "\n\n---\nPROMEMORIA FINALE OBBLIGATORIO: Scrivi TUTTI i campi di testo del JSON in italiano. "
        "Include senza eccezione narrazioni, analisi, descrizioni, ragionamenti, segnali, "
        "interpretazioni, riassunti e note. Se il materiale sorgente è in un'altra lingua, redigi in italiano.\n"
        "DISCIPLINA EPISTEMICA: Presenta come fatto solo ciò che è direttamente osservato nelle fonti. "
        "Anteponi alle inferenze 'apparentemente', 'sembra', 'secondo dati autodichiarati'. "
        "Non scrivere mai 'è leader', 'ha forte trazione' come fatto senza prove esterne verificabili."
    ),
}


class GeminiClient:
    def __init__(self):
        # response_mime_type enforces constrained JSON decoding:
        # the model is required to produce syntactically complete, valid JSON.
        # This eliminates truncated-JSON failures caused by thinking-mode token
        # consumption on gemini-2.5+ models and prevents code-fence wrapping.
        self.model = genai.GenerativeModel(
            settings.gemini_model,
            generation_config={"response_mime_type": "application/json"},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=15, max=60),
        retry=retry_if_not_exception_type(asyncio.TimeoutError),
        retry_error_callback=_quota_error_callback,
    )
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        expected_keys: Optional[List[str]] = None,
        language: str = "en",
    ) -> dict:
        """
        Call Gemini and return parsed JSON.
        Raises ValueError if response is not valid JSON.
        """
        format_instruction = _FORMAT_INSTRUCTIONS.get(language, _FORMAT_INSTRUCTIONS["en"])
        lang_reminder = _LANG_FINAL_REMINDER.get(language, "")
        full_prompt = (
            f"{system_prompt}\n\n"
            f"{format_instruction}\n\n"
            f"{user_prompt}"
            f"{lang_reminder}"
        )

        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self.model.generate_content, full_prompt),
                timeout=settings.llm_timeout_seconds,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            raise GeminiTimeoutError(
                f"Gemini {settings.gemini_model} did not respond within "
                f"{settings.llm_timeout_seconds}s (elapsed: {elapsed}ms). "
                f"If this persists, increase LLM_TIMEOUT_SECONDS in .env."
            )
        duration_ms = int((time.monotonic() - start) * 1000)

        raw_text = response.text.strip()

        # Strip accidental code fences if model ignores instructions.
        # Handles both opening AND closing fences (e.g. ```json\n{...}\n```).
        if raw_text.startswith("```"):
            parts = raw_text.split("```")
            # parts[0]="" parts[1]="json\n{...}\n" parts[2]=""
            raw_text = parts[1] if len(parts) > 1 else raw_text
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            # raw_decode tolerates trailing content after the JSON object
            # (e.g. closing code fence, thinking-mode tokens, or trailing notes
            # appended by gemini-2.5-flash after the closing brace).
            # json.loads would raise "Extra data" in those cases.
            parsed, end_index = json.JSONDecoder().raw_decode(raw_text)
            trailing = raw_text[end_index:].strip()
            if trailing:
                module_hint = system_prompt.splitlines()[0][:80]
                logger.warning(
                    "Gemini trailing content detected "
                    f"({len(trailing)} chars after JSON). "
                    f"Tail sample: {trailing[:120]!r}. "
                    f"Module: {module_hint!r}"
                )
        except json.JSONDecodeError as e:
            module_hint = system_prompt.splitlines()[0][:80]
            logger.error(
                f"Gemini returned non-JSON (len={len(raw_text)}). "
                f"Module: {module_hint!r}. "
                f"Head: {raw_text[:200]!r}. "
                f"Tail: {raw_text[-200:]!r}"
            )
            raise ValueError(f"Gemini response is not valid JSON: {e}")

        if expected_keys:
            missing = [k for k in expected_keys if k not in parsed]
            if missing:
                logger.warning(f"Gemini response missing keys: {missing}")

        logger.debug(f"Gemini call took {duration_ms}ms")
        return {"data": parsed, "duration_ms": duration_ms}



gemini_client = GeminiClient()