import pytest

from mykhaya.recipe_import import RecipeImportError, _validate_url, normalise_recipe


def test_normalises_recipe_json_ld_and_how_to_steps() -> None:
    draft = normalise_recipe(
        {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": "Tomato pasta",
            "description": "A quick dinner",
            "image": [{"url": "/images/pasta.jpg"}],
            "prepTime": "PT10M",
            "cookTime": "PT20M",
            "recipeYield": "4 servings",
            "recipeCategory": "Dinner",
            "recipeIngredient": ["400 g pasta", "2 tomatoes"],
            "recipeInstructions": [
                {
                    "@type": "HowToSection",
                    "itemListElement": [{"@type": "HowToStep", "text": "Boil pasta."}],
                },
                {"@type": "HowToStep", "text": "Stir through sauce."},
            ],
        },
        "https://example.com/recipes/pasta",
    )
    assert draft is not None
    assert draft["name"] == "Tomato pasta"
    assert draft["image_url"] == "https://example.com/images/pasta.jpg"
    assert draft["prep_minutes"] == 10
    assert draft["cook_minutes"] == 20
    assert draft["servings"] == 4
    assert draft["ingredients"][0]["text"] == "400 g pasta"
    assert draft["instructions"] == "Boil pasta.\n\nStir through sauce."


def test_finds_recipe_inside_graph_and_supports_missing_optional_values() -> None:
    draft = normalise_recipe(
        {"@graph": [{"@type": "WebPage"}, {"@type": "Recipe", "name": "Soup"}]},
        "https://example.com/soup",
    )
    assert draft == {
        "name": "Soup",
        "description": None,
        "image_url": None,
        "meal_type": "other",
        "prep_minutes": None,
        "cook_minutes": None,
        "servings": None,
        "instructions": None,
        "source_url": "https://example.com/soup",
        "ingredients": [],
    }


def test_no_recipe_metadata_returns_none() -> None:
    assert normalise_recipe({"@type": "WebPage"}, "https://example.com") is None


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/recipe", "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.1/x"],
)
def test_rejects_unsafe_recipe_urls(url: str) -> None:
    with pytest.raises(RecipeImportError):
        _validate_url(url)
