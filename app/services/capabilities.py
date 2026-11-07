"""Vendor command catalog and conservative device-version fingerprinting."""
from __future__ import annotations

import re
from app.security.redaction import redact_text

COMMAND_CATALOG = {
    "huawei": {
        "version": "display version",
        "hostname": "display sysname",
        "interfaces": "display interface brief",
        "vlans": "display vlan",
        "routing": "display ip routing-table",
        "configuration": "display current-configuration",
        "arp": "display arp",
        "lldp": "display lldp neighbor brief",
    },
    "h3c": {
        "version": "display version",
        "hostname": "display system-information",
        "interfaces": "display interface brief",
        "vlans": "display vlan",
        "routing": "display ip routing-table",
        "configuration": "display current-configuration",
        "arp": "display arp",
        "lldp": "display lldp neighbor-information brief",
    },
    "cisco": {
        "version": "show version",
        "hostname": "show running-config | include ^hostname",
        "interfaces": "show ip interface brief",
        "vlans": "show vlan brief",
        "routing": "show ip route",
        "configuration": "show running-config",
        "arp": "show ip arp",
        "lldp": "show lldp neighbors",
    },
}

_MODEL_PATTERNS = (
    re.compile(r"\b(CE\d{4,5}|S\d{4,5}|NE\d{3,5}|AR\d{3,5}|USG\d{3,5})\b", re.I),
    re.compile(r"\b(WS-C\d{4,5}[A-Z0-9-]*|C\d{4,5}[A-Z0-9-]*|N\d{3,4}[A-Z0-9-]*)\b", re.I),
    re.compile(r"\b(\d{4,5}[A-Z]{0,4})\b", re.I),
)


def fingerprint_version(configured_vendor: str, output: str) -> dict:
    text = redact_text(output or "")
    lower = text.lower()
    detected = configured_vendor
    confidence = "configured_vendor_only"
    if any(token in lower for token in ("yunshan", "vrp", "huawei versatile routing", "cloudengine")):
        detected, confidence = "huawei", "version_signature"
    elif "comware" in lower or "h3c" in lower:
        detected, confidence = "h3c", "version_signature"
    elif any(token in lower for token in ("cisco ios", "ios xe", "ios xr", "nx-os", "nexus operating")):
        detected, confidence = "cisco", "version_signature"

    model = None
    for pattern in _MODEL_PATTERNS:
        match = pattern.search(text)
        if match:
            model = match.group(1).upper()
            break

    if detected == "huawei" and any(x in lower for x in ("yunshan", "vrp 8", "vrp8", "cloudengine")):
        platform_hint = "huawei_vrp8_or_cloudengine"
    elif detected == "huawei":
        platform_hint = "huawei_vrp"
    elif detected == "h3c":
        platform_hint = "h3c_comware"
    elif detected == "cisco" and "nx-os" in lower:
        platform_hint = "cisco_nxos"
    elif detected == "cisco":
        platform_hint = "cisco_ios_family"
    else:
        platform_hint = "unknown"

    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:12]
    return {
        "configured_vendor": configured_vendor,
        "detected_vendor": detected,
        "vendor_matches_configuration": detected == configured_vendor,
        "detection_confidence": confidence,
        "model_hint": model,
        "platform_hint": platform_hint,
        "version_excerpt": "\n".join(first_lines)[:1800],
        "command_catalog": COMMAND_CATALOG.get(detected, {}),
        "warning": "版本识别基于版本回显特征，不会自动修改已登记的 vendor/platform；请人工核对型号和系统版本。",
    }
