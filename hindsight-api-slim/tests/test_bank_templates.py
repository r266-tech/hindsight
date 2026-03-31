"""Integration tests for bank template import/export endpoints."""

import pytest
import pytest_asyncio
import httpx
from datetime import datetime
from hindsight_api.api import create_app


@pytest_asyncio.fixture
async def api_client(memory):
    """Create an async test client for the FastAPI app."""
    app = create_app(memory, initialize_memory=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def bank_id():
    return f"template_test_{datetime.now().timestamp()}"


@pytest.fixture
def sample_template():
    return {
        "version": "1",
        "description": "Test template",
        "bank": {
            "reflect_mission": "Test mission for reflect",
            "retain_mission": "Extract test data carefully",
            "retain_extraction_mode": "verbose",
            "disposition_empathy": 5,
            "disposition_skepticism": 2,
            "enable_observations": True,
            "observations_mission": "Track test patterns",
        },
        "mental_models": [
            {
                "id": "test-model-one",
                "name": "Test Model One",
                "source_query": "What are the key patterns?",
                "tags": ["test"],
                "max_tokens": 1024,
                "trigger": {"refresh_after_consolidation": True},
            },
            {
                "id": "test-model-two",
                "name": "Test Model Two",
                "source_query": "What are the common issues?",
            },
        ],
    }


class TestImportValidation:
    """Test template manifest validation."""

    @pytest.mark.asyncio
    async def test_import_dry_run_valid(self, api_client, bank_id, sample_template):
        """dry_run=true with a valid manifest returns what would happen."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import?dry_run=true",
            json=sample_template,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["config_applied"] is True
        assert set(data["mental_models_created"]) == {"test-model-one", "test-model-two"}

    @pytest.mark.asyncio
    async def test_import_invalid_version(self, api_client, bank_id):
        """Reject manifest with unsupported version."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={"version": "999"},
        )
        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_import_invalid_extraction_mode(self, api_client, bank_id):
        """Semantic validation catches bad extraction mode."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "bank": {"retain_extraction_mode": "invalid_mode"},
            },
        )
        assert resp.status_code == 400
        assert "retain_extraction_mode" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_import_custom_instructions_without_custom_mode(self, api_client, bank_id):
        """Validate that custom_instructions requires extraction_mode=custom."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "bank": {
                    "retain_extraction_mode": "verbose",
                    "retain_custom_instructions": "some custom prompt",
                },
            },
        )
        assert resp.status_code == 400
        assert "retain_custom_instructions" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_import_duplicate_mental_model_ids(self, api_client, bank_id):
        """Reject manifest with duplicate mental model IDs."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {"id": "dup-id", "name": "First", "source_query": "q1"},
                    {"id": "dup-id", "name": "Second", "source_query": "q2"},
                ],
            },
        )
        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_import_missing_mental_model_id(self, api_client, bank_id):
        """Mental model without id is rejected."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {"name": "No ID Model", "source_query": "test query"},
                ],
            },
        )
        assert resp.status_code == 422  # Pydantic validation (id is required)

    @pytest.mark.asyncio
    async def test_import_invalid_mental_model_id_format(self, api_client, bank_id):
        """Mental model with invalid ID format is rejected."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {"id": "UPPERCASE-NOT-ALLOWED", "name": "Bad", "source_query": "q"},
                ],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_import_empty_manifest(self, api_client, bank_id):
        """Import with no bank or mental_models is valid (no-op)."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={"version": "1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["config_applied"] is False
        assert data["mental_models_created"] == []

    @pytest.mark.asyncio
    async def test_import_empty_mental_model_name(self, api_client, bank_id):
        """Semantic validation catches empty mental model name."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {"id": "test-mm", "name": "  ", "source_query": "q"},
                ],
            },
        )
        assert resp.status_code == 400
        assert "name" in resp.json()["detail"]


class TestImportApply:
    """Test that import actually applies config and creates mental models."""

    @pytest.mark.asyncio
    async def test_import_applies_config(self, api_client, bank_id):
        """Import with bank config applies config overrides."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "bank": {
                    "reflect_mission": "Imported mission",
                    "disposition_empathy": 4,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["config_applied"] is True
        assert data["dry_run"] is False

        # Verify config was actually applied
        config_resp = await api_client.get(f"/v1/default/banks/{bank_id}/config")
        assert config_resp.status_code == 200
        config = config_resp.json()
        assert config["overrides"]["reflect_mission"] == "Imported mission"
        assert config["overrides"]["disposition_empathy"] == 4

    @pytest.mark.asyncio
    async def test_import_creates_mental_models(self, api_client, bank_id):
        """Import creates mental models and returns operation IDs."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {
                        "id": "import-mm-1",
                        "name": "Imported Model",
                        "source_query": "What patterns exist?",
                        "tags": ["imported"],
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "import-mm-1" in data["mental_models_created"]
        assert len(data["operation_ids"]) == 1

        # Verify mental model exists
        mm_resp = await api_client.get(f"/v1/default/banks/{bank_id}/mental-models/import-mm-1")
        assert mm_resp.status_code == 200
        mm = mm_resp.json()
        assert mm["name"] == "Imported Model"
        assert mm["source_query"] == "What patterns exist?"
        assert mm["tags"] == ["imported"]

    @pytest.mark.asyncio
    async def test_import_updates_existing_mental_models(self, api_client, bank_id):
        """Re-importing updates existing mental models matched by ID."""
        # First import
        await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {
                        "id": "reusable-mm",
                        "name": "Original Name",
                        "source_query": "Original query",
                    },
                ],
            },
        )

        # Second import with same ID but different content
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {
                        "id": "reusable-mm",
                        "name": "Updated Name",
                        "source_query": "Updated query",
                    },
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reusable-mm" in data["mental_models_updated"]
        assert data["mental_models_created"] == []

        # Verify update
        mm_resp = await api_client.get(f"/v1/default/banks/{bank_id}/mental-models/reusable-mm")
        assert mm_resp.status_code == 200
        mm = mm_resp.json()
        assert mm["name"] == "Updated Name"
        assert mm["source_query"] == "Updated query"

    @pytest.mark.asyncio
    async def test_import_config_only(self, api_client, bank_id):
        """Import with only bank config (no mental_models) works."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "bank": {"retain_extraction_mode": "verbose"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["config_applied"] is True
        assert data["mental_models_created"] == []
        assert data["operation_ids"] == []

    @pytest.mark.asyncio
    async def test_import_mental_models_only(self, api_client, bank_id):
        """Import with only mental_models (no bank config) works."""
        resp = await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "mental_models": [
                    {"id": "mm-only", "name": "MM Only", "source_query": "test"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["config_applied"] is False
        assert "mm-only" in data["mental_models_created"]


class TestExport:
    """Test bank template export."""

    @pytest.mark.asyncio
    async def test_export_empty_bank(self, api_client, bank_id):
        """Export a bank with no overrides returns minimal manifest."""
        # Create bank
        await api_client.put(f"/v1/default/banks/{bank_id}", json={})

        resp = await api_client.get(f"/v1/default/banks/{bank_id}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1"
        assert data["bank"] is None
        assert data["mental_models"] is None

    @pytest.mark.asyncio
    async def test_export_after_import(self, api_client, bank_id):
        """Export after import returns the imported config and mental models."""
        template = {
            "version": "1",
            "bank": {
                "reflect_mission": "Roundtrip mission",
                "disposition_empathy": 3,
            },
            "mental_models": [
                {
                    "id": "roundtrip-mm",
                    "name": "Roundtrip Model",
                    "source_query": "What happened?",
                    "tags": ["roundtrip"],
                    "max_tokens": 512,
                },
            ],
        }

        # Import
        import_resp = await api_client.post(f"/v1/default/banks/{bank_id}/import", json=template)
        assert import_resp.status_code == 200

        # Export
        resp = await api_client.get(f"/v1/default/banks/{bank_id}/export")
        assert resp.status_code == 200
        data = resp.json()

        assert data["version"] == "1"
        assert data["bank"]["reflect_mission"] == "Roundtrip mission"
        assert data["bank"]["disposition_empathy"] == 3

        assert len(data["mental_models"]) == 1
        mm = data["mental_models"][0]
        assert mm["id"] == "roundtrip-mm"
        assert mm["name"] == "Roundtrip Model"
        assert mm["source_query"] == "What happened?"
        assert mm["tags"] == ["roundtrip"]
        assert mm["max_tokens"] == 512

    @pytest.mark.asyncio
    async def test_export_reimport_roundtrip(self, api_client, bank_id):
        """Exported manifest can be re-imported into a new bank."""
        # Set up source bank
        await api_client.post(
            f"/v1/default/banks/{bank_id}/import",
            json={
                "version": "1",
                "bank": {"retain_mission": "Roundtrip test"},
                "mental_models": [
                    {"id": "rt-mm", "name": "RT Model", "source_query": "test query"},
                ],
            },
        )

        # Export
        export_resp = await api_client.get(f"/v1/default/banks/{bank_id}/export")
        assert export_resp.status_code == 200
        exported = export_resp.json()

        # Import into a new bank
        new_bank_id = f"{bank_id}_clone"
        import_resp = await api_client.post(
            f"/v1/default/banks/{new_bank_id}/import",
            json=exported,
        )
        assert import_resp.status_code == 200
        data = import_resp.json()
        assert data["config_applied"] is True
        assert "rt-mm" in data["mental_models_created"]

    @pytest.mark.asyncio
    async def test_export_nonexistent_bank(self, api_client):
        """Export from a nonexistent bank returns the bank with defaults (auto-created)."""
        resp = await api_client.get("/v1/default/banks/nonexistent-export-test/export")
        # get_bank_profile auto-creates, so this returns a valid empty manifest
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1"
