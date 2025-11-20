from __future__ import annotations

import json
import os
import re
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .util import BenchError


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    kind: str
    base_url: str | None
    configured: bool
    paid: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class BudgetCheck:
    """A transparent local preflight budget calculation for one Harbor job."""

    planned_input_tokens: int | None
    planned_output_tokens: int | None
    estimated_usd: float | None


PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "paid": True,
        "description": "OpenAI API (ChatGPT API credits, not a consumer subscription)",
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
        "paid": True,
        "description": "Anthropic Claude API (API credits, not a Claude subscription)",
    },
    "openrouter": {
        "kind": "openai-compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "paid": True,
        "description": "OpenRouter routed OpenAI-compatible models",
    },
    "custom": {
        "kind": "openai-compatible",
        "base_url_env": "CUSTOM_OPENAI_BASE_URL",
        "api_key_env": "CUSTOM_OPENAI_API_KEY",
        "paid": True,
        "description": "Any OpenAI-compatible endpoint (vLLM, LM Studio, private gateway)",
    },
    "ollama": {
        "kind": "openai-compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "base_url_env": "OLLAMA_BASE_URL",
        "api_key_env": "",
        "paid": False,
        "description": "Local Ollama OpenAI-compatible endpoint",
    },
}


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader: only fills variables absent from the process environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def load_provider_config(root: Path, config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    _load_dotenv(root / ".env")
    selected = config_path or Path(os.environ.get("MFG_BENCH_PROVIDER_CONFIG", ""))
    if not selected or str(selected) == ".":
        candidate = root / "configs" / "providers.local.toml"
        selected = candidate if candidate.is_file() else root / "configs" / "providers.example.toml"
    if not selected.is_absolute():
        selected = root / selected
    if not selected.is_file():
        raise BenchError(f"Provider configuration does not exist: {selected}")
    try:
        raw = tomllib.loads(selected.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise BenchError(f"Invalid provider configuration: {exc}") from exc
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        raise BenchError("Provider configuration needs a [providers.<name>] table.")
    return {str(name): dict(value) for name, value in providers.items() if isinstance(value, dict)}


def _env(value: Any) -> str | None:
    return os.environ.get(str(value), "").strip() or None if value else None


def provider_statuses(root: Path, config_path: Path | None = None) -> list[ProviderStatus]:
    providers = load_provider_config(root, config_path)
    statuses: list[ProviderStatus] = []
    for name, config in sorted(providers.items()):
        diagnostics: list[str] = []
        # An environment URL intentionally overrides an example-config fallback,
        # allowing a local Ollama/vLLM endpoint to move without committing a host URL.
        base_url = (
            _env(config.get("base_url_env")) or str(config.get("base_url", "")).strip() or None
        )
        key_env = str(config.get("api_key_env", "")).strip()
        key = _env(key_env)
        if not base_url:
            diagnostics.append("base URL is not configured")
        if key_env and not key:
            diagnostics.append(f"environment variable {key_env} is unset")
        if not key_env:
            diagnostics.append("no API key is required by this configuration")
        statuses.append(
            ProviderStatus(
                name=name,
                kind=str(config.get("kind", "unknown")),
                base_url=base_url,
                configured=bool(base_url) and (bool(key) or not key_env),
                paid=bool(config.get("paid", False)),
                diagnostics=tuple(diagnostics),
            )
        )
    return statuses


def test_connection(
    root: Path, provider_name: str, config_path: Path | None = None
) -> dict[str, Any]:
    """Perform an explicit, non-generative endpoint reachability/authentication check.

    OpenAI-compatible providers use the documented GET /models endpoint. Other
    providers receive an inexpensive GET to their configured base URL; a 4xx
    response still proves DNS/TLS/endpoint reachability and is reported without
    treating it as successful authentication.
    """
    config = load_provider_config(root, config_path)
    if provider_name not in config:
        raise BenchError(f"Unknown provider: {provider_name}")
    selected = next(
        item for item in provider_statuses(root, config_path) if item.name == provider_name
    )
    if not selected.configured:
        raise BenchError(
            f"Provider {provider_name} is not configured: {'; '.join(selected.diagnostics)}"
        )
    base_url = selected.base_url
    if base_url is None:
        raise BenchError(f"Provider {provider_name} has no configured base URL.")
    endpoint = base_url.rstrip("/")
    if selected.kind in {"openai", "openai-compatible"}:
        endpoint += "/models"
    headers = {"Accept": "application/json"}
    key_name = str(config[provider_name].get("api_key_env", ""))
    if key_name:
        headers["Authorization"] = f"Bearer {os.environ[key_name]}"
    request = urllib.request.Request(endpoint, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310: explicit opt-in CLI
            return {
                "provider": provider_name,
                "endpoint": endpoint,
                "reachable": True,
                "http_status": response.status,
            }
    except urllib.error.HTTPError as exc:
        # HTTP response confirms transport reachability but exposes an authentication/path diagnostic.
        return {
            "provider": provider_name,
            "endpoint": endpoint,
            "reachable": True,
            "http_status": exc.code,
            "authenticated": False if exc.code in {401, 403} else None,
            "diagnostic": "Endpoint responded with HTTP error; no generation request was sent.",
        }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "provider": provider_name,
            "endpoint": endpoint,
            "reachable": False,
            "diagnostic": str(exc),
        }


def discover_models(root: Path, provider_name: str, config_path: Path | None = None) -> list[str]:
    config = load_provider_config(root, config_path)
    if provider_name not in config:
        raise BenchError(f"Unknown provider: {provider_name}")
    selected = next(
        item for item in provider_statuses(root, config_path) if item.name == provider_name
    )
    if not selected.configured:
        raise BenchError(
            f"Provider {provider_name} is not configured: {'; '.join(selected.diagnostics)}"
        )
    if selected.kind not in {"openai", "openai-compatible"}:
        raise BenchError(
            f"Automatic model discovery is not implemented for {selected.kind}; set default_model explicitly."
        )
    base_url = selected.base_url
    if base_url is None:
        raise BenchError(f"Provider {provider_name} has no configured base URL.")
    key_name = str(config[provider_name].get("api_key_env", ""))
    headers = {"Accept": "application/json"}
    if key_name:
        headers["Authorization"] = f"Bearer {os.environ[key_name]}"
    request = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310: explicit opt-in CLI
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise BenchError(f"Model discovery failed for {provider_name}: {exc}") from exc
    data = payload.get("data", []) if isinstance(payload, dict) else []
    return sorted(str(item["id"]) for item in data if isinstance(item, dict) and item.get("id"))


def write_provider_config(
    root: Path,
    *,
    name: str,
    preset: str | None = None,
    base_url: str | None = None,
    base_url_env: str | None = None,
    api_key_env: str | None = None,
    model: str | None = None,
    paid: bool | None = None,
    input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
    pricing_as_of: str | None = None,
) -> Path:
    """Write a safe local provider entry; secrets are referenced, never stored.

    The destination is ``configs/providers.local.toml`` which is git-ignored. This
    gives an easy-connect path for ChatGPT, Claude, OpenRouter, custom compatible
    endpoints and Ollama without asking operators to hand-edit TOML.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise BenchError("Provider name may contain only letters, digits, '_' and '-'.")
    values: dict[str, Any] = dict(PROVIDER_PRESETS.get(preset or name, {}))
    values.pop("description", None)
    if base_url is not None:
        values["base_url"] = base_url
    if base_url_env is not None:
        values["base_url_env"] = base_url_env
    if api_key_env is not None:
        values["api_key_env"] = api_key_env
    if model is not None:
        values["default_model"] = model
    if paid is not None:
        values["paid"] = paid
    if any(
        value is not None
        for value in (input_usd_per_million, output_usd_per_million, pricing_as_of)
    ):
        if input_usd_per_million is None or output_usd_per_million is None or not pricing_as_of:
            raise BenchError(
                "Dated pricing needs input_usd_per_million, output_usd_per_million "
                "and pricing_as_of together."
            )
        try:
            date.fromisoformat(pricing_as_of)
        except ValueError as exc:
            raise BenchError("pricing_as_of must be an ISO calendar date (YYYY-MM-DD).") from exc
        values["input_usd_per_million"] = input_usd_per_million
        values["output_usd_per_million"] = output_usd_per_million
        values["pricing_as_of"] = pricing_as_of
    if not values:
        raise BenchError(f"Unknown preset {preset!r}; pass explicit provider fields.")
    target = root / "configs" / "providers.local.toml"
    existing: dict[str, dict[str, Any]] = {}
    if target.is_file():
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
        existing = {
            str(key): dict(value)
            for key, value in raw.get("providers", {}).items()
            if isinstance(value, dict)
        }
    existing[name] = values
    lines = [
        "# Generated by `mfgbench providers add`. Git-ignored; secrets stay in environment variables.",
        "",
    ]
    for provider_name, config in sorted(existing.items()):
        lines.append(f"[providers.{provider_name}]")
        for key, value in config.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            else:
                lines.append(f"{key} = {json.dumps(str(value))}")
        lines.append("")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def estimate_cost(config: dict[str, Any], *, input_tokens: int, output_tokens: int) -> float:
    """Estimate only when the caller configured explicit, dated unit rates."""
    try:
        input_rate = float(config["input_usd_per_million"])
        output_rate = float(config["output_usd_per_million"])
        pricing_as_of = str(config["pricing_as_of"]).strip()
        date.fromisoformat(pricing_as_of)
    except (KeyError, TypeError, ValueError) as exc:
        raise BenchError(
            "No reliable dated cost rate configured. Add input_usd_per_million, "
            "output_usd_per_million, and ISO pricing_as_of to the selected local provider config."
        ) from exc
    if input_tokens < 0 or output_tokens < 0 or input_rate < 0 or output_rate < 0:
        raise BenchError("Token counts and configured price rates must be non-negative.")
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def check_budget(
    config: dict[str, Any],
    *,
    planned_input_tokens: int | None,
    planned_output_tokens: int | None,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
    max_estimated_usd: float | None,
) -> BudgetCheck:
    """Validate an explicit external-evaluation budget before Harbor is launched.

    The planned token values are job-wide estimates supplied by the operator. This
    check refuses an execution whose declared plan exceeds a requested cap; it
    cannot manufacture reliable prices or impose a universal provider-side token
    limit on agents that do not expose one. Agent-specific runtime limits are
    handled separately by the Harbor wrapper.
    """
    values = {
        "planned_input_tokens": planned_input_tokens,
        "planned_output_tokens": planned_output_tokens,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
    }
    for name, value in values.items():
        if value is not None and value < 0:
            raise BenchError(f"{name} must be non-negative.")
    if max_estimated_usd is not None and max_estimated_usd < 0:
        raise BenchError("max_estimated_usd must be non-negative.")

    if max_input_tokens is not None:
        if planned_input_tokens is None:
            raise BenchError("--max-input-tokens requires --planned-input-tokens.")
        if planned_input_tokens > max_input_tokens:
            raise BenchError(
                f"Planned input tokens ({planned_input_tokens}) exceed the cap ({max_input_tokens})."
            )
    if max_output_tokens is not None:
        if planned_output_tokens is None:
            raise BenchError("--max-output-tokens requires --planned-output-tokens.")
        if planned_output_tokens > max_output_tokens:
            raise BenchError(
                f"Planned output tokens ({planned_output_tokens}) exceed the cap ({max_output_tokens})."
            )

    estimated_usd: float | None = None
    if max_estimated_usd is not None:
        if planned_input_tokens is None or planned_output_tokens is None:
            raise BenchError(
                "--max-estimated-usd requires both --planned-input-tokens and --planned-output-tokens."
            )
        estimated_usd = estimate_cost(
            config, input_tokens=planned_input_tokens, output_tokens=planned_output_tokens
        )
        if estimated_usd > max_estimated_usd:
            raise BenchError(
                f"Estimated job cost ${estimated_usd:.6f} exceeds the cap ${max_estimated_usd:.6f}."
            )
    return BudgetCheck(
        planned_input_tokens=planned_input_tokens,
        planned_output_tokens=planned_output_tokens,
        estimated_usd=estimated_usd,
    )
