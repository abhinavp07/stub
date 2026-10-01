from httpx import AsyncClient

from tests.conftest import ClientFactory, upload_receipt, use_sample


async def _categories(client: AsyncClient) -> dict[str, dict]:
    return {c["name"]: c for c in (await client.get("/api/categories")).json()}


async def test_new_users_get_default_categories(client: AsyncClient) -> None:
    cats = await _categories(client)
    assert set(cats) == {
        "Groceries", "Dining", "Transport", "Gas", "Shopping",
        "Entertainment", "Health", "Utilities", "Travel", "Other",
    }  # fmt: skip
    assert all(c["is_default"] and c["color"].startswith("#") for c in cats.values())


async def test_create_rename_recolor_delete(client: AsyncClient) -> None:
    resp = await client.post("/api/categories", json={"name": "  Pets ", "color": "#AABBCC"})
    assert resp.status_code == 201
    pets = resp.json()
    assert (pets["name"], pets["color"], pets["is_default"]) == ("Pets", "#aabbcc", False)

    resp = await client.patch(
        f"/api/categories/{pets['id']}", json={"name": "Pet care", "color": "#112233"}
    )
    assert resp.status_code == 200
    assert (resp.json()["name"], resp.json()["color"]) == ("Pet care", "#112233")

    assert (await client.delete(f"/api/categories/{pets['id']}")).status_code == 204
    assert "Pet care" not in await _categories(client)


async def test_duplicate_names_conflict_case_insensitively(client: AsyncClient) -> None:
    resp = await client.post("/api/categories", json={"name": "groceries"})
    assert resp.status_code == 409
    other = (await client.post("/api/categories", json={"name": "Pets"})).json()
    resp = await client.patch(f"/api/categories/{other['id']}", json={"name": "DINING"})
    assert resp.status_code == 409
    # Renaming to its own name (different case) is fine.
    resp = await client.patch(f"/api/categories/{other['id']}", json={"name": "PETS"})
    assert resp.status_code == 200


async def test_category_validation(client: AsyncClient) -> None:
    assert (await client.post("/api/categories", json={"name": ""})).status_code == 422
    bad_color = await client.post("/api/categories", json={"name": "X", "color": "red"})
    assert bad_color.status_code == 422


async def test_deleting_category_uncategorizes_receipts(client: AsyncClient) -> None:
    use_sample("grocery")
    receipt = await upload_receipt(client)
    groceries = (await _categories(client))["Groceries"]
    assert receipt["category_id"] == groceries["id"]
    assert (await _categories(client))["Groceries"]["receipt_count"] == 1

    await client.delete(f"/api/categories/{groceries['id']}")
    fresh = (await client.get(f"/api/receipts/{receipt['id']}")).json()
    assert fresh["category_id"] is None


async def test_other_users_categories_are_404(make_client: ClientFactory) -> None:
    owner = await make_client("owner@example.com")
    intruder = await make_client("intruder@example.com")
    cat = (await _categories(owner))["Dining"]
    url = f"/api/categories/{cat['id']}"

    assert (await intruder.patch(url, json={"name": "Hijacked"})).status_code == 404
    assert (await intruder.delete(url)).status_code == 404
    assert (await _categories(owner))["Dining"]["id"] == cat["id"]
    assert cat["id"] not in {c["id"] for c in (await _categories(intruder)).values()}

    # Nor can a receipt be filed under someone else's category.
    use_sample("grocery")
    receipt = await upload_receipt(intruder)
    resp = await intruder.patch(f"/api/receipts/{receipt['id']}", json={"category_id": cat["id"]})
    assert resp.status_code == 422


async def test_categories_require_auth(make_client: ClientFactory) -> None:
    anon = await make_client()
    assert (await anon.get("/api/categories")).status_code == 401
