import pytest

from app.services.verification import validate_assertions, evaluate_assertions


def test_contains_not_contains_and_regex_are_all_required():
    assertions = validate_assertions(
        expected_output_contains="VLAN 300",
        expected_output_contains_all=["NETOPS"],
        expected_output_not_contains=["VLAN 400"],
        expected_output_regex=[r"VLAN\s+300"],
    )
    result = evaluate_assertions(
        "VLAN    300  NETOPS\nVLAN 500",
        **assertions,
    )
    assert result["passed"] is True
    assert len(result["checks"]) == 4


def test_not_contains_can_verify_deletion():
    assertions = validate_assertions(expected_output_not_contains=["VLAN 400"])
    assert evaluate_assertions("VLAN 100\nVLAN 300", **assertions)["passed"] is True
    assert evaluate_assertions("VLAN 100\nVLAN 400", **assertions)["passed"] is False


def test_invalid_regex_and_empty_assertions_are_rejected():
    with pytest.raises(ValueError, match="至少提供一条验证断言"):
        validate_assertions()
    with pytest.raises(ValueError, match="无效的验证正则表达式"):
        validate_assertions(expected_output_regex=["["])


def test_device_error_fails_verification_even_when_contains_matches():
    assertions = validate_assertions(expected_output_contains="VLAN")
    result = evaluate_assertions("VLAN 300\nError: Unrecognized command", **assertions)
    assert result["passed"] is False
    assert result["device_error"] is not None


def test_truncated_output_adds_actionable_warning():
    assertions = validate_assertions(expected_output_contains="NETOPS-MCP-VERIFY-2026")
    result = evaluate_assertions("description NETOPS-MCP-VERIFY...", **assertions)
    assert result["passed"] is False
    assert result["truncation_suspected"] is True
    assert result["warnings"]


def test_truncated_output_cannot_prove_not_contains_deletion():
    assertions = validate_assertions(expected_output_not_contains=["VLAN 400"])
    result = evaluate_assertions("VLAN 100\nVLAN 300\n...", **assertions)
    assert result["passed"] is False
    assert result["truncation_suspected"] is True
    assert result["failed_checks"][0]["inconclusive"] is True


def test_high_risk_regex_constructs_are_rejected():
    for pattern in (r"(a+)+$", r"(a|aa)+$", r"(a)\1"):
        with pytest.raises(ValueError, match="高风险回溯"):
            validate_assertions(expected_output_regex=[pattern])
