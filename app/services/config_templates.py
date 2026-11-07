"""Reviewed starter templates. Rendering never applies changes to devices."""
from __future__ import annotations

import ipaddress
import re

TEMPLATES = {
    "huawei_vlan_create": {
        "vendor": "huawei", "description": "创建 VLAN（VRP/CloudEngine）",
        "required": ["vlan_id"], "optional": ["description", "commit"],
    },
    "h3c_vlan_create": {
        "vendor": "h3c", "description": "创建 VLAN（Comware）",
        "required": ["vlan_id"], "optional": ["description"],
    },
    "cisco_vlan_create": {
        "vendor": "cisco", "description": "创建 VLAN（IOS/IOS XE）",
        "required": ["vlan_id"], "optional": ["name"],
    },
    "huawei_static_route_add": {
        "vendor": "huawei", "description": "添加 IPv4 静态路由（VRP）",
        "required": ["prefix", "next_hop"], "optional": ["preference", "commit"],
    },
    "h3c_static_route_add": {
        "vendor": "h3c", "description": "添加 IPv4 静态路由（Comware）",
        "required": ["prefix", "next_hop"], "optional": ["preference"],
    },
    "cisco_static_route_add": {
        "vendor": "cisco", "description": "添加 IPv4 静态路由（IOS/IOS XE）",
        "required": ["prefix", "next_hop"], "optional": ["distance"],
    },
}


def _vlan(value) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError("vlan_id 必须是 1-4094 的整数")
    number = int(value)
    if not 1 <= number <= 4094:
        raise ValueError("vlan_id 必须是 1-4094 的整数")
    return number



def _bounded_integer(value, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError(f"{name} 必须是 {minimum}-{maximum} 的整数")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}-{maximum} 之间")
    return number

def _text(value, name: str, max_len: int = 64) -> str:
    value = str(value).strip()
    if not value or len(value) > max_len or not re.fullmatch(r"[A-Za-z0-9_. -]+", value):
        raise ValueError(f"{name} 仅允许字母、数字、空格、点、下划线和连字符，长度 1-{max_len}")
    return value


def _ip_prefix(value: str) -> str:
    try:
        return str(ipaddress.IPv4Network(value, strict=False))
    except Exception as exc:
        raise ValueError("prefix 必须是有效 IPv4 网段，例如 10.10.10.0/24") from exc


def _ip(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except Exception as exc:
        raise ValueError("next_hop 必须是有效 IPv4 地址") from exc


def list_templates(vendor: str | None = None) -> list[dict]:
    return [
        {"template_id": key, **meta}
        for key, meta in TEMPLATES.items()
        if vendor is None or meta["vendor"] == vendor
    ]


def render_template(template_id: str, device: dict, parameters: dict) -> dict:
    meta = TEMPLATES.get(template_id)
    if not meta:
        raise ValueError(f"未知模板：{template_id}")
    if device.get("vendor") != meta["vendor"]:
        raise ValueError(f"模板厂商为 {meta['vendor']}，设备厂商为 {device.get('vendor')}")
    if not isinstance(parameters, dict):
        raise ValueError("parameters 必须是 JSON 对象")
    missing = [key for key in meta["required"] if key not in parameters]
    unknown = set(parameters) - set(meta["required"]) - set(meta["optional"])
    if missing:
        raise ValueError(f"缺少模板参数：{', '.join(missing)}")
    if unknown:
        raise ValueError(f"包含不支持的模板参数：{', '.join(sorted(unknown))}")

    vid = _vlan(parameters["vlan_id"]) if "vlan_id" in parameters else None
    commit_value = parameters.get("commit", False)
    if not isinstance(commit_value, bool):
        raise ValueError("commit 参数必须是 JSON 布尔值 true/false")
    commit = commit_value
    commands: list[str]
    rollback: list[str]
    verify: str
    contains: list[str] = []
    not_contains: list[str] = []

    if template_id.endswith("vlan_create"):
        if template_id == "huawei_vlan_create":
            desc = _text(parameters.get("description", f"NETOPS_VLAN_{vid}"), "description")
            commands = ["system-view", f"vlan {vid}", f"description {desc}"]
            rollback = ["system-view", f"undo vlan {vid}"]
            if commit:
                commands.append("commit"); rollback.append("commit")
            commands.append("return"); rollback.append("return")
            verify = f"display vlan {vid}"
            contains = [f"VLAN {vid}"]
        elif template_id == "h3c_vlan_create":
            desc = _text(parameters.get("description", f"NETOPS_VLAN_{vid}"), "description")
            commands = ["system-view", f"vlan {vid}", f"description {desc}", "quit", "return"]
            rollback = ["system-view", f"undo vlan {vid}", "return"]
            verify = f"display vlan {vid}"; contains = [f"VLAN {vid}"]
        else:
            name = _text(parameters.get("name", f"NETOPS_VLAN_{vid}"), "name")
            commands = ["configure terminal", f"vlan {vid}", f"name {name}", "end"]
            rollback = ["configure terminal", f"no vlan {vid}", "end"]
            verify = f"show vlan id {vid}"; contains = [str(vid)]
    else:
        prefix = _ip_prefix(parameters["prefix"])
        next_hop = _ip(parameters["next_hop"])
        if template_id.startswith("huawei_"):
            pref = _bounded_integer(parameters.get("preference", 60), "preference", 1, 255)
            network = ipaddress.IPv4Network(prefix)
            route = f"ip route-static {network.network_address} {network.prefixlen} {next_hop} preference {pref}"
            commands = ["system-view", route]
            rollback = ["system-view", f"undo {route}"]
            if commit: commands.append("commit"); rollback.append("commit")
            commands.append("return"); rollback.append("return")
            verify = f"display ip routing-table {prefix}"
            contains = [next_hop]
        elif template_id.startswith("h3c_"):
            pref = _bounded_integer(parameters.get("preference", 60), "preference", 1, 255)
            network = ipaddress.IPv4Network(prefix)
            route = f"ip route-static {network.network_address} {network.prefixlen} {next_hop} preference {pref}"
            commands = ["system-view", route, "return"]
            rollback = ["system-view", f"undo {route}", "return"]
            verify = f"display ip routing-table {prefix}"; contains = [next_hop]
        else:
            distance = _bounded_integer(parameters.get("distance", 1), "distance", 1, 255)
            network = str(ipaddress.IPv4Network(prefix).network_address)
            mask = str(ipaddress.IPv4Network(prefix).netmask)
            route = f"ip route {network} {mask} {next_hop} {distance}"
            commands = ["configure terminal", route, "end"]
            rollback = ["configure terminal", f"no {route}", "end"]
            verify = f"show ip route {network}"; contains = [next_hop]

    return {
        "success": True,
        "template_id": template_id,
        "device_id": device["id"],
        "description": meta["description"],
        "commands": commands,
        "rollback_commands": rollback,
        "verify_command": verify,
        "expected_output_contains_all": contains,
        "expected_output_not_contains": not_contains,
        "expected_output_regex": [],
        "requires_manual_review": True,
        "preconditions": ([f"确认 VLAN {vid} 当前不存在，避免回滚时误删已有 VLAN。"] if vid is not None else
                          [f"确认目标路由 {prefix} 尚不存在，避免回滚时移除已有路由。"]),
        "apply_instruction": "请人工核对命令、回滚命令和验证断言后，再调用 config_request_approval 创建审批单；本工具不会下发配置。",
        "platform_note": "VRP8/CloudEngine 设备如要求两阶段提交，请在参数 commit=true；普通 VRP/H3C/Cisco 不应盲目加入 commit。",
    }
