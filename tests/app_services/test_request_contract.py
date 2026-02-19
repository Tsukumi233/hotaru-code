import pytest

from hotaru.app_services.provider_service import ProviderService
from hotaru.app_services.session_service import SessionService


@pytest.mark.anyio
async def test_session_service_create_rejects_legacy_project_id_field() -> None:
    with pytest.raises(ValueError, match="projectID"):
        await SessionService.create({"projectID": "proj_legacy"}, cwd=".")


@pytest.mark.anyio
async def test_session_service_delete_messages_rejects_legacy_message_ids_field() -> None:
    with pytest.raises(ValueError, match="messageIDs"):
        await SessionService.delete_messages("session_1", {"messageIDs": ["m1", "m2"]})


@pytest.mark.anyio
async def test_provider_service_connect_rejects_legacy_provider_fields() -> None:
    with pytest.raises(ValueError, match="providerID"):
        await ProviderService.connect(
            {
                "providerID": "openai",
                "apiKey": "sk-test",
                "config": {"type": "openai", "models": {}},
            }
        )
