import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.engine import execute


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        assert (
            c.post(
                "/api/auth/local-session", headers={"Origin": "http://testserver"}
            ).status_code
            == 200
        )
        yield c


@pytest.mark.parametrize(
    "columns", [["bad-column"], [{}], [{"name": ""}], [{"name": "id"}, {"name": "id"}]]
)
def test_metadata_bad_columns_are_rejected_without_losing_saved_structure(
    client, columns
):
    original = {
        "name": "元数据验收",
        "datasetId": "demo-dataset",
        "columns": [{"name": "id", "type": "integer"}],
    }
    saved = client.post("/api/governance/tables", json=original).json()["data"]
    response = client.put(
        "/api/governance/tables/" + saved["id"], json={"columns": columns}
    )
    assert response.status_code == 422
    assert response.json()["success"] is False
    assert (
        client.get("/api/governance/tables/" + saved["id"]).json()["data"]["columns"]
        == original["columns"]
    )


@pytest.mark.parametrize(
    "items",
    [
        ["bad-item"],
        [{}],
        [{"code": "", "name": "空码"}],
        [{"code": "A", "name": ""}],
        [{"code": "A", "name": "甲"}, {"code": "A", "name": "乙"}],
    ],
)
def test_dictionary_invalid_items_are_rejected(client, items):
    response = client.post(
        "/api/governance/dictionaries",
        json={"name": "代码集验收", "dictionaryDetails": items},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "operation,values,extra,expected",
    [
        ("trim", [" A ", "B"], {}, ["A", "B"]),
        ("upper", ["a", "b"], {}, ["A", "B"]),
        ("lower", ["A", "B"], {}, ["a", "b"]),
        ("number", ["12.5", "bad", "", None], {}, [12.5, None, None, None]),
        ("fill", ["", None, "OK"], {"value": "Unknown"}, ["Unknown", "Unknown", "OK"]),
    ],
)
def test_cleaning_modes_have_expected_semantics(operation, values, extra, expected):
    payload = pipeline(
        [{"v": v} for v in values],
        "clean",
        {"fields": ["v"], "operation": operation, **extra},
    )
    assert [r["v"] for r in execute(payload)["rows"]] == expected


@pytest.mark.parametrize(
    "operator,value,expected",
    [
        ("eq", "2", [2]),
        ("ne", "2", [1, None, "", "Alpha", "Alphabeta"]),
        ("contains", "Alpha", ["Alpha", "Alphabeta"]),
        ("notEmpty", "", [1, 2, "Alpha", "Alphabeta"]),
        ("gt", "1", [2]),
        ("lt", "2", [1]),
    ],
)
def test_filter_modes_have_expected_semantics(operator, value, expected):
    rows = [{"v": v} for v in [1, 2, None, "", "Alpha", "Alphabeta"]]
    payload = pipeline(
        rows, "filter", {"field": "v", "operator": operator, "value": value}
    )
    assert [r["v"] for r in execute(payload)["rows"]] == expected


def pipeline(rows, kind, config):
    return {
        "datasets": {"test": {"rows": rows}},
        "rules": {},
        "workflow": {
            "nodes": [
                {"id": "a", "type": "source", "config": {"datasetId": "test"}},
                {"id": "b", "type": kind, "config": config},
                {"id": "c", "type": "output", "config": {}},
            ],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
        },
    }


def test_account_names_reject_blank_and_normalize_surrounding_spaces(client):
    assert (
        client.post(
            "/api/auth/users",
            json={"name": "   ", "password": "acceptance-reader", "role": "reader"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/users",
            json={"name": " admin ", "password": "acceptance-reader", "role": "reader"},
        ).status_code
        == 409
    )
    created = client.post(
        "/api/auth/users",
        json={"name": " reader ", "password": "acceptance-reader", "role": "reader"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["name"] == "reader"
    assert client.post("/api/auth/logout").status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            json={"name": " reader ", "password": "acceptance-reader"},
        ).status_code
        == 200
    )
