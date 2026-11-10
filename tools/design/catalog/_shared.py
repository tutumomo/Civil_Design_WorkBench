"""設計計算器共用的小工具（自 design_api.py 拆出，2026-11-11 W6 第二批）。"""

from typing import Any, Mapping


def _num(data: Mapping[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value in (None, ""):
        if default is None:
            raise DesignAPIError(f"缺少參數 {key}")
        return float(default)
    return float(value)
