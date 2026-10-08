from scripts.azm_build_boundary import replay


def test_missing_mo_falls_back_and_compiled_mo_resolves_arabic():
    result = replay()
    assert result["before"]["output"] == "Ticket queue"
    assert result["before"]["falls_back_to_source"] is True
    assert result["after"]["output"] == "قائمة التذاكر"
    assert result["after"]["translated"] is True
    assert result["guard_product_needed"] is False
