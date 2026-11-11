"""設計計算器共用的小工具（自 design_api.py 拆出，2026-11-11 W6 第二批）。

`DesignAPIError` 定義在此（而非 design_api.py）：design_api 會 import catalog.*，
若 catalog 反向 import design_api 會循環，故例外類別放在最低層，design_api 再轉出。
"""

from typing import Any, Mapping


class DesignAPIError(ValueError):
    """Invalid calculator id or input payload."""


def _num(data: Mapping[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value in (None, ""):
        if default is None:
            raise DesignAPIError(f"缺少參數 {key}")
        return float(default)
    return float(value)
