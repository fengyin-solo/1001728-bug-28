"""维保合同接口：维护维保合同，覆盖确认签订、标记到期、终止合同等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.contract import ALL_STATUSES, SORTABLE_FIELDS, service

router = APIRouter(prefix="/api/contract", tags=["维保合同"])

LIST_FIELDS = ["合同编号", "服务单位", "维保设备", "合同金额", "服务期限", "签订人员", "到期日期", "合同状态"]
STATUSES = list(ALL_STATUSES)


def _list_kwargs(
    keyword: str | None,
    unit: str | None,
    device: str | None,
    status: str | None,
    sort_by: str | None,
    order: str,
    page: int,
    size: int,
    *,
    max_size: int = 200,
) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始")
    if size < 1 or size > max_size:
        raise HTTPException(status_code=400, detail=f"每页数量需在 1 到 {max_size} 之间")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"合同状态需是以下之一：{'、'.join(STATUSES)}")
    if sort_by and sort_by not in SORTABLE_FIELDS:
        raise HTTPException(status_code=400, detail=f"暂不支持按「{sort_by}」排序")
    if order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="排序方向只能是 asc 或 desc")
    return {
        "keyword": keyword,
        "unit": unit,
        "device": device,
        "status": status,
        "sort_by": sort_by,
        "order": order,
        "page": page,
        "size": size,
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按合同编号检索"),
    unit: str | None = Query(default=None, description="按服务单位过滤"),
    device: str | None = Query(default=None, description="按维保设备过滤"),
    status: str | None = Query(default=None, description="待签订、履行中、已到期、已终止"),
    sort_by: str | None = Query(default=None, description="排序字段：到期日期、合同金额"),
    order: str = Query(default="asc", description="asc 升序 / desc 降序"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按合同编号、服务单位、维保设备与状态叠加过滤维保合同列表。

    条件之间取交集，命中数 total 即过滤后的总数，排序与履约状态都由后端给出。
    """
    kwargs = _list_kwargs(keyword, unit, device, status, sort_by, order, page, size)
    items, total = service.list_entries(**kwargs)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats/summary")
def stats_summary() -> dict[str, Any]:
    """合同统计：在履合同数与列表、详情、运营概览取自同一份落库口径。"""
    return service.stats()


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    unit: str | None = None,
    device: str | None = None,
    status: str | None = None,
    sort_by: str | None = None,
    order: str = "asc",
) -> dict[str, Any]:
    """导出维保合同清单：返回当前过滤条件叠加后的全量命中数据，口径与列表一致。"""
    kwargs = _list_kwargs(
        keyword, unit, device, status, sort_by, order, 1, 10000, max_size=10000
    )
    items, total = service.list_entries(**kwargs)
    return {"module": "contract", "total": total, "items": items}


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
    """对单条维保合同执行确认签订、标记到期、终止合同；不允许的动作会被拦下并说明当前状态。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
