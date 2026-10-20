from check_tool_calling import validate_call


def call(name: str, args: object) -> dict:
    return {"tool_calls": [{"function": {"name": name, "arguments": args}}]}


def test_accepts_valid_call_with_object_or_json_string_args() -> None:
    assert validate_call(call("get_weather", {"city": "Lisbon"}))[0]
    assert validate_call(call("get_weather", '{"city": "Lisbon, PT", "unit": "celsius"}'))[0]


def test_rejects_wrong_name_bad_args_and_no_call() -> None:
    assert not validate_call(call("get_time", {"city": "Lisbon"}))[0]
    assert not validate_call(call("get_weather", {"town": "Lisbon"}))[0]
    assert not validate_call(call("get_weather", {"city": "Lisbon", "unit": "kelvin"}))[0]
    assert not validate_call(call("get_weather", "not json"))[0]
    assert not validate_call({"content": "It is sunny."})[0]
