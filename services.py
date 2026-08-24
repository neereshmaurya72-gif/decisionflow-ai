"""Local rule-based service layer for DecisionFlow AI.

This project uses only the built-in heuristic/rule-based engine. No external
AI provider, API key, cloud model, or email API is required.
"""
from ai_engine import extract_structured, verify_evidence_heuristic


def analyze_meeting(transcript, meeting_date, known_owners):
    return extract_structured(transcript, meeting_date, known_owners)


def verify_evidence(task_title, task_description, evidence_label, evidence_note):
    return verify_evidence_heuristic(task_title, task_description, evidence_label, evidence_note)


def watsonx_config_summary():
    return {
        "configured": True,
        "provider": "Built-in rule-based extraction engine",
        "model": None,
    }


def email_config_summary():
    return {
        "configured": True,
        "provider": "Built-in in-app notification system",
    }


def deliver_email(to, to_name, subject, body):
    return {
        "delivered": False,
        "mode": "in-app",
        "detail": f"Notification created inside DecisionFlow AI for {to}.",
    }


def ai_mode():
    return "rule-based"


def email_mode():
    return "in-app"
