"""DecisionFlow AI — Flask application entry point.

Run with:  python app.py    ->  http://127.0.0.1:5000
"""
import os
from datetime import datetime

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

import metrics
import services
import store
from ai_engine import detect_drift, pretty_date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "decisionflow-ai-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024


@app.errorhandler(403)
def forbidden(_error):
    return render_template("403.html"), 403



NAV = [
    {"to": "dashboard", "label": "Dashboard", "icon": "grid", "roles": ["admin", "manager", "employee"]},
    {"to": "meetings", "label": "Meetings", "icon": "video", "roles": ["admin", "manager"]},
    {"to": "decisions", "label": "Decisions", "icon": "check", "roles": ["admin", "manager"]},
    {"to": "tasks", "label": "Tasks", "icon": "file", "roles": ["admin", "manager", "employee"]},
    {"to": "chain", "label": "Meeting → Execution", "icon": "branch", "roles": ["admin", "manager"]},
    {"to": "employees", "label": "Employees", "icon": "users", "roles": ["admin", "manager"]},
    {"to": "evidence", "label": "Evidence", "icon": "sparkles", "roles": ["admin", "manager"]},
    {"to": "analytics", "label": "Analytics", "icon": "chart", "roles": ["admin", "manager"]},
    {"to": "notifications", "label": "Notifications", "icon": "bell", "roles": ["admin", "manager", "employee"]},
    {"to": "settings", "label": "Settings", "icon": "settings", "roles": ["admin", "manager", "employee"]},
]


def require_roles(*roles):
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            state = store.load_state()
            user = store.current_user(state)
            if user.get("role") not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def can_access_task(task, user):
    return user.get("role") in ("admin", "manager") or task.get("employeeId") == user.get("id")


@app.context_processor
def inject_globals():
    state = store.load_state()
    user = store.current_user(state)
    unread = len([n for n in state["notifications"]
                  if not n["read"] and (n["to"] == user["email"] if user["role"] == "employee" else True)])
    return {
        "nav": [item for item in NAV if user["role"] in item["roles"]],
        "current_user": user,
        "all_employees": [e for e in state["employees"] if e["active"]],
        "unread_count": unread,
        "ai_mode": services.ai_mode(),
        "app_name": "DecisionFlow AI",
    }


@app.template_filter("pretty_date")
def pretty_date_filter(value):
    return pretty_date(value) if value else "—"


@app.template_filter("pct")
def pct_filter(value):
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("status_slug")
def status_slug(value):
    return (value or "").lower().replace(" ", "-")


# ------------------------------------------------------------------ session

@app.post("/switch-user")
def switch_user():
    store.set_current_user(request.form.get("user_id", ""))
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------------ dashboard

@app.get("/")
def dashboard():
    state = store.load_state()
    user = store.current_user(state)
    tasks = store.visible_tasks(state, user)
    stats = metrics.overview_stats(state["meetings"], state["decisions"], tasks)
    upcoming = sorted(
        [t for t in tasks if t["status"] not in ("Completed", "Rejected")],
        key=lambda t: t["deadline"],
    )[:6]
    return render_template(
        "dashboard.html",
        stats=stats,
        tasks=tasks,
        upcoming=upcoming,
        status_data=metrics.tasks_by_status(tasks),
        employee_data=metrics.tasks_by_employee(state["tasks"], state["employees"]),
        trend=metrics.completion_over_time(tasks),
        meetings=state["meetings"][:4],
        is_overdue=store.is_overdue,
        display_status=store.display_status,
        days_left=metrics.days_left,
    )


# ------------------------------------------------------------------ meetings

@app.get("/meetings")
@require_roles("admin", "manager")
def meetings():
    state = store.load_state()
    rows = [{"meeting": m, "exec": metrics.meeting_execution(m, state["tasks"])}
            for m in state["meetings"]]
    return render_template("meetings.html", rows=rows)


@app.route("/meetings/new", methods=["GET", "POST"])
@require_roles("admin", "manager")
def meeting_new():
    if request.method == "POST":
        transcript = request.form.get("transcript", "").strip()
        upload = request.files.get("transcript_file")
        if upload and upload.filename:
            try:
                transcript = upload.read().decode("utf-8", errors="ignore").strip() or transcript
            except Exception:
                pass
        if len(transcript) < 10:
            flash("Please paste a transcript (or upload a .txt file) before analyzing.", "error")
            return redirect(url_for("meeting_new"))
        participants = [p.strip() for p in request.form.get("participants", "").split(",") if p.strip()]
        meeting = store.add_meeting({
            "title": request.form.get("title", "Untitled meeting").strip() or "Untitled meeting",
            "date": request.form.get("date") or store.today(),
            "organizer": request.form.get("organizer", "").strip(),
            "participants": participants,
            "durationMinutes": int(request.form.get("duration") or 30),
            "recordingName": request.form.get("recording_name", "").strip() or None,
            "transcript": transcript,
        })
        flash("Meeting saved. Running AI analysis…", "success")
        return redirect(url_for("meeting_detail", meeting_id=meeting["id"], analyze=1))
    return render_template("meeting_new.html", today=store.today())


@app.get("/meetings/<meeting_id>")
@require_roles("admin", "manager")
def meeting_detail(meeting_id):
    state = store.load_state()
    meeting = store.find(state["meetings"], meeting_id)
    if not meeting:
        abort(404)
    drafts, result = [], None
    if request.args.get("analyze"):
        result, drafts = store.run_analysis(meeting_id)
        state = store.load_state()
    tasks = [t for t in state["tasks"] if t["meetingId"] == meeting_id]
    decisions = [d for d in state["decisions"] if d["meetingId"] == meeting_id]
    return render_template(
        "meeting_detail.html", meeting=meeting, tasks=tasks, decisions=decisions,
        drafts=drafts, result=result, employees=state["employees"],
        execution=metrics.meeting_execution(meeting, state["tasks"]),
        display_status=store.display_status,
    )


@app.post("/meetings/<meeting_id>/approve")
@require_roles("admin", "manager")
def meeting_approve(meeting_id):
    accepted = []
    for key in request.form.getlist("draft_id"):
        if request.form.get(f"approve_{key}") != "on":
            continue
        employee_id = request.form.get(f"employee_{key}") or None
        if not employee_id:
            continue
        accepted.append({
            "title": request.form.get(f"title_{key}", "").strip(),
            "employeeId": employee_id,
            "deadline": request.form.get(f"deadline_{key}") or "",
            "priority": request.form.get(f"priority_{key}", "Medium"),
            "confidence": float(request.form.get(f"confidence_{key}") or 0.8),
            "sourceStatement": request.form.get(f"source_{key}", ""),
        })
    decisions = []
    for i, text in enumerate(request.form.getlist("decision_text")):
        if request.form.get(f"decision_keep_{i}") != "on":
            continue
        decisions.append({
            "decision": text,
            "category": request.form.getlist("decision_category")[i],
            "confidence": float(request.form.getlist("decision_confidence")[i] or 0.8),
        })
    count = store.approve_drafts(meeting_id, accepted, decisions)
    flash(f"{count} task(s) assigned and notification email(s) queued.", "success")
    return redirect(url_for("meeting_detail", meeting_id=meeting_id))


# ------------------------------------------------------------------ decisions

@app.get("/decisions")
@require_roles("admin", "manager")
def decisions():
    state = store.load_state()
    rows = []
    for d in state["decisions"]:
        meeting = store.find(state["meetings"], d["meetingId"])
        drift = None
        if d["revisions"]:
            last = d["revisions"][-1]
            drift = detect_drift(d["text"], last["text"],
                                 datetime.strptime(d["createdAt"], "%Y-%m-%d").date())
        rows.append({"decision": d, "meeting": meeting, "drift": drift,
                     "tasks": [t for t in state["tasks"] if t["decisionId"] == d["id"]]})
    return render_template("decisions.html", rows=rows)


# ------------------------------------------------------------------ tasks

@app.get("/tasks")
def tasks():
    state = store.load_state()
    all_tasks = store.visible_tasks(state)
    status = request.args.get("status", "All")
    priority = request.args.get("priority", "All")
    owner = request.args.get("owner", "All")
    query = request.args.get("q", "").strip().lower()

    rows = all_tasks
    if status != "All":
        rows = [t for t in rows if store.display_status(t) == status]
    if priority != "All":
        rows = [t for t in rows if t["priority"] == priority]
    if owner != "All":
        rows = [t for t in rows if t["employeeId"] == owner]
    if query:
        rows = [t for t in rows if query in t["title"].lower() or query in t["ownerName"].lower()]
    rows = sorted(rows, key=lambda t: t["deadline"])
    return render_template("tasks.html", rows=rows, status=status, priority=priority,
                           owner=owner, q=request.args.get("q", ""),
                           display_status=store.display_status, days_left=metrics.days_left)


@app.get("/tasks/<task_id>")
def task_detail(task_id):
    state = store.load_state()
    task = store.find(state["tasks"], task_id)
    if not task:
        abort(404)
    return render_template(
        "task_detail.html", task=task,
        meeting=store.find(state["meetings"], task["meetingId"]),
        decision=store.find(state["decisions"], task["decisionId"]) if task["decisionId"] else None,
        evidence=[e for e in state["evidence"] if e["taskId"] == task_id],
        display_status=store.display_status, days_left=metrics.days_left,
    )


@app.post("/tasks/<task_id>/status")
def task_status(task_id):
    new_status = request.form.get("status", "Pending")
    progress = int(request.form.get("progress") or 0)
    patch = {"status": new_status, "progress": progress}
    if new_status == "Completed":
        patch["completedAt"] = store.today()
        patch["progress"] = 100
    try:
        store.update_task(task_id, patch, f"Status changed to {new_status} ({patch['progress']}%)")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("task_detail", task_id=task_id))
    flash("Task updated.", "success")
    return redirect(url_for("task_detail", task_id=task_id))


@app.post("/tasks/<task_id>/comment")
def task_comment(task_id):
    store.add_comment(task_id, request.form.get("text", ""))
    return redirect(url_for("task_detail", task_id=task_id))


@app.post("/tasks/<task_id>/evidence")
def task_evidence(task_id):
    kind = request.form.get("kind", "file")
    label = request.form.get("label", "").strip()
    upload = request.files.get("evidence_file")
    if upload and upload.filename:
        label = upload.filename
    if not label:
        flash("Add a file, URL or description before submitting evidence.", "error")
        return redirect(url_for("task_detail", task_id=task_id))
    verification = store.submit_evidence(task_id, kind, label, request.form.get("note", "").strip())
    flash(f"AI verification: {verification['verdict']} "
          f"({round(verification['confidence'] * 100)}%). {verification['summary']}", "success")
    return redirect(url_for("task_detail", task_id=task_id))


@app.post("/evidence/<evidence_id>/override")
@require_roles("admin", "manager")
def evidence_override(evidence_id):
    store.override_verification(evidence_id, request.form.get("verdict", "match"))
    flash("Verification overridden.", "success")
    return redirect(request.referrer or url_for("evidence"))


# ------------------------------------------------------------------ chain / employees / evidence

@app.get("/chain")
@require_roles("admin", "manager")
def chain():
    state = store.load_state()
    rows = []
    for m in state["meetings"]:
        m_decisions = [d for d in state["decisions"] if d["meetingId"] == m["id"]]
        m_tasks = [t for t in state["tasks"] if t["meetingId"] == m["id"]]
        task_ids = {t["id"] for t in m_tasks}
        rows.append({
            "meeting": m, "decisions": m_decisions, "tasks": m_tasks,
            "evidence": [e for e in state["evidence"] if e["taskId"] in task_ids],
            "exec": metrics.meeting_execution(m, state["tasks"]),
        })
    return render_template("chain.html", rows=rows, display_status=store.display_status)


@app.route("/employees", methods=["GET", "POST"])
@require_roles("admin", "manager")
def employees():
    if request.method == "POST":
        try:
            store.add_employee({
                "employeeCode": request.form.get("employeeCode", "").strip(),
                "fullName": request.form.get("fullName", "").strip(),
                "email": request.form.get("email", "").strip(),
                "department": request.form.get("department", "").strip(),
                "jobRole": request.form.get("jobRole", "").strip(),
                "role": request.form.get("role", "employee"),
                "active": True,
            })
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("employees"))
        flash("Employee added.", "success")
        return redirect(url_for("employees"))
    state = store.load_state()
    rows = []
    for e in state["employees"]:
        own = [t for t in state["tasks"] if t["employeeId"] == e["id"]]
        rows.append({
            "employee": e, "total": len(own),
            "completed": len([t for t in own if t["status"] == "Completed"]),
            "overdue": len([t for t in own if store.is_overdue(t)]),
        })
    return render_template("employees.html", rows=rows)


@app.get("/evidence")
@require_roles("admin", "manager")
def evidence():
    state = store.load_state()
    rows = [{"evidence": e, "task": store.find(state["tasks"], e["taskId"])}
            for e in state["evidence"]]
    return render_template("evidence.html", rows=rows,
                           accuracy=metrics.verification_accuracy(state["evidence"]))


# ------------------------------------------------------------------ analytics / notifications / settings

@app.get("/analytics")
@require_roles("admin", "manager")
def analytics():
    state = store.load_state()
    tasks_all = state["tasks"]
    return render_template(
        "analytics.html",
        stats=metrics.overview_stats(state["meetings"], state["decisions"], tasks_all),
        status_data=metrics.tasks_by_status(tasks_all),
        employee_data=metrics.tasks_by_employee(tasks_all, state["employees"]),
        trend=metrics.completion_over_time(tasks_all),
        avg_days=metrics.average_completion_days(tasks_all),
        accuracy=metrics.verification_accuracy(state["evidence"]),
        meeting_rows=[{"meeting": m, "exec": metrics.meeting_execution(m, tasks_all)}
                      for m in state["meetings"]],
    )


@app.get("/notifications")
def notifications():
    state = store.load_state()
    user = store.current_user(state)
    items = state["notifications"]
    if user["role"] == "employee":
        items = [n for n in items if n["to"] == user["email"]]
    return render_template("notifications.html", items=items,
                           email_mode=services.email_mode())


@app.post("/notifications/<notification_id>/read")
def notification_read(notification_id):
    store.mark_notification_read(notification_id)
    return redirect(url_for("notifications"))


@app.post("/notifications/sweep")
def notification_sweep():
    count = store.run_reminder_sweep()
    flash(f"Reminder sweep created {count} notification(s).", "success")
    return redirect(url_for("notifications"))


@app.get("/settings")
def settings():
    return render_template(
        "settings.html",
        ai_service=services.watsonx_config_summary(),
        email_service=services.email_config_summary(),
    )


@app.post("/settings/reset")
@require_roles("admin", "manager")
def settings_reset():
    store.reset_demo()
    flash("Demo data restored.", "success")
    return redirect(url_for("settings"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    store.load_state()  # seed data/state.json on first run
    app.run(host="127.0.0.1", port=5000, debug=True)