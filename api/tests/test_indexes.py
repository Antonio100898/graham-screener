"""Index source transport invariants."""

from screener.sources import indexes


def test_wikimedia_request_identifies_the_client(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"parse": {"text": "constituents"}}

    def get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(indexes.httpx, "get", get)

    assert indexes._page("Example") == "constituents"
    assert seen["headers"]["User-Agent"] == indexes.WIKIMEDIA_USER_AGENT
    assert "contact via repo" not in seen["headers"]["User-Agent"]
