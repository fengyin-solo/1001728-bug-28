"""维保合同业务规则：筛选口径、履约状态与到期判定都收在这里，前后端只认这一份。

设计要点（对应列表页“对不上”的几类问题）：

- 筛选、排序、履约状态全部在后端算，列表、详情、导出、概览共用同一口径，
  前端不再各自计算，避免“详情按存下来的判、列表按前端算的显示”。
- 到期判定落库：每条合同至多一条到期记录（contract_expiry），
  同一次到期判定重复下发只生效一次。
- 履约状态只能 待签订 → 履行中 → 已到期 单向推进；已终止是历史归档状态，
  回退或跳档一律拦下并说明当前状态。
- 存量合同在服务启动时按签订时的服务期限回填到期记录，
  回填只新增判定记录，不改动已归档的历史结论，也不改动合同金额与到期日期。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
import re

from app.store import store

MODULE = "contract"
EXPIRY_MODULE = "contract_expiry"
REQUIRED_FIELDS = ["合同编号", "服务单位", "维保设备"]
OPTIONAL_FIELDS = ["合同金额", "服务期限", "签订人员", "到期日期"]

# 履约状态：待签订 → 履行中 → 已到期，单向推进。
LIFECYCLE = ["待签订", "履行中", "已到期"]
# 已终止是归档终态，不参与履约推进。
TERMINATED = "已终止"
ALL_STATUSES = LIFECYCLE + [TERMINATED]

ACTION_RULES = {"确认签订": "履行中", "标记到期": "已到期", "终止合同": TERMINATED}

DATE_PATTERN = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")
UPCOMING_DAYS = 30

EXPIRY_SOURCE_BACKFILL = "存量回填"
EXPIRY_SOURCE_MANUAL = "到期判定"


def today() -> date:
    return date.today()


def parse_date(value: Any) -> date | None:
    """把 '2026-09-01' / '2026年9月1日' 这类文本解析成日期，解析不了就返回 None。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


class ContractService:
    # ---------- 到期判定落库 ----------

    def _expiry_rows(self) -> list[dict[str, Any]]:
        return store.rows(EXPIRY_MODULE)

    def find_expiry(self, contract_id: int) -> dict[str, Any] | None:
        """读取某条合同的到期判定记录；有且仅有一条。"""
        for row in self._expiry_rows():
            if int(row.get("合同id", 0)) == contract_id:
                return row
        return None

    def _derive_expiry_date(self, entry: dict[str, Any]) -> date | None:
        """按签订时的服务期限推导到期日期。

        服务期限常见写法是 '2026-01-01 至 2026-12-31' 这种区间，取区间末日期；
        识别不出来时退回合同上已登记的到期日期；都没有就留空。
        只读取，不回写合同字段。
        """
        period = str(entry.get("服务期限") or "").strip()
        dates = DATE_PATTERN.findall(period)
        parsed: list[date] = []
        for parts in dates:
            try:
                parsed.append(date(int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                continue
        if parsed:
            return max(parsed)
        return parse_date(entry.get("到期日期"))

    def _create_expiry(
        self,
        entry: dict[str, Any],
        *,
        source: str,
        judged_at: datetime,
        remark: str = "",
    ) -> dict[str, Any]:
        """新增一条到期判定记录（每条合同至多一条，调用方负责先查重）。"""
        expiry_date = self._derive_expiry_date(entry)
        rows = self._expiry_rows()
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "合同id": int(entry["id"]),
            "合同编号": entry.get("合同编号"),
            "到期日期": iso_date(expiry_date),
            "判定时间": judged_at.isoformat(timespec="seconds"),
            "来源": source,
            "备注": remark,
        }
        rows.append(record)
        return record

    def backfill_expiries(self) -> int:
        """为此前没有判定结果的存量合同，按签订时的服务期限回填一条到期记录。

        - 已有判定记录的合同跳过，回填不推翻已归档的历史结论；
        - 履行中且服务期限已过的合同，顺理成章置为已到期（修复“早已到期却显示履行中”）；
        - 待签订/已终止等状态只补判定记录，历史状态原样保留；
        - 全程不改动合同金额、到期日期等原有字段。
        """
        backfilled = 0
        now = datetime.now()
        for entry in store.rows(MODULE):
            if self.find_expiry(int(entry["id"])) is not None:
                continue
            record = self._create_expiry(
                entry, source=EXPIRY_SOURCE_BACKFILL, judged_at=now,
                remark="启动时按签订服务期限回填",
            )
            backfilled += 1
            if entry.get("status") == "履行中":
                expiry_date = parse_date(record.get("到期日期"))
                if expiry_date is not None and expiry_date < today():
                    entry["status"] = "已到期"
                    entry["pending"] = False
        return backfilled

    # ---------- 统一口径 ----------

    def _canonical_status(self, entry: dict[str, Any]) -> str:
        """合同履约状态的唯一口径：落库的 status 字段，异常值归一到待签订。"""
        status = entry.get("status")
        return status if status in ALL_STATUSES else LIFECYCLE[0]

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表/详情/导出共用的展示结构，合同状态以落库判定为准。"""
        data = dict(entry)
        status = self._canonical_status(entry)
        data["status"] = status
        data["合同状态"] = status
        expiry = self.find_expiry(int(entry["id"]))
        data["到期判定"] = expiry or None
        return data

    def _matches(
        self,
        entry: dict[str, Any],
        *,
        keyword: str | None,
        service_unit: str | None,
        status: str | None,
        expiring_only: bool,
    ) -> bool:
        if keyword and keyword not in str(entry.get("合同编号", "")):
            return False
        # 按服务单位过滤：做包含匹配，中文单位名不再串到别家。
        if service_unit and service_unit not in str(entry.get("服务单位", "")):
            return False
        if status and self._canonical_status(entry) != status:
            return False
        if expiring_only:
            expiry = parse_date(entry.get("到期日期"))
            if expiry is None:
                return False
            delta = (expiry - today()).days
            if not (0 <= delta <= UPCOMING_DAYS):
                return False
        return True

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        service_unit: str | None = None,
        status: str | None = None,
        expiring_only: bool = False,
        sort_by_expiry: bool = False,
        order: str = "asc",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 条件逐个叠加，命中的是各条件的交集，命中数与页脚同源。
        rows = [
            entry
            for entry in store.rows(MODULE)
            if self._matches(
                entry,
                keyword=str(keyword or "").strip() or None,
                service_unit=str(service_unit or "").strip() or None,
                status=str(status or "").strip() or None,
                expiring_only=expiring_only,
            )
        ]
        if sort_by_expiry:
            # 到期日期排序以后端解析的日期为准；日期缺失/无法解析的排到最后。
            def sort_key(entry: dict[str, Any]) -> tuple[int, date | None, int]:
                parsed = parse_date(entry.get("到期日期"))
                return (1 if parsed is None else 0, parsed, int(entry.get("id", 0)))

            rows.sort(key=sort_key, reverse=(order == "desc"))
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(entry) for entry in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def summary(self) -> dict[str, Any]:
        """在履合同数等指标的唯一来源：合同详情、列表卡片、运营概览都取这里。"""
        rows = store.rows(MODULE)
        performing = sum(1 for row in rows if self._canonical_status(row) == "履行中")
        upcoming = 0
        total_amount = 0.0
        for row in rows:
            expiry = parse_date(row.get("到期日期"))
            if (
                expiry is not None
                and self._canonical_status(row) == "履行中"
                and 0 <= (expiry - today()).days <= UPCOMING_DAYS
            ):
                upcoming += 1
            try:
                total_amount += float(row.get("合同金额") or 0)
            except (TypeError, ValueError):
                continue
        return {
            "performingCount": performing,
            "upcomingCount": upcoming,
            "totalAmount": round(total_amount, 2),
        }

    # ---------- 写入 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry["status"] = LIFECYCLE[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"维保合同 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于维保合同可执行范围"

        current = self._canonical_status(entry)
        now = datetime.now()

        if action == "终止合同":
            if current == TERMINATED:
                return None, f"合同已处于「{TERMINATED}」归档状态，不能重复终止"
            # 终止是归档动作，待签订/履行中/已到期都可以归档，归档后不可再回退。
            entry["status"] = TERMINATED
            entry["pending"] = False
            if self.find_expiry(entry_id) is None:
                self._create_expiry(
                    entry, source=EXPIRY_SOURCE_MANUAL, judged_at=now,
                    remark="合同终止时补登的到期判定",
                )
            return self._present(entry), "维保合同已终止合同"

        target = ACTION_RULES[action]

        if action == "确认签订":
            if current == "履行中":
                return None, f"合同当前为「履行中」，确认签订无需重复下发"
            if current == "已到期":
                return None, f"合同当前为「已到期」，不能回退到「履行中」"
            if current == TERMINATED:
                return None, f"合同当前为「已终止」归档状态，不能回退到「履行中」"
            entry["status"] = target
            entry["pending"] = True
            return self._present(entry), "维保合同已确认签订"

        # 标记到期：到期判定落库，重复下发只生效一次，且只能由履行中单向推进。
        if current == "已到期":
            record = self.find_expiry(entry_id)
            when = record.get("判定时间") if record else None
            detail = f"（判定时间：{when}）" if when else ""
            return None, f"合同当前为「已到期」，到期判定已生效{detail}，重复下发不再处理"
        if current == "待签订":
            return None, f"合同当前为「待签订」，需先确认签订，不能跳档到「已到期」"
        if current == TERMINATED:
            return None, f"合同当前为「已终止」归档状态，不能改判为「已到期」"

        record = self.find_expiry(entry_id)
        if record is None:
            record = self._create_expiry(entry, source=EXPIRY_SOURCE_MANUAL, judged_at=now)
        elif record.get("来源") == EXPIRY_SOURCE_BACKFILL:
            # 带未来到期日的回填合同被提前判定到期：沿用同一条记录，只更新判定信息。
            record["判定时间"] = now.isoformat(timespec="seconds")
            record["来源"] = EXPIRY_SOURCE_MANUAL
            record["备注"] = "履行期内提前判定到期"
        entry["status"] = target
        entry["pending"] = False
        return self._present(entry), "维保合同已标记到期"
