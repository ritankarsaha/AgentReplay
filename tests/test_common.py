from agentreplay.patching import common


def test_build_request_payload_excludes_transport_fields():
    kwargs = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "timeout": 30,
        "extra_headers": {"X-Foo": "bar"},
        "extra_query": {"q": "1"},
        "extra_body": {"b": "2"},
    }

    payload = common.build_request_payload(kwargs)

    assert payload == {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


def test_build_response_payload_streaming_placeholder():
    assert common.build_response_payload(object(), streaming=True) == {"streaming": True}


def test_build_response_payload_uses_model_dump():
    class Resp:
        def model_dump(self):
            return {"id": "abc"}

    assert common.build_response_payload(Resp(), streaming=False) == {"id": "abc"}


def test_build_response_payload_dict_passthrough():
    assert common.build_response_payload({"id": "abc"}, streaming=False) == {"id": "abc"}


def test_build_response_payload_fallback_to_str():
    assert common.build_response_payload(42, streaming=False) == {"value": "42"}


def test_build_error_payload():
    err = ValueError("bad input")
    assert common.build_error_payload(err) == {"type": "ValueError", "message": "bad input"}
