"""Best-effort secret redaction for logs, audit records, and returned CLI text."""
from __future__ import annotations

import re
from typing import Any

_REDACTED = "<REDACTED>"
_SECRET_LINE_PATTERNS = [
    # Huawei/H3C local users, RADIUS/TACACS, SNMP communities, IPSec keys.
    re.compile(
        r"(?i)(\b(?:password|passwd|secret|community|shared-key|pre-shared-key|psk|token|authorization-key)\b"
        r"(?:\s+(?:irreversible-cipher|cipher|simple|read|write|encrypted|[0-9]+)){0,2}\s+)(\S+)(.*)$"
    ),
    # Cisco-style username ... secret/password ... and enable secret.
    re.compile(r"(?i)(\b(?:username\s+\S+\s+(?:secret|password)|enable\s+secret)\s+)(\S+)(.*)$"),
    # TACACS/RADIUS and IKE/IPsec shared keys; keep trailing address/type fields.
    re.compile(r"(?i)(\b(?:tacacs-server|radius-server)\s+(?:host\s+\S+\s+)?key\s+(?:[0-9]+\s+)?)(\S+)(.*)$"),
    re.compile(r"(?i)(\b(?:crypto\s+isakmp\s+key|ike\s+pre-shared-key|authentication-key|auth-passphrase|priv-passphrase)\s+)(\S+)(.*)$"),
    # Private-key material should never be echoed into MCP logs/results.
    re.compile(r"(?i)(-----BEGIN [^-]*PRIVATE KEY-----).*(-----END [^-]*PRIVATE KEY-----)"),
]
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.I | re.S
)
_SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|community|shared.?key|private.?key|token|credential|api.?key)"
)


def redact_text(value: str | None) -> str:
    if value is None:
        return ""
    text = _PRIVATE_KEY_BLOCK_RE.sub("[PRIVATE KEY MATERIAL REDACTED]", str(value))
    output_lines = []
    for line in text.splitlines():
        redacted = line
        for pattern in _SECRET_LINE_PATTERNS:
            if pattern.search(redacted):
                if "PRIVATE KEY" in redacted.upper():
                    redacted = "[PRIVATE KEY MATERIAL REDACTED]"
                else:
                    redacted = pattern.sub(rf"\1{_REDACTED}\3", redacted, count=1) if pattern.groups >= 3 else pattern.sub(rf"\1{_REDACTED}", redacted, count=1)
                break
        output_lines.append(redacted)
    return "\n".join(output_lines)


def redact_value(value: Any, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(key):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
