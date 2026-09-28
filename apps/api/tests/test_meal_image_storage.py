"""Meal photo persistence and optional-photo recipe import failures."""

import errno
import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from mykhaya.config import Settings
from mykhaya.routers import meal_plans
from mykhaya.schemas import RecipeImportRequest


@pytest.fixture
def import_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    draft = {
        "name": "Chicken kebabs",
        "description": None,
        "source_url": "https://example.com/recipes/kebabs",
        "image_url": "https://example.com/kebabs.jpg",
        "meal_type": "dinner",
        "prep_minutes": None,
        "cook_minutes": None,
        "servings": None,
        "instructions": "Roast the vegetables.",
        "ingredients": [{"text": "2 tomatoes"}],
    }
    output = io.BytesIO()
    Image.new("RGB", (12, 12), "green").save(output, "JPEG")
    monkeypatch.setattr(meal_plans, "require_capability", AsyncMock())
    monkeypatch.setattr(meal_plans, "require_entitlement", AsyncMock())
    monkeypatch.setattr(meal_plans, "import_recipe", AsyncMock(return_value=draft))
    monkeypatch.setattr(
        meal_plans, "download_recipe_image", AsyncMock(return_value=output.getvalue())
    )
    return Settings(meal_image_storage_dir=str(tmp_path / "meal-images"))


async def test_import_saves_processed_photo(import_dependencies: Settings) -> None:
    home_id = uuid.uuid4()
    result = await meal_plans.import_recipe_draft(
        home_id, RecipeImportRequest(url="https://example.com/recipes/kebabs"),
        auth=Mock(), db=AsyncMock(), settings=import_dependencies,
    )
    assert result.image_url is not None
    assert result.image_url.startswith(f"/api/v1/homes/{home_id}/meals/images/")
    saved = Path(import_dependencies.meal_image_storage_dir) / result.image_url.rsplit("/", 1)[1]
    with Image.open(saved) as image:
        assert image.format == "WEBP"
    assert result.name == "Chicken kebabs"


@pytest.mark.parametrize("failure_stage", ["directory", "write"])
async def test_image_storage_failure_preserves_recipe_text(
    import_dependencies: Settings, monkeypatch: pytest.MonkeyPatch, failure_stage: str,
) -> None:
    failure = OSError(errno.EROFS, "Read-only file system")
    storage = Mock()
    storage.save = AsyncMock(side_effect=failure)
    factory = (
        Mock(side_effect=failure)
        if failure_stage == "directory"
        else Mock(return_value=storage)
    )
    monkeypatch.setattr(meal_plans, "get_meal_image_storage", factory)
    log = Mock()
    monkeypatch.setattr(meal_plans, "log", log)
    result = await meal_plans.import_recipe_draft(
        uuid.uuid4(), RecipeImportRequest(url="https://example.com/recipes/kebabs"),
        auth=Mock(), db=AsyncMock(), settings=import_dependencies,
    )
    assert result.image_url is None
    assert result.name == "Chicken kebabs"
    assert result.instructions == "Roast the vegetables."
    assert result.source_url == "https://example.com/recipes/kebabs"
    assert result.ingredients[0].text == "2 tomatoes"
    log.warning.assert_called_once_with("recipe_import_image_storage_failed", errno=errno.EROFS)


def test_meal_volume_matches_existing_non_root_read_only_deployment() -> None:
    root = Path(__file__).resolve().parents[3]
    if not (root / "compose.yml").exists():
        pytest.skip("Deployment files are not copied into the API test image")
    compose = (root / "compose.yml").read_text(encoding="utf-8")
    dockerfile = (root / "apps/api/Dockerfile").read_text(encoding="utf-8")
    assert "meal_image_data:/data/meal-images" in compose
    assert "  meal_image_data: {}" in compose
    api_service = compose.split("  api: &api", 1)[1].split("  worker:", 1)[0]
    assert "read_only: true" in api_service
    for command in ["RUN mkdir -p", "&& chown mykhaya:mykhaya"]:
        line = next(line for line in dockerfile.splitlines() if command in line)
        assert "/data/meal-images" in line
    assert "USER 10001:10001" in dockerfile
