"""Provider presets, validation, and onboarding flow.

Extracted from app.py to keep the main TUI module focused.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

_PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


@dataclass(frozen=True)
class ProviderPreset:
    preset_id: str
    provider_type: str
    provider_id: str
    provider_name: str
    base_url: str
    default_models: str


PROVIDER_PRESETS: Dict[str, ProviderPreset] = {
    "moonshot": ProviderPreset(
        preset_id="moonshot",
        provider_type="openai",
        provider_id="moonshot",
        provider_name="Moonshot",
        base_url="https://api.moonshot.cn/v1",
        default_models="kimi-k2.5",
    ),
}


def validate_provider_id(value: str) -> str:
    provider_id = value.strip().lower()
    if not provider_id:
        raise ValueError("Provider ID cannot be empty.")
    if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("Provider ID must match [a-z0-9][a-z0-9_-]*.")
    return provider_id


def validate_base_url(value: str) -> str:
    base_url = value.strip()
    if not base_url:
        raise ValueError("Base URL cannot be empty.")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be a valid http(s) URL.")
    return base_url


def parse_model_ids(value: str) -> List[str]:
    model_ids: List[str] = []
    seen = set()

    for item in value.split(","):
        model_id = item.strip()
        if not model_id:
            continue
        if any(char.isspace() for char in model_id):
            raise ValueError(f"Model ID '{model_id}' cannot contain whitespace.")
        if model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)

    if not model_ids:
        raise ValueError("Please provide at least one model ID.")
    return model_ids


def resolve_preset(preset_id: str) -> Optional[ProviderPreset]:
    return PROVIDER_PRESETS.get(str(preset_id or "").strip().lower())


async def provider_connect_flow(app) -> None:
    """Run the interactive provider onboarding wizard.

    Args:
        app: TuiApp instance driving the dialog screens.
    """
    from .dialogs import InputDialog, SelectDialog

    preset_choice = await app.push_screen_wait(
        SelectDialog(
            title="Provider preset",
            options=[
                ("Moonshot (Kimi)", "moonshot"),
                ("Custom provider", "custom"),
            ],
        )
    )
    if preset_choice is None:
        return

    preset = resolve_preset(str(preset_choice))
    using_preset = preset is not None

    if preset:
        provider_type = preset.provider_type
        provider_id = preset.provider_id
        provider_name = preset.provider_name
        base_url = preset.base_url
        default_models = preset.default_models
    else:
        provider_type = await app.push_screen_wait(
            SelectDialog(
                title="Provider protocol",
                options=[
                    ("OpenAI-compatible API", "openai"),
                    ("Anthropic-compatible API", "anthropic"),
                ],
            )
        )
        if provider_type is None:
            return

        provider_id_raw = await app.push_screen_wait(
            InputDialog(
                title="Provider ID",
                placeholder="my-provider",
                submit_label="Next",
            )
        )
        if provider_id_raw is None:
            return
        try:
            provider_id = validate_provider_id(str(provider_id_raw))
        except ValueError as exc:
            app.notify(str(exc), severity="error")
            return

        provider_name_raw = await app.push_screen_wait(
            InputDialog(
                title="Provider display name",
                placeholder="Optional (defaults to provider ID)",
                default_value=provider_id,
                submit_label="Next",
            )
        )
        if provider_name_raw is None:
            return
        provider_name = provider_name_raw.strip() or provider_id

        base_url_raw = await app.push_screen_wait(
            InputDialog(
                title="Base URL",
                placeholder="https://api.example.com/v1",
                submit_label="Next",
            )
        )
        if base_url_raw is None:
            return
        try:
            base_url = validate_base_url(str(base_url_raw))
        except ValueError as exc:
            app.notify(str(exc), severity="error")
            return
        default_models = ""

    try:
        provider_id = validate_provider_id(provider_id)
        base_url = validate_base_url(base_url)
    except ValueError as exc:
        app.notify(str(exc), severity="error")
        return

    api_key = await app.push_screen_wait(
        InputDialog(
            title="API key",
            placeholder="sk-...",
            submit_label="Next",
            password=True,
        )
    )
    if api_key is None:
        return
    api_key = api_key.strip()
    if not api_key:
        app.notify("API key cannot be empty.", severity="error")
        return

    model_value = await app.push_screen_wait(
        InputDialog(
            title="Model IDs",
            placeholder="gpt-4o-mini, claude-sonnet-4-5",
            default_value=default_models,
            submit_label="Connect",
        )
    )
    if model_value is None:
        return

    try:
        model_ids = parse_model_ids(str(model_value))
    except ValueError as exc:
        app.notify(str(exc), severity="error")
        return

    try:
        await app.sdk_ctx.connect_provider(
            provider_id=provider_id,
            provider_type=str(provider_type),
            provider_name=provider_name,
            base_url=base_url,
            api_key=api_key,
            model_ids=model_ids,
        )
        await app._sync_providers()
    except Exception as exc:
        app.notify(f"Failed to connect provider: {exc}", severity="error")
        return

    if using_preset:
        app.notify(f"Connected provider '{provider_id}' via preset.")
    else:
        app.notify(f"Connected provider '{provider_id}'.")
    app.action_model_list(provider_filter=provider_id)
