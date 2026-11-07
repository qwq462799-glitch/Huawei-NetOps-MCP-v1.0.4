from app.security.device_output import detect_device_error


def test_detects_cloudengine_vrp_parser_error():
    output = """[~HUAWEI]display hostname
Error: Unrecognized command found at '^' position.
"""
    result = detect_device_error(output)
    assert result is not None
    assert "Unrecognized command" in result["line"]


def test_detects_cisco_invalid_input_but_not_normal_error_counter():
    assert detect_device_error("% Invalid input detected at '^' marker.") is not None
    assert detect_device_error("GigabitEthernet0/0: 0 input errors, 0 CRC") is None
    assert detect_device_error("Error: 7 input errors counted in historical log") is None


def test_ansi_escape_is_ignored():
    assert detect_device_error("\x1b[31mError: Wrong parameter\x1b[0m") is not None
