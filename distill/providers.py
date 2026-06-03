from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from distill.logs import Logger, null_logger

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVIDERS_YAML = REPO_ROOT / "config" / "providers.yaml"
PROVIDERS_YAML_EXAMPLE = REPO_ROOT / "config" / "providers.example.yaml"

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

DEFAULT_MODELS: dict[str, Optional[str]] = {
    "anthropic-api": "claude-haiku-4-5",
    "openai-api": "gpt-4o-mini",
    "gemini-api": "gemini-1.5-flash",
    "openrouter-api": "anthropic/claude-haiku-4.5",
    "claude-cli": "claude-haiku-4-5-20251001",
    "codex-cli": None,
    "gemini-cli": "gemini-2.5-flash",
    "cursor-cli": "sonnet-4",
}


@dataclass(frozen=True)
class DistillerUsage:
    provider: str
    model: Optional[str]
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    wall_seconds: Optional[float] = None

    @classmethod
    def zero(cls, provider: str, model: Optional[str]) -> "DistillerUsage":
        return cls(
            provider=provider,
            model=model,
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            total_tokens=0,
            wall_seconds=0.0,
        )


@dataclass(frozen=True)
class ProviderResult:
    data: Optional[dict]
    usage: DistillerUsage


def load_provider_config(logger: Logger = null_logger) -> tuple[str, Optional[str]]:
    env_provider = os.environ.get("DISTILL_PROVIDER")
    env_model = os.environ.get("DISTILL_MODEL")
    if env_provider:
        return env_provider, env_model

    cfg_path = PROVIDERS_YAML if PROVIDERS_YAML.exists() else PROVIDERS_YAML_EXAMPLE
    if cfg_path.exists():
        try:
            import yaml

            data = yaml.safe_load(cfg_path.read_text()) or {}
            provider = data.get("default_provider", "claude-cli")
            providers = data.get("providers", {}) or {}
            model = (providers.get(provider) or {}).get("model")
            return provider, model or None
        except Exception as exc:
            logger(f"  could not parse {cfg_path}: {exc}; falling back to claude-cli")

    return "claude-cli", None


def traced(name: str) -> Callable:
    try:
        from langsmith import traceable

        return traceable(name=name)
    except Exception:
        def passthrough(fn):
            return fn

        return passthrough


def call_provider(provider: str, model: Optional[str], prompt: str, logger: Logger = null_logger) -> ProviderResult:
    model_id = model or DEFAULT_MODELS.get(provider)
    logger(f"  provider={provider} model={model_id}")
    if provider == "claude-cli":
        return _call_claude_cli(prompt, model_id, logger)
    if provider == "codex-cli":
        return _call_codex_cli(prompt, model_id, logger)
    if provider == "gemini-cli":
        return _call_gemini_cli(prompt, model_id, logger)
    if provider == "cursor-cli":
        return _call_cursor_cli(prompt, model_id, logger)
    if provider == "anthropic-api":
        return _call_anthropic_api(prompt, model_id, logger)
    if provider == "openai-api":
        return _call_openai_api(prompt, model_id, logger)
    if provider == "gemini-api":
        return _call_gemini_api(prompt, model_id, logger)
    if provider == "openrouter-api":
        return _call_openrouter_api(prompt, model_id, logger)
    logger(f"  unknown provider: {provider}")
    return ProviderResult(None, DistillerUsage.zero(provider, model_id))


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


@traced("distill.claude-cli")
def _call_claude_cli(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    cli = shutil.which("claude")
    _fallback = os.path.expanduser("~/.local/bin/claude")
    if not cli and os.path.exists(_fallback):
        cli = _fallback
    if not cli:
        logger("  claude CLI not found")
        return ProviderResult(None, _zero_usage("claude-cli", model, started))

    cmd = [
        cli, "-p",
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        prompt,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        logger(f"  claude CLI failed (exit {result.returncode}): {result.stderr[:300]}")
        return ProviderResult(None, _usage("claude-cli", model, started))
    try:
        outer = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger(f"  claude wrapper parse failed: {exc}")
        return ProviderResult(None, _usage("claude-cli", model, started))
    usage = _usage_from_mapping("claude-cli", model, outer.get("usage"), started, logger)
    if outer.get("is_error"):
        logger(f"  claude API error: {str(outer.get('result', ''))[:300]}")
        return ProviderResult(None, usage)
    return ProviderResult(_extract_json_object(outer.get("result", "")), usage)


@traced("distill.codex-cli")
def _call_codex_cli(prompt: str, model: Optional[str], logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not shutil.which("codex"):
        logger("  codex CLI not found")
        return ProviderResult(None, _zero_usage("codex-cli", model, started))
    cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--color", "never"]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        logger(f"  codex exec failed: {(result.stderr or result.stdout)[-300:]}")
        return ProviderResult(None, _usage("codex-cli", model, started))
    out = result.stdout
    usage = _usage_from_codex_stdout("codex-cli", model, out, started, logger)
    marker = out.rfind("tokens used")
    region = out[marker:] if marker != -1 else out[-8000:]
    return ProviderResult(_extract_json_object(region) or _extract_json_object(out), usage)


@traced("distill.gemini-cli")
def _call_gemini_cli(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not shutil.which("gemini"):
        logger("  gemini CLI not found")
        return ProviderResult(None, _zero_usage("gemini-cli", model, started))
    result = subprocess.run(["gemini", "-m", model, "-p", prompt], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        logger(f"  gemini exec failed: {result.stderr[:300]}")
        return ProviderResult(None, _usage("gemini-cli", model, started))
    return ProviderResult(_extract_json_object(result.stdout), _usage("gemini-cli", model, started))


@traced("distill.cursor-cli")
def _call_cursor_cli(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not shutil.which("cursor-agent"):
        logger("  cursor-agent CLI not found")
        return ProviderResult(None, _zero_usage("cursor-cli", model, started))
    cmd = [
        "cursor-agent", "--print",
        "--mode", "ask",
        "--output-format", "json",
        "--trust",
        "--model", model,
        prompt,
    ]
    if os.environ.get("CURSOR_API_KEY"):
        cmd[1:1] = ["--api-key", os.environ["CURSOR_API_KEY"]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        logger(f"  cursor-agent failed: {(result.stderr or result.stdout)[-300:]}")
        return ProviderResult(None, _usage("cursor-cli", model, started))
    inner: Any = result.stdout
    try:
        wrapper = json.loads(result.stdout)
        inner = wrapper.get("result") or wrapper.get("text") or wrapper.get("content") or ""
        if isinstance(inner, list):
            inner = "".join(b.get("text", "") for b in inner if isinstance(b, dict))
    except json.JSONDecodeError:
        pass
    return ProviderResult(_extract_json_object(inner if inner else result.stdout), _usage("cursor-cli", model, started))


@traced("distill.anthropic-api")
def _call_anthropic_api(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger("  ANTHROPIC_API_KEY not set")
        return ProviderResult(None, _zero_usage("anthropic-api", model, started))
    from langchain_anthropic import ChatAnthropic

    resp = ChatAnthropic(model=model, max_tokens=2048, temperature=0).invoke(prompt)
    return ProviderResult(
        _extract_json_object(_response_text(resp)),
        _usage_from_response("anthropic-api", model, resp, started, logger),
    )


@traced("distill.openai-api")
def _call_openai_api(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not os.environ.get("OPENAI_API_KEY"):
        logger("  OPENAI_API_KEY not set")
        return ProviderResult(None, _zero_usage("openai-api", model, started))
    from langchain_openai import ChatOpenAI

    resp = ChatOpenAI(model=model, max_tokens=2048, temperature=0).invoke(prompt)
    return ProviderResult(
        _extract_json_object(_response_text(resp)),
        _usage_from_response("openai-api", model, resp, started, logger),
    )


@traced("distill.gemini-api")
def _call_gemini_api(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not os.environ.get("GOOGLE_API_KEY"):
        logger("  GOOGLE_API_KEY not set")
        return ProviderResult(None, _zero_usage("gemini-api", model, started))
    from langchain_google_genai import ChatGoogleGenerativeAI

    resp = ChatGoogleGenerativeAI(model=model, temperature=0, max_output_tokens=2048).invoke(prompt)
    return ProviderResult(
        _extract_json_object(_response_text(resp)),
        _usage_from_response("gemini-api", model, resp, started, logger),
    )


@traced("distill.openrouter-api")
def _call_openrouter_api(prompt: str, model: str, logger: Logger) -> ProviderResult:
    started = time.perf_counter()
    if not os.environ.get("OPENROUTER_API_KEY"):
        logger("  OPENROUTER_API_KEY not set")
        return ProviderResult(None, _zero_usage("openrouter-api", model, started))
    from langchain_openai import ChatOpenAI

    resp = ChatOpenAI(
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        max_tokens=2048,
        temperature=0,
        default_headers={
            "HTTP-Referer": "https://github.com/internetyev/cross-agent-memory-kit",
            "X-Title": "mcp-memory-service-hook",
        },
    ).invoke(prompt)
    return ProviderResult(
        _extract_json_object(_response_text(resp)),
        _usage_from_response("openrouter-api", model, resp, started, logger),
    )


def _usage(
    provider: str,
    model: Optional[str],
    started: float,
    *,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cache_creation_input_tokens: Optional[int] = None,
    cache_read_input_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> DistillerUsage:
    if total_tokens is None:
        parts = [
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
        ]
        total_tokens = sum(part for part in parts if isinstance(part, int)) if any(part is not None for part in parts) else None
    return DistillerUsage(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        total_tokens=total_tokens,
        wall_seconds=round(time.perf_counter() - started, 3),
    )


def _zero_usage(provider: str, model: Optional[str], started: float) -> DistillerUsage:
    return _usage(
        provider,
        model,
        started,
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        total_tokens=0,
    )


def _usage_from_mapping(
    provider: str,
    model: Optional[str],
    raw_usage: Any,
    started: float,
    logger: Logger,
) -> DistillerUsage:
    if not isinstance(raw_usage, dict):
        if raw_usage is not None:
            logger(f"  usage parse warning: expected object, got {type(raw_usage).__name__}")
        else:
            logger("  usage parse warning: provider did not return usage")
        return _usage(provider, model, started)

    input_tokens = _first_int(raw_usage, "input_tokens", "prompt_tokens", "input")
    output_tokens = _first_int(raw_usage, "output_tokens", "completion_tokens", "output")
    cache_creation = _first_int(raw_usage, "cache_creation_input_tokens")
    cache_read = _first_int(raw_usage, "cache_read_input_tokens")
    total_tokens = _first_int(raw_usage, "total_tokens", "total")
    return _usage(
        provider,
        model,
        started,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
        total_tokens=total_tokens,
    )


def _usage_from_codex_stdout(
    provider: str,
    model: Optional[str],
    stdout: str,
    started: float,
    logger: Logger,
) -> DistillerUsage:
    marker = stdout.lower().rfind("tokens used")
    usage_region = stdout[marker:] if marker != -1 else stdout[-2000:]
    input_tokens = _regex_int(usage_region, r"\binput(?:[_ ]tokens?)?\b\s*[:=]\s*([\d,]+)")
    output_tokens = _regex_int(usage_region, r"\boutput(?:[_ ]tokens?)?\b\s*[:=]\s*([\d,]+)")
    total_tokens = _regex_int(usage_region, r"\btotal(?:[_ ]tokens?)?\b\s*[:=]\s*([\d,]+)")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        logger("  usage parse warning: could not find codex token counts")
    return _usage(
        provider,
        model,
        started,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _usage_from_response(
    provider: str,
    model: Optional[str],
    response: Any,
    started: float,
    logger: Logger,
) -> DistillerUsage:
    raw_usage = getattr(response, "usage_metadata", None)
    if isinstance(raw_usage, dict):
        return _usage_from_mapping(provider, model, raw_usage, started, logger)

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        for key in ("usage", "token_usage", "usage_metadata"):
            if isinstance(response_metadata.get(key), dict):
                return _usage_from_mapping(provider, model, response_metadata[key], started, logger)

    logger("  usage parse warning: response did not include usage metadata")
    return _usage(provider, model, started)


def _response_text(response: Any) -> str:
    content = getattr(response, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _first_int(data: dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return _coerce_int(value)
    return None


def _regex_int(text: str, pattern: str) -> Optional[int]:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _coerce_int(match.group(1))


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        return int(cleaned) if cleaned.isdigit() else None
    return None
