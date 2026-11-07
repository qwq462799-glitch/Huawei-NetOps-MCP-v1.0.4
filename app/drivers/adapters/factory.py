from app.drivers.adapters.ensp import ENSPLegacyAdapter
from app.drivers.adapters.ensp_pro import ENSPProAdapter

_ADAPTERS = {
    "ensp": ENSPLegacyAdapter(),
    "ensp_pro": ENSPProAdapter(),
}


def normalize_device(device: dict) -> dict:
    """Apply a simulator adapter when the device belongs to a simulator.

    Existing physical-device records remain unchanged. For backwards
    compatibility, legacy eNSP records may still omit simulator and use the
    explicit `platform: huawei_vrp_ensp` marker or `simulator: ensp`.
    """
    simulator = str(device.get("simulator", "")).strip().lower()
    platform = str(device.get("platform", "")).strip().lower()
    if not simulator and platform == "huawei_vrp_ensp":
        simulator = "ensp"
    if not simulator:
        return dict(device)
    adapter = _ADAPTERS.get(simulator)
    if adapter is None:
        raise ValueError(f"未知模拟器类型：{simulator}；支持 ensp、ensp_pro")
    return adapter.normalize(device)
