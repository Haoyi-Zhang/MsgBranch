from msgbranch.localhero_core import run_component


def check(source, target):
    return run_component([{"meta": {"case": "x"}, "source": source, "target": target}])[0]


def test_positional_reordering_is_not_an_error():
    row = check({"x": "%s: %s"}, {"x": "%2$s: %1$s"})
    assert not row["error"]


def test_plural_omission_is_only_a_hint():
    row = check(
        {"x": "%(n)d item", "x__plural_1": "%(n)d items"},
        {"x": "one item", "x__plural_1": "%(n)d items"},
    )
    assert not row["error"]
    assert row["hint"]


def test_unexpected_placeholder_is_an_error():
    row = check({"x": "hello"}, {"x": "hello %(owner)s"})
    assert row["error"]


def test_strftime_is_not_treated_as_printf():
    row = check({"x": "%Y-%m-%d"}, {"x": "%d/%m/%Y"})
    assert not row["error"]
