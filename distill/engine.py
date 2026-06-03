from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from distill.logs import Logger, null_logger
from distill.providers import DistillerUsage, ProviderResult, call_provider, load_provider_config, traced
from distill.registry import format_registry_for_prompt, load_registry
from distill.storage import record_distill_run, store_results
from distill.transcript_schema import NormalizedTranscript

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "distill" / "prompt.md"
MIN_USEFUL_CHARS = 500
MAX_TRANSCRIPT_CHARS = 80_000


@dataclass(frozen=True)
class DistillationRunResult:
    status: str
    artifacts_returned: int = 0
    facts_returned: int = 0
    artifacts_stored: int = 0
    facts_stored: int = 0
    reason: Optional[str] = None


def run_distillation(
    transcript: NormalizedTranscript,
    logger: Logger = null_logger,
) -> DistillationRunResult:
    run_started_at = datetime.now().astimezone()
    logger(f"distilling {transcript.agent} session {transcript.session_id} from {transcript.source_path}")
    text = transcript.user_assistant_text()
    provider, model = load_provider_config(logger)

    if len(text) < MIN_USEFUL_CHARS:
        reason = f"only {len(text)} chars of user/assistant text"
        logger(f"  skipped: {reason}")
        usage = DistillerUsage.zero(provider, model)
        log_usage(logger, usage, "skipped")
        record_distill_run(
            transcript=transcript,
            usage=usage,
            status="skipped",
            reason=reason,
            transcript_chars=len(text),
            run_started_at=run_started_at,
            logger=logger,
        )
        return DistillationRunResult(status="skipped", reason=reason)

    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[-MAX_TRANSCRIPT_CHARS:]
        logger(f"  truncated to last {MAX_TRANSCRIPT_CHARS} chars")

    clients, projects = load_registry(logger)
    logger(f"  registry loaded: {len(clients)} clients, {len(projects)} projects")
    prompt = render_prompt(format_registry_for_prompt(clients, projects), text)

    logger(f"  calling {provider} ({model or 'default'}) with {len(text)} chars of transcript")

    provider_result = distill(prompt, provider, model, logger)
    log_usage(logger, provider_result.usage, "provider-returned")
    distilled = provider_result.data
    if not distilled:
        logger("  no distillation result")
        record_distill_run(
            transcript=transcript,
            usage=provider_result.usage,
            status="failed",
            reason="no distillation result",
            transcript_chars=len(text),
            prompt_chars=len(prompt),
            run_started_at=run_started_at,
            logger=logger,
        )
        return DistillationRunResult(status="failed", reason="no distillation result")

    artifacts_returned = len(distilled.get("artifacts", []) or [])
    facts_returned = len(distilled.get("facts", []) or [])
    logger(f"  returned {artifacts_returned} artifacts, {facts_returned} facts")
    if artifacts_returned == 0 and facts_returned == 0:
        record_distill_run(
            transcript=transcript,
            usage=provider_result.usage,
            status="empty",
            transcript_chars=len(text),
            prompt_chars=len(prompt),
            artifacts_returned=artifacts_returned,
            facts_returned=facts_returned,
            run_started_at=run_started_at,
            logger=logger,
        )
        return DistillationRunResult(status="empty")

    artifacts_stored, facts_stored = asyncio.run(
        store_results(
            distilled,
            transcript,
            logger,
            distiller_provider=provider_result.usage.provider,
            distiller_model=provider_result.usage.model,
        )
    )
    logger(f"  stored {artifacts_stored}/{artifacts_returned} artifacts and {facts_stored}/{facts_returned} facts")
    record_distill_run(
        transcript=transcript,
        usage=provider_result.usage,
        status="stored",
        transcript_chars=len(text),
        prompt_chars=len(prompt),
        artifacts_returned=artifacts_returned,
        facts_returned=facts_returned,
        artifacts_stored=artifacts_stored,
        facts_stored=facts_stored,
        run_started_at=run_started_at,
        logger=logger,
    )
    return DistillationRunResult(
        status="stored",
        artifacts_returned=artifacts_returned,
        facts_returned=facts_returned,
        artifacts_stored=artifacts_stored,
        facts_stored=facts_stored,
    )


def render_prompt(registry_block: str, transcript_text: str) -> str:
    template = PROMPT_PATH.read_text()
    return template.replace("{registry}", registry_block) + "\n\n--- TRANSCRIPT ---\n" + transcript_text


@traced("distill.session")
def distill(prompt: str, provider: str, model: Optional[str], logger: Logger) -> ProviderResult:
    return call_provider(provider, model, prompt, logger)


def log_usage(logger: Logger, usage: DistillerUsage, status: str) -> None:
    logger(
        "  usage "
        f"status={status} "
        f"provider={usage.provider} "
        f"model={usage.model} "
        f"input={_display_token(usage.input_tokens)} "
        f"output={_display_token(usage.output_tokens)} "
        f"cache_create={_display_token(usage.cache_creation_input_tokens)} "
        f"cache_read={_display_token(usage.cache_read_input_tokens)} "
        f"total={_display_token(usage.total_tokens)} "
        f"wall={usage.wall_seconds if usage.wall_seconds is not None else 'null'}s"
    )


def _display_token(value: Optional[int]) -> str:
    return "null" if value is None else str(value)
