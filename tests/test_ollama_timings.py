from studio_core.ollama import Timings


def test_timings_convert_nanoseconds_to_rates() -> None:
    t = Timings.from_response(
        {
            "load_duration": 2_000_000_000,
            "prompt_eval_count": 500,
            "prompt_eval_duration": 1_000_000_000,
            "eval_count": 100,
            "eval_duration": 4_000_000_000,
            "total_duration": 7_000_000_000,
        }
    )
    assert t.load_s == 2.0
    assert t.prompt_tps == 500.0
    assert t.gen_tps == 25.0
    assert t.total_s == 7.0


def test_timings_tolerate_missing_fields() -> None:
    t = Timings.from_response({})
    assert t.prompt_tps == 0.0 and t.gen_tps == 0.0
