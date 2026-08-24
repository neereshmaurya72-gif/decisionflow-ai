"""Analytics helpers — Python port of src/lib/metrics.ts."""
from datetime import datetime

from store import is_overdue, today


def _d(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def overview_stats(meetings, decisions, tasks):
    completed = len([t for t in tasks if t["status"] == "Completed"])
    overdue = len([t for t in tasks if is_overdue(t)])
    pending = len([t for t in tasks
                   if not is_overdue(t) and t["status"] not in ("Completed", "Rejected")])
    needs_review = len([t for t in tasks if t["status"] == "Needs Review"])
    rate = (completed / len(tasks) * 100) if tasks else 0
    return {
        "meetings": len(meetings), "decisions": len(decisions), "tasks": len(tasks),
        "completed": completed, "pending": pending, "overdue": overdue,
        "needsReview": needs_review, "executionRate": round(rate, 1),
    }


STATUS_ORDER = ["Pending", "In Progress", "Submitted", "Completed", "Needs Review", "Overdue"]


def tasks_by_status(tasks):
    buckets = {k: 0 for k in STATUS_ORDER}
    for t in tasks:
        key = "Overdue" if is_overdue(t) else t["status"]
        buckets[key] = buckets.get(key, 0) + 1
    return [{"name": k, "value": v} for k, v in buckets.items()]


def tasks_by_employee(tasks, employees):
    rows = []
    for e in employees:
        if e["role"] != "employee":
            continue
        own = [t for t in tasks if t["employeeId"] == e["id"]]
        rows.append({
            "name": e["fullName"].split(" ")[0],
            "fullName": e["fullName"],
            "total": len(own),
            "completed": len([t for t in own if t["status"] == "Completed"]),
            "overdue": len([t for t in own if is_overdue(t)]),
        })
    return rows


def _week_label(value):
    return _d(value).strftime("%b %d")


def completion_over_time(tasks):
    buckets = {}
    for t in tasks:
        key = t["createdAt"]
        entry = buckets.setdefault(key, {"created": 0, "completed": 0})
        entry["created"] += 1
        if t.get("completedAt"):
            ce = buckets.setdefault(t["completedAt"], {"created": 0, "completed": 0})
            ce["completed"] += 1
    rows = []
    for key in sorted(buckets):
        v = buckets[key]
        rows.append({"name": _week_label(key), "created": v["created"], "completed": v["completed"],
                     "rate": round(v["completed"] / v["created"] * 100) if v["created"] else 0})
    return rows


def average_completion_days(tasks):
    done = [t for t in tasks if t.get("completedAt")]
    if not done:
        return 0
    total = sum(max(0, (_d(t["completedAt"]) - _d(t["createdAt"])).days) for t in done)
    return round(total / len(done), 1)


def verification_accuracy(evidence):
    verified = [e for e in evidence if e.get("verification")]
    if not verified:
        return 0
    agreed = len([e for e in verified if not e["verification"].get("overriddenBy")])
    return round(agreed / len(verified) * 100, 1)


def days_left(deadline):
    if not deadline:
        return None
    return (_d(deadline) - _d(today())).days


def meeting_execution(meeting, tasks):
    own = [t for t in tasks if t["meetingId"] == meeting["id"]]
    completed = len([t for t in own if t["status"] == "Completed"])
    return {"tasks": len(own), "completed": completed,
            "rate": round(completed / len(own) * 100, 1) if own else 0}