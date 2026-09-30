"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS

# 内部辅助表：只服务于特定业务判定，不计入业务模块清单与运营概览。
INTERNAL_TABLES = {"contract_expiry"}


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 到期判定记录表：每条维保合同至多一条，由合同服务负责读写。
        self._tables["contract_expiry"] = []

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in INTERNAL_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        # 在履合同数直接取合同服务的同一口径，保证与合同列表、详情一致。
        from app.services.contract import ContractService

        contract_summary = ContractService().summary()
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            module = {
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            }
            if name == "contract":
                module["performing"] = contract_summary["performingCount"]
            modules.append(module)
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
            {"label": "在履合同", "value": contract_summary["performingCount"]},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
