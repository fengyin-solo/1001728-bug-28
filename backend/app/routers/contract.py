"""维保合同接口：维护维保合同，覆盖确认签订、标记到期、终止合同等动作。

列表的筛选（合同编号、服务单位、履约状态、即将到期）、到期日期排序都在后端完成，
条件叠加取交集，页脚 total 与命中行同源；前端不再自行排序或推算履约状态。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.contract import ALL_STATUSES, ContractService

router = APIRouter(prefix="/api/contract", tags=["维保合同"])

service = ContractService()

LIST_FIELDS = ["合同编号", "服务单位", "维保设备", "合同金额", "服务期限", "签订人员", "到期日期", "合同状态"]
STATUSES = ALL_STATUSES


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按合同编号检索"),
    service_unit: str | None = Query(default=None, description="按服务单位过滤"),
    status: str | None = Query(default=None, description="待签订、履行中、已到期、已终止"),
    expiring: bool = Query(default=False, description="仅看 30 天内到期的履行中合同"),
    sort_expiry: bool = Query(default=False, description="按到期日期排序"),
    order: str = Query(default="asc", description="到期日期排序方向：asc / desc"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按合同编号、服务单位、履约状态过滤维保合同列表；条件叠加取交集。

    没有数据时返回空页，不报错；total 是全部命中条件的行数，与页脚一致。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="排序方向只支持 asc 或 desc")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"合同状态只支持：{'、'.join(STATUSES)}")
    items, total = service.list_entries(
        keyword=keyword,
        service_unit=service_unit,
        status=status,
        expiring_only=expiring,
        sort_by_expiry=sort_expiry,
        order=order,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary", response_model=dict)
def contract_summary() -> dict[str, Any]:
    """在履合同数等指标的唯一口径：列表卡片、合同详情、运营概览都取这一份。"""
    return service.summary()


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条维保合同明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"维保合同 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条维保合同，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="维保合同已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条维保合同执行确认签订、标记到期、终止合同；回退或跳档会被拦下并说明当前状态。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    service_unit: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出维保合同清单：沿用当前过滤条件，命中口径与列表页一致。"""
    items, total = service.list_entries(
        keyword=keyword,
        service_unit=service_unit,
        status=status,
        page=1,
        size=10000,
    )
    return {"module": "contract", "total": total, "items": items}
