import httpx

from screener.sources.prices import YahooPriceProvider


def test_japanese_exchange_suffix_survives_yahoo_symbol_normalization():
    paths = []

    def reply(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"chart": {"result": [{"meta": {}}]}})

    provider = YahooPriceProvider()
    provider.close()
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        provider._http = client
        assert provider._chart("6752.T", "1d", "1m") is not None
        assert provider._chart("BRK.B", "1d", "1m") is not None
    assert paths == ["/v8/finance/chart/6752.T", "/v8/finance/chart/BRK-B"]
