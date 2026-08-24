"""JSON-file backed application store (replaces the React context + localStorage)."""
import json
import os
import threading
import uuid
from datetime import datetime

from demo_data import build_demo_state
import services

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
_lock = threading.Lock()


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:7]}"


def today():
    return datetime.now().strftime("%Y-%m-%d")


def load_state():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        state = build_demo_state()
        save_state(state)
        return state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        state = build_demo_state()
        save_state(state)
        return state


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def mutate(fn):
    """Runs fn(state) under a lock and persists the result."""
    with _lock:
        state = load_state()
        result = fn(state)
        save_state(state)
        return result


def reset_demo():
    with _lock:
        save_state(build_demo_state())


# ---------------------------------------------------------------- helpers

def current_user(state):
    for e in state["employees"]:
        if e["id"] == state["currentUserId"]:
            return e
    return state["employees"][0]


def find(items, item_id):
    for i in items:
        if i["id"] == item_id:
            return i
    return None


def is_overdue(task):
    deadline = task.get("deadline")
    return bool(deadline) and task["status"] not in ("Completed", "Rejected") and deadline < today()


def display_status(task):
    return "Overdue" if is_overdue(task) else task["status"]


def match_employee(name, employees):
    n = (name or "").strip().lower()
    if not n:
        return None
    for e in employees:
        if e["fullName"].lower() == n:
            return e
    for e in employees:
        if e["fullName"].lower().split(" ")[0] == n.split(" ")[0]:
            return e
    for e in employees:
        if e["email"].split("@")[0] == n:
            return e
    return None


def visible_tasks(state, user=None):
    user = user or current_user(state)
    if user["role"] == "employee":
        return [t for t in state["tasks"] if t["employeeId"] == user["id"]]
    return list(state["tasks"])


def log(task, actor, message):
    task["activity"].append({"id": uid("a"), "at": today(), "actor": actor, "message": message})


# ---------------------------------------------------------------- actions

def set_current_user(user_id):
    def op(state):
        state["currentUserId"] = user_id
    mutate(op)


def add_meeting(data):
    meeting = dict(data)
    meeting["id"] = uid("m")
    meeting["analyzed"] = False

    def op(state):
        state["meetings"].insert(0, meeting)
    mutate(op)
    return meeting


def run_analysis(meeting_id):
    state = load_state()
    meeting = find(state["meetings"], meeting_id)
    if not meeting:
        raise ValueError("Meeting not found")
    result = services.analyze_meeting(
        meeting["transcript"], meeting["date"], [e["fullName"] for e in state["employees"]]
    )
    drafts = []
    for t in result.get("tasks", []):
        match = match_employee(t.get("owner", ""), state["employees"])
        drafts.append({
            "id": uid("draft"),
            "title": t.get("task", ""),
            "ownerName": match["fullName"] if match else t.get("owner", ""),
            "employeeId": match["id"] if match else None,
            "deadline": t.get("deadline", today()),
            "priority": t.get("priority", "Medium"),
            "confidence": t.get("confidence", 0.7),
            "sourceStatement": t.get("sourceStatement", ""),
        })

    def op(s):
        m = find(s["meetings"], meeting_id)
        if m:
            m["analyzed"] = True
    mutate(op)
    return result, drafts


def approve_drafts(meeting_id, accepted_drafts, extracted_decisions):
    """accepted_drafts: list of dicts already edited by the manager."""
    created = {"count": 0}

    def op(state):
        actor = current_user(state)["fullName"]
        new_decisions = []
        for extracted in extracted_decisions:
            text = extracted.get("decision", "").strip()
            if not text:
                continue
            if any(d["meetingId"] == meeting_id and d["text"] == text for d in state["decisions"]):
                continue
            new_decisions.append({
                "id": uid("d"), "meetingId": meeting_id, "text": text,
                "category": extracted.get("category", "General"),
                "confidence": extracted.get("confidence", 0.8),
                "createdAt": today(), "revisions": [],
            })

        new_tasks, new_notifications = [], []
        for draft in accepted_drafts:
            employee = find(state["employees"], draft.get("employeeId"))
            if not employee:
                continue
            key = draft["title"].lower()[:18]
            linked = next((d for d in new_decisions if key in d["text"].lower()), None)
            task_id = uid("t")
            new_tasks.append({
                "id": task_id, "title": draft["title"], "description": draft.get("sourceStatement", ""),
                "meetingId": meeting_id, "decisionId": linked["id"] if linked else None,
                "ownerName": employee["fullName"], "employeeId": employee["id"],
                "deadline": draft["deadline"], "priority": draft["priority"],
                "status": "Pending", "progress": 0, "confidence": draft.get("confidence", 0.8),
                "sourceStatement": draft.get("sourceStatement", ""), "approved": True,
                "createdAt": today(), "completedAt": None, "comments": [],
                "activity": [{"id": uid("a"), "at": today(), "actor": actor,
                              "message": "Task approved and assigned"}],
            })

            from ai_engine import pretty_date
            subject = f"New Task Assigned: {draft['title']}"
            body = (f"Hi {employee['fullName'].split(' ')[0]},\n\nA new task has been assigned to you "
                    f"from a recent meeting.\n\nTask: {draft['title']}\n"
                    f"Deadline: {pretty_date(draft['deadline'])}\nPriority: {draft['priority']}\n\n"
                    "Please open your DecisionFlow AI dashboard to view the complete task details and "
                    "update your progress.\n\nRegards,\nDecisionFlow AI")
            services.deliver_email(employee["email"], employee["fullName"], subject, body)
            new_notifications.append({
                "id": uid("n"), "type": "assignment", "to": employee["email"],
                "toName": employee["fullName"], "subject": subject, "body": body,
                "at": today(), "read": False, "taskId": task_id,
            })

        state["decisions"] = new_decisions + state["decisions"]
        state["tasks"] = new_tasks + state["tasks"]
        state["notifications"] = new_notifications + state["notifications"]
        created["count"] = len(new_tasks)
    mutate(op)
    return created["count"]


VALID_TASK_STATUSES = {"Pending", "In Progress", "Submitted", "Completed", "Needs Review", "Rejected"}


def normalize_task_update(patch):
    patch = dict(patch or {})
    status = patch.get("status")
    if status is not None and status not in VALID_TASK_STATUSES:
        raise ValueError("Invalid task status.")
    if "progress" in patch:
        try:
            progress = int(patch["progress"])
        except (TypeError, ValueError):
            raise ValueError("Progress must be a whole number from 0 to 100.")
        if not 0 <= progress <= 100:
            raise ValueError("Progress must be between 0 and 100.")
        patch["progress"] = progress

    if status == "Completed":
        patch["progress"] = 100
        patch["completedAt"] = today()
    elif status == "In Progress" and patch.get("progress", 0) >= 100:
        raise ValueError("An In Progress task must have progress below 100%.")
    elif status in ("Pending",):
        patch["progress"] = 0
        patch["completedAt"] = None
    elif status in ("In Progress", "Submitted", "Needs Review"):
        patch["completedAt"] = None
    elif status == "Rejected":
        patch["completedAt"] = None
    return patch


def update_task(task_id, patch, activity_message=None):
    patch = normalize_task_update(patch)
    def op(state):
        task = find(state["tasks"], task_id)
        if not task:
            return
        task.update(patch)
        if activity_message:
            log(task, current_user(state)["fullName"], activity_message)
    mutate(op)


def add_comment(task_id, text):
    def op(state):
        task = find(state["tasks"], task_id)
        if not task or not text.strip():
            return
        task["comments"].append({"id": uid("c"), "author": current_user(state)["fullName"],
                                 "text": text.strip(), "at": today()})
    mutate(op)


def submit_evidence(task_id, kind, label, note):
    state = load_state()
    task = find(state["tasks"], task_id)
    if not task:
        raise ValueError("Task not found")
    verification = services.verify_evidence(task["title"], task["description"], label, note)
    verification["at"] = today()
    verification.setdefault("overriddenBy", None)
    verification.setdefault("overriddenAt", None)
    verification["aiVerdict"] = verification["verdict"]
    verification["aiConfidence"] = verification["confidence"]
    verification["finalVerdict"] = verification["verdict"]
    status = "Completed" if verification["verdict"] == "match" else "Needs Review"
    verification["finalStatus"] = status

    def op(s):
        actor = current_user(s)["fullName"]
        t = find(s["tasks"], task_id)
        ev = {"id": uid("e"), "taskId": task_id, "kind": kind, "label": label, "note": note,
              "submittedBy": actor, "at": today(), "verification": verification}
        s["evidence"].insert(0, ev)
        log(t, actor, f"Evidence submitted: {label}")
        t["status"] = status
        t["progress"] = 100 if status == "Completed" else max(t["progress"], 80)
        t["completedAt"] = today() if status == "Completed" else t.get("completedAt")
        pct = round(verification["confidence"] * 100)
        log(t, "DecisionFlow AI", f"AI verification: {verification['verdict']} ({pct}%) → {status}")
        s["notifications"].insert(0, {
            "id": uid("n"), "type": "verification", "to": "kavita@example.com", "toName": "Kavita Rao",
            "subject": f"Evidence {verification['verdict']} for: {t['title']}",
            "body": f"{verification['summary']}\n\nConfidence: {pct}%\nResulting status: {status}",
            "at": today(), "read": False, "taskId": task_id,
        })
    mutate(op)
    return verification

def override_verification(evidence_id, decision):
    """Record a manager decision without changing the original AI verdict."""
    decision = (decision or "").strip().lower()
    if decision == "match":
        decision = "accept"
    elif decision == "mismatch":
        decision = "reject"
    if decision not in ("accept", "reject"):
        raise ValueError("Invalid evidence decision.")

    def op(state):
        ev = find(state["evidence"], evidence_id)
        if not ev or not ev.get("verification"):
            return
        actor = current_user(state)["fullName"]
        v = ev["verification"]
        ai_verdict = v.get("aiVerdict", v.get("verdict", "mismatch"))
        v["aiVerdict"] = ai_verdict
        v["aiConfidence"] = v.get("aiConfidence", v.get("confidence", 0))
        v["finalVerdict"] = "match" if decision == "accept" else "mismatch"
        v["finalStatus"] = "Completed" if decision == "accept" else "Rejected"
        v["overriddenBy"] = actor
        v["overriddenAt"] = today()

        task = find(state["tasks"], ev["taskId"])
        if task:
            task["status"] = v["finalStatus"]
            task["progress"] = 100 if decision == "accept" else min(task.get("progress", 0), 99)
            task["completedAt"] = today() if decision == "accept" else None
            log(task, actor, f"Manager override → {v['finalStatus']}")
    mutate(op)

def add_employee(data):
    def op(state):
        employee = dict(data)
        code = employee.get("employeeCode", "").strip()
        name = employee.get("fullName", "").strip()
        email = employee.get("email", "").strip().lower()
        if not code or not name or not email:
            raise ValueError("Employee code, full name and email are required.")
        if any(e.get("employeeCode", "").lower() == code.lower() for e in state["employees"]):
            raise ValueError("Employee code already exists.")
        if any(e.get("email", "").lower() == email for e in state["employees"]):
            raise ValueError("Email already exists.")
        employee["employeeCode"] = code
        employee["fullName"] = name
        employee["email"] = email
        employee["id"] = uid("u")
        employee["active"] = True
        state["employees"].append(employee)
    mutate(op)



def mark_notification_read(notification_id):
    def op(state):
        n = find(state["notifications"], notification_id)
        if n:
            n["read"] = True
    mutate(op)


def run_reminder_sweep():
    created = {"count": 0}

    def op(state):
        now = datetime.strptime(today(), "%Y-%m-%d").date()
        batch = []
        for task in state["tasks"]:
            if task["status"] in ("Completed", "Rejected"):
                continue
            employee = find(state["employees"], task.get("employeeId"))
            if not employee:
                continue
            days = (datetime.strptime(task["deadline"], "%Y-%m-%d").date() - now).days
            kind = "reminder"
            if days == 3:
                message = "Reminder: your task is due in 3 days."
            elif days == 1:
                message = "Reminder: your task is due tomorrow."
            elif days == 0:
                message = "Reminder: your task is due today."
            elif days < 0:
                message = f"Your task is overdue by {abs(days)} day(s)."
                kind = "overdue"
            else:
                continue
            if any(n.get("taskId") == task["id"] and n["type"] == kind and n["at"] == today()
                   for n in state["notifications"]):
                continue
            subject = f"{'Overdue' if kind == 'overdue' else 'Reminder'}: {task['title']}"
            body = (f"Hi {employee['fullName'].split(' ')[0]},\n\n{message}\n\n"
                    f"Task: {task['title']}\nDeadline: {task['deadline']}\n\nRegards,\nDecisionFlow AI")
            services.deliver_email(employee["email"], employee["fullName"], subject, body)
            batch.append({"id": uid("n"), "type": kind, "to": employee["email"],
                          "toName": employee["fullName"], "subject": subject, "body": body,
                          "at": today(), "read": False, "taskId": task["id"]})
        state["notifications"] = batch + state["notifications"]
        created["count"] = len(batch)
    mutate(op)
    return created["count"]