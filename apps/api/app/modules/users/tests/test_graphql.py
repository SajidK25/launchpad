import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.modules.users.graphql import build_router, validate_read_query


def test_graphql_schema_has_no_mutation_root() -> None:
    async def context_getter(request: Request) -> dict[str, object]:
        return {"member": None}

    app = FastAPI()
    app.include_router(build_router(context_getter), prefix="/api/v1")
    response = TestClient(app).post("/api/v1/graphql", json={"query": "mutation { updateProfile }"})

    assert response.status_code == 200
    assert response.json()["data"] is None
    assert response.json()["errors"]


@pytest.mark.parametrize(
    "query",
    [
        "mutation { viewerProfile { accountId } }",
        "query { __schema { queryType { name } } }",
        "query { otherProfile: publicProfile(accountId: "
        '"00000000-0000-0000-0000-000000000000") { accountId } }',
        "query { publicProfile(accountId: "
        '"00000000-0000-0000-0000-000000000000") { accountId } '
        'publicProfile(accountId: "00000000-0000-0000-0000-000000000000") '
        "{ accountId } }",
    ],
)
def test_graphql_read_validator_rejects_unapproved_operations(query: str) -> None:
    with pytest.raises(ValueError):
        validate_read_query(query)


def test_graphql_read_validator_rejects_get_style_deep_documents() -> None:
    query = (
        "query { viewerProfile { accountId displayName bio links photoUrl visibility version } }"
    )
    validate_read_query(query)
