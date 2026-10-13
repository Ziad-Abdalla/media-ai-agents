from types import SimpleNamespace

import pytest


class FakeClient:
    """Stands in for anthropic.Anthropic. Returns canned responses, costs nothing."""

    def __init__(self, input_tokens=1000, output_tokens=200, cache_write=0, cache_read=None):
        self.calls = 0
        self.usage = SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,  # the API can send None
        )
        self.messages = self  # so client.messages.create works

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(model=kwargs["model"], usage=self.usage,
                               stop_reason="end_turn", content=[])


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "costs.sqlite")
    monkeypatch.setenv("COST_DB_PATH", path)
    monkeypatch.setenv("COST_BUDGET_USD", "15")
    return path
