from app.agent.lazy_runtime import LazyAgentRuntime


class FakeRuntime:
    def run(self, request):
        return {"status": "completed", "prompt": request}


def test_lazy_runtime_does_not_construct_provider_until_first_run():
    created = []
    runtime = LazyAgentRuntime(lambda: created.append(True) or FakeRuntime())

    assert created == []
    assert runtime.loaded is False
    assert runtime.run("hello")["status"] == "completed"
    assert created == [True]
    assert runtime.loaded is True
