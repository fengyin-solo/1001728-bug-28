"""维保合同业务规则：筛选排序、到期判定落库、状态单向流转与统计口径都收在这里。

列表/详情/概览只读本服务给出的结果，前端不再各自推算履约状态：
- 到期判定结果落库为「到期判定」记录（判定结果、判定依据日期、判定时间、来源）；
- 存量合同按签订时的服务期限回填一条到期记录，已归档的历史结论不被推翻；
- 履约状态只能 待签订 → 履行中 → 已到期 单向推进，终止合同为履行中的终态动作。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "contract"
REQUIRED_FIELDS = ["合同编号", "服务单位", "维保设备"]

# 履约状态只允许沿这个序列单向推进；已终止是履行合同的终止终态，不属于履约序列。
STATUS_ORDER = ["待签订", "履行中", "已到期"]
STATUS_TERMINATED = "已终止"
ALL_STATUSES = [*STATUS_ORDER, STATUS_TERMINATED]

# 每个动作允许从哪些当前状态发起；不在表里的一律挡下并说明当前状态。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "确认签订": {"target": "履行中", "allow_from": {"待签订"}},
    "标记到期": {"target": "已到期", "allow_from": {"履行中"}},
    "终止合同": {"target": "已终止", "allow_from": {"履行中"}},
}

SORTABLE_FIELDS = {"到期日期", "合同金额"}
UPCOMING_WINDOW_DAYS = 30
BACKFILL_SOURCE = "存量回填"
MANUAL_SOURCE = "人工标记"


def _parse_day(value: Any) -> date | None:
    """把 YYYY-MM-DD 文本解析成日期；解析不了（占位文本/空值）就返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _resolve_due_date(row: dict[str, Any]) -> date | None:
    """到期日期优先取合同登记的「到期日期」；缺失时再按「服务期限」的截止日推断。

    服务期限支持单日（2026-01-01）或区间（2026-01-01 至 2026-12-31）两种写法。
    """
    due = _parse_day(row.get("到期日期"))
    if due is not None:
        return due
    term = str(row.get("服务期限") or "").strip()
    if not term:
        return None
    for sep in ("至", "~", "～", "-"):
        if sep in term:
            tail = term.split(sep)[-1].strip()
            parsed = _parse_day(tail)
            if parsed is not None:
                return parsed
    return _parse_day(term)


def _build_expiry_record(due: date, *, source: str, judged_on: date) -> dict[str, Any]:
    """落库一条到期判定记录；同一份合同的履约状态只认这份落库结论。"""
    return {
        "判定结果": "已到期",
        "判定依据日期": due.isoformat(),
        "判定时间": judged_on.isoformat(),
        "来源": source,
    }


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用的输出口径：合同状态直接取落库状态，不再各算各的。"""
    item = dict(row)
    item["合同状态"] = row.get("status")
    return item


class ContractService:
    def __init__(self) -> None:
        self._backfilled = False

    # ---------------------------------------------------------------- 列表/详情

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        unit: str | None = None,
        device: str | None = None,
        status: str | None = None,
        sort_by: str | None = None,
        order: str = "asc",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """筛选条件叠加取交集，排序与分页都在后端口径内完成，命中集即返回集。"""
        rows = store.rows(MODULE)

        # 所有条件是 AND：逐条同时满足才进命中集，避免按服务单位过滤还看到别家。
        if keyword and keyword.strip():
            needle = keyword.strip()
            rows = [row for row in rows if needle in str(row.get("合同编号", ""))]
        if unit and unit.strip():
            needle = unit.strip()
            rows = [row for row in rows if needle in str(row.get("服务单位", ""))]
        if device and device.strip():
            needle = device.strip()
            rows = [row for row in rows if needle in str(row.get("维保设备", ""))]
        if status and status.strip():
            needle = status.strip()
            rows = [row for row in rows if row.get("status") == needle]

        rows = self._sort_rows(rows, sort_by=sort_by, descending=(order == "desc"))

        total = len(rows)
        start = max(page - 1, 0) * size
        return [_serialize(row) for row in rows[start:start + size]], total

    @staticmethod
    def _sort_rows(
        rows: list[dict[str, Any]], *, sort_by: str | None, descending: bool
    ) -> list[dict[str, Any]]:
        if sort_by == "到期日期":
            # 日期解析不出来的排到最后，避免早已到期的合同被错误日期文本顶到前面。
            def due_key(row: dict[str, Any]) -> tuple[int, date]:
                due = _resolve_due_date(row)
                return (0, due) if due is not None else (1, date.max)

            return sorted(rows, key=due_key, reverse=descending)
        if sort_by == "合同金额":
            def amount_key(row: dict[str, Any]) -> tuple[int, float]:
                try:
                    return (0, float(row.get("合同金额") or 0))
                except (TypeError, ValueError):
                    return (1, 0.0)

            return sorted(rows, key=amount_key, reverse=descending)
        # 默认按登记顺序，保证分页稳定。
        return sorted(rows, key=lambda row: int(row.get("id", 0)))

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _serialize(row) if row is not None else None

    # -------------------------------------------------------------------- 登记

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 合同金额与到期日期仅在登记时写入，后续流转动作不再改动这两项。
        if values.get("合同金额") is not None:
            entry["合同金额"] = values.get("合同金额")
        if values.get("服务期限") is not None:
            entry["服务期限"] = values.get("服务期限")
        if values.get("签订人员") is not None:
            entry["签订人员"] = values.get("签订人员")
        if values.get("到期日期") is not None:
            entry["到期日期"] = values.get("到期日期")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _serialize(entry), []

    # ------------------------------------------------------------ 状态流转动作

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """履约状态单向推进：回退、跳档、重复下发都挡下，并说明合同当前状态。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"维保合同 {entry_id} 不存在或已归档"
        rule = ACTION_RULES.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于维保合同可执行范围"

        current = str(entry.get("status") or "")
        target = str(rule["target"])
        if current not in rule["allow_from"]:
            if current == target:
                # 同一次到期判定重复下发只生效一次：重复动作幂等挡下，不重复落库。
                return None, f"维保合同当前为「{current}」，无需重复{action}"
            if current == STATUS_TERMINATED:
                return None, f"维保合同当前为「已终止」，已终止合同不能再{action}"
            return None, (
                f"维保合同当前为「{current}」，不能直接{action}；"
                f"履约状态只能按 待签订 → 履行中 → 已到期 单向推进"
            )

        if action == "标记到期":
            # 到期判定落库：列表、详情、概览以后端这份命中结论为准。
            record = _build_expiry_record(
                _resolve_due_date(entry) or date.today(),
                source=MANUAL_SOURCE,
                judged_on=date.today(),
            )
            entry["到期判定"] = record
        entry["status"] = target
        entry["pending"] = target != STATUS_TERMINATED and target != STATUS_ORDER[-1]
        entry["abnormal"] = False
        return _serialize(entry), f"维保合同已{action}"

    # ------------------------------------------------------------ 存量回填判定

    def backfill_expiry_records(self, *, today: date | None = None) -> int:
        """给此前没有判定结果的存量合同按签订时的服务期限回填一条到期记录。

        - 只补没有「到期判定」的合同，且只依据合同自己的服务期限/到期日期推断；
        - 已到期、已终止属已归档的历史结论，回填不推翻其状态；
        - 履行中但服务期限已过的合同，补落「已到期」结论，修正列表/详情不一致；
        - 待签订合同尚未起算服务期限，不回填，避免从待签订跳档到已到期；
        - 回填不动合同金额与到期日期原值。
        """
        if self._backfilled:
            return 0
        self._backfilled = True
        today = today or date.today()
        changed = 0
        for row in store.rows(MODULE):
            if row.get("到期判定"):
                continue
            current = str(row.get("status") or "")
            if current not in {"履行中", "已到期", "已终止"}:
                continue
            due = _resolve_due_date(row)
            if due is None or due > today:
                continue
            row["到期判定"] = _build_expiry_record(
                due, source=BACKFILL_SOURCE, judged_on=today
            )
            if current == "履行中":
                # 以落库判定为准，修正前端各自推算导致的「早已到期仍显示履行中」。
                row["status"] = "已到期"
                row["pending"] = False
                row["abnormal"] = False
            # 已到期/已终止：只补判定记录，状态保持归档结论不变。
            changed += 1
        return changed

    # ---------------------------------------------------------------- 统计口径

    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in ALL_STATUSES}
        for row in store.rows(MODULE):
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return counts

    def stats(self, *, today: date | None = None) -> dict[str, Any]:
        """在履合同数与列表、详情取同一份（落库状态），概览卡片也调这里。"""
        today = today or date.today()
        horizon = today + timedelta(days=UPCOMING_WINDOW_DAYS)
        active = 0
        upcoming = 0
        total_amount = 0.0
        for row in store.rows(MODULE):
            try:
                total_amount += float(row.get("合同金额") or 0)
            except (TypeError, ValueError):
                pass
            if row.get("status") != "履行中":
                continue
            active += 1
            due = _resolve_due_date(row)
            if due is not None and today <= due <= horizon:
                upcoming += 1
        return {
            "active": active,
            "upcoming": upcoming,
            "total_amount": round(total_amount, 2),
            "status_counts": self.status_counts(),
        }


service = ContractService()
