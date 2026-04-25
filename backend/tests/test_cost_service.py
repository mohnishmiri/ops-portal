import pytest

from app.services.cost_service import CostService


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeQueryResult:
    def __init__(self, *, columns: list[str], rows: list[list], next_link: str | None = None) -> None:
        self.columns = [_FakeColumn(name) for name in columns]
        self.rows = rows
        self.next_link = next_link


class _FakeQueryOperations:
    def __init__(self, results: list[_FakeQueryResult]) -> None:
        self._results = list(results)
        self.calls: list[dict] = []

    def usage(self, *, scope: str, parameters, **kwargs):
        self.calls.append({"scope": scope, "params": kwargs.get("params")})
        return self._results.pop(0)


class _FakeClient:
    def __init__(self, results: list[_FakeQueryResult]) -> None:
        self.query = _FakeQueryOperations(results)

    def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_execute_cost_query_collects_paginated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CostService()
    fake_client = _FakeClient(
        [
            _FakeQueryResult(
                columns=["Cost", "UsageDate", "ResourceGroup"],
                rows=[[10, 20260301, "rg-a"]],
                next_link="https://management.azure.com/providers/Microsoft.CostManagement/query?api-version=test&$skiptoken=abc",
            ),
            _FakeQueryResult(
                columns=["Cost", "UsageDate", "ResourceGroup"],
                rows=[[20, 20260302, "rg-b"], [30, 20260303, "rg-c"]],
                next_link=None,
            ),
        ]
    )

    def fake_get_client() -> _FakeClient:
        return fake_client

    monkeypatch.setattr(service, "_get_client", fake_get_client)

    col_names, rows = await service._execute_cost_query("/subscriptions/sub-1", {"type": "AmortizedCost"})

    assert col_names == ["Cost", "UsageDate", "ResourceGroup"]
    assert rows == [
        [10, 20260301, "rg-a"],
        [20, 20260302, "rg-b"],
        [30, 20260303, "rg-c"],
    ]
    assert fake_client.query.calls == [
        {"scope": "/subscriptions/sub-1", "params": None},
        {"scope": "/subscriptions/sub-1", "params": {"$skiptoken": "abc"}},
    ]
