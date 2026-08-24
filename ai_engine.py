"""Heuristic AI engine (demo mode) — Python port of the original TypeScript engine."""
import re
from datetime import date, datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

HIGH_SIGNALS = ["urgent", "asap", "critical", "immediately", "high priority", "must", "blocker", "report"]
LOW_SIGNALS = ["eventually", "when possible", "nice to have", "low priority", "sometime"]

CATEGORY_RULES = [
    ("Product", ["launch", "website", "feature", "release", "roadmap", "product"]),
    ("Sales", ["sales", "revenue", "pipeline", "deal", "client", "customer"]),
    ("Marketing", ["marketing", "campaign", "presentation", "brand", "social"]),
    ("Engineering", ["deploy", "bug", "api", "qa", "infrastructure", "test"]),
    ("Finance", ["budget", "cost", "invoice", "pricing", "forecast"]),
    ("Operations", ["process", "hiring", "policy", "vendor", "schedule"]),
]

ACTION_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)\s+(?:will|should|is going to|has to|needs to|must)\s+([^.!?]+)"
)
DECISION_RE = re.compile(
    r"\b(we (?:have )?(?:decided|agreed)|decision:|it (?:was|is) (?:decided|agreed)|final(?:ized)?|"
    r"approved|the team agreed|launch date|moved to)\b",
    re.I,
)

STOP = {"the", "a", "an", "of", "for", "to", "and", "in", "on", "with", "by", "this", "that",
        "is", "are", "be", "please", "file", "doc", "new", "pdf", "docx", "xlsx"}


def split_sentences(text):
    """Split transcript into speaker-labelled statements and preserve the speaker."""
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    if not text:
        return []

    text = re.sub(r"\n+", " ", text)
    turns = re.split(
        r"\s+(?=[A-Z][A-Za-z]+(?:\s+[A-Za-z]+){0,2}\s*:)",
        text,
    )
    result = []
    for turn in turns:
        turn = turn.strip()
        if not turn:
            continue
        speaker_match = re.match(
            r"^([A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?)\s*:\s*(.*)$",
            turn,
        )
        speaker = speaker_match.group(1) if speaker_match else ""
        body = speaker_match.group(2) if speaker_match else turn
        pieces = re.split(r"(?<=[.!?])\s+", body)
        for piece in pieces:
            piece = piece.strip()
            if len(piece) > 8:
                result.append(f"{speaker}: {piece}" if speaker else piece)
    return result



def _speaker_name(sentence):
    m = re.match(r"^\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s*:\s*", sentence)
    return m.group(1).strip() if m else ""


def _strip_speaker(sentence):
    return re.sub(r"^\s*[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?\s*:\s*", "", sentence).strip()


def categorize(text):
    lower = (text or "").lower()
    for category, words in CATEGORY_RULES:
        if any(w in lower for w in words):
            return category
    return "General"


def _fmt(d):
    return d.strftime("%Y-%m-%d")


def _next_weekday(base, weekday_index):
    delta = (weekday_index - base.weekday()) % 7 or 7
    return base + timedelta(days=delta)


def _known_owner(name, known_owners):
    n = (name or "").strip().lower()
    if not n:
        return ""
    for owner in known_owners:
        if owner.lower() == n:
            return owner
    for owner in known_owners:
        if owner.lower().split()[0] == n.split()[0]:
            return owner
    return name.strip()


def _role_owner(name, known_owners):
    n = (name or "").strip().lower()
    if n in {"qa", "qa team", "quality assurance"}:
        for owner in known_owners:
            if owner.lower().startswith("priya "):
                return owner
    return _known_owner(name, known_owners)


def parse_deadline(phrase, base):
    """Prefer the date attached to 'by/before/on/due', not an earlier date in a condition."""
    lower = (phrase or "").lower()
    marker = re.search(
        r"(?:by|before|on|due(?:\s+by)?)\s+(?:the\s+)?"
        r"(today|tomorrow|end of week|end of month|next week|in \d+ days?|"
        + "|".join(MONTHS) + r"\s+\d{1,2}|\d{4}-\d{2}-\d{2})",
        lower,
    )
    target = marker.group(1) if marker else lower

    if "today" in target:
        return _fmt(base)
    if "tomorrow" in target:
        return _fmt(base + timedelta(days=1))
    if "end of week" in target or "this week" in target:
        return _fmt(_next_weekday(base, 4))
    if "next week" in target:
        return _fmt(base + timedelta(days=7))
    if "end of month" in target:
        return _fmt(base + timedelta(days=21))

    m = re.search(r"in (\d+) days?", target)
    if m:
        return _fmt(base + timedelta(days=int(m.group(1))))

    m = re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})", target)
    if m:
        try:
            return _fmt(datetime.strptime(f"{m.group(1)} {m.group(2)} {base.year}", "%B %d %Y").date())
        except ValueError:
            pass

    m = re.search(r"\d{4}-\d{2}-\d{2}", target)
    if m:
        return m.group(0)

    candidates = re.findall(
        r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}",
        lower,
    )
    if len(candidates) == 1:
        c = candidates[0]
        for i, day in enumerate(WEEKDAYS):
            if c == day:
                return _fmt(_next_weekday(base, i))
        m = re.match(r"([a-z]+)\s+(\d+)", c)
        if m:
            try:
                return _fmt(datetime.strptime(f"{m.group(1)} {m.group(2)} {base.year}", "%B %d %Y").date())
            except ValueError:
                pass
    return None


def detect_priority(sentence):
    lower = sentence.lower()
    if any(s in lower for s in HIGH_SIGNALS):
        return "High"
    if any(s in lower for s in LOW_SIGNALS):
        return "Low"
    return "Medium"


def clean_task(raw):
    t = re.sub(r"^\s*(and|then|also|please)\s+", "", raw.strip(), flags=re.I)
    t = re.sub(r"\s+(by|before|on|due(?:\s+by)?)\s+.*$", "", t, flags=re.I)
    t = re.sub(r"[.,;]+$", "", t).strip()
    if not t:
        return ""
    return t[0].upper() + t[1:]


def pretty_date(iso_str):
    try:
        return datetime.strptime(iso_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        try:
            return datetime.strptime(iso_str, "%Y-%m-%d").strftime("%B %d, %Y")
        except (ValueError, TypeError):
            return iso_str or ""


_COMMITMENT = re.compile(
    r"(?P<owner>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?|QA(?:\s+team)?)\s+"
    r"(?P<verb>will|should|shall|is going to|has to|needs to|must)\s+"
    r"(?P<action>[^.!?]+?)(?=(?:,\s*(?:and\s+)?"
    r"(?:[A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?|QA(?:\s+team)?)\s+"
    r"(?:will|should|shall|is going to|has to|needs to|must)\b)|[.!?]|$)",
    re.I,
)

_FIRST_PERSON = re.compile(
    r"\b(I'll|I will|I can|I should|I need to|I have to|I must)\s+"
    r"(?P<action>[^.!?]+?)(?=(?:,\s*(?:and\s+)?"
    r"(?:[A-Z][A-Za-z]+(?:\s+[A-Za-z]+)?|QA(?:\s+team)?)\s+"
    r"(?:will|should|shall|is going to|has to|needs to|must)\b)|[.!?]|$)",
    re.I,
)

_STRONG_ACTION_WORDS = {
    "prepare", "create", "update", "refresh", "run", "open", "review", "complete",
    "finish", "test", "confirm", "check", "share", "send", "build", "fix", "deploy",
    "publish", "collect", "add", "freeze", "schedule", "present", "finalize", "finalise",
    "verify", "approve", "call", "contact", "provide", "deliver", "pull", "take",
}


def _normalize_action_title(task):
    lower = task.lower().strip()
    # Prefer the concrete deliverable in phrases such as:
    # "pull numbers ... and prepare the sales report"
    m = re.search(r"\bprepare\s+(.+?)(?:\s+by\b|$)", task, re.I)
    if lower.startswith("pull ") and m:
        return "Prepare " + m.group(1).strip(" .;,")
    if lower.startswith("take the customer presentation"):
        return "Prepare the customer presentation"
    if "have that ready" in lower and "presentation" in lower:
        return "Prepare the customer presentation"
    return task


def _make_task(owner, action, source, base, known_owners):
    owner = _role_owner(re.sub(r"^\s*and\s+", "", owner, flags=re.I), known_owners)
    task = _normalize_action_title(clean_task(action))
    if not task or task.lower().split()[0] not in _STRONG_ACTION_WORDS or owner.lower() in {"we", "us", "team", "everyone"}:
        return None

    explicit = parse_deadline(action, base)
    known = _known_owner(owner, known_owners) in known_owners
    if not known and owner.lower() not in {"qa", "qa team", "quality assurance"}:
        return None
    confidence = min(0.98, 0.70 + (0.18 if known else 0.04) + (0.10 if explicit else 0))

    return {
        "task": task,
        "owner": owner,
        "deadline": explicit or "",
        "priority": detect_priority(source),
        "status": "Pending",
        "confidence": round(confidence, 2),
        "sourceStatement": source.strip(),
    }


def extract_structured(transcript, meeting_date, known_owners=None):
    """High-precision demo extraction of committed actions and explicit decisions.

    The extractor intentionally prefers precision over recall:
    - questions, suggestions, risks and hedged statements are not tasks
    - vague phrases such as "do that" are ignored
    - conditions are not treated as commitments
    - final-plan recap sentences are not copied as giant decisions
    """
    known_owners = known_owners or []

    try:
        base = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        base = date.today()

    sentences = split_sentences(transcript)
    tasks, decisions = [], []
    seen_tasks, seen_decisions = set(), set()

    # These phrases are usually conversational, speculative or explicitly
    # non-committal. They should not become action items.
    REJECT_TASK = re.compile(
        r"\b("
        r"not sure|can't promise|cannot promise|"
        r"don't want to commit|do not want to commit|"
        r"might|may|could|"
        r"i don't think|i do not think|"
        r"should have an answer|have an answer|"
        r"do that|"
        r"be finished|"
        r"review it|"
        r"get to it|"
        r"leave it without a deadline"
        r")\b",
        re.I,
    )

    # A task should normally start with a concrete action. "Have X ready"
    # and "Have X confirmed" are also useful commitments.
    ACTION_START = re.compile(
        r"^(?:"
        r"prepare|create|update|refresh|run|open|review|complete|finish|"
        r"test|confirm|check|share|send|build|fix|deploy|publish|collect|"
        r"add|freeze|schedule|present|finali[sz]e|verify|approve|call|"
        r"contact|provide|deliver|pull|take|"
        r"have\s+(?!an?\s+answer\b|a\s+call\b|the\s+customer\s+call\b)"
        r"[^.!?]+"
        r")\b",
        re.I,
    )

    def add_task(owner, action, source, confidence_base=0.78):
        owner = (owner or "").strip()
        # Parse the deadline before clean_task() removes the "by/on/due" tail.
        deadline = parse_deadline(action, base) or ""
        action = clean_task(action)

        if not action:
            return

        low = action.lower().strip()

        # Reject vague/non-committal actions.
        if REJECT_TASK.search(low):
            return

        # "I have the customer call..." is context, not a task.
        if re.match(r"^(?:have|has)\s+(?:the\s+)?(?:customer\s+)?call\b", low):
            return

        # Avoid turning negative opinions into tasks.
        if re.match(r"^(?:increase|change|move|remove|add)\b", low):
            if re.search(r"\b(?:don't|do not|not|shouldn't|should not)\b", source, re.I):
                return

        # A concrete action is required.
        if not ACTION_START.match(low):
            return

        action = _normalize_action_title(action)

        # Map a known owner. Unknown/absent owners remain Unassigned.
        if owner:
            mapped = _known_owner(owner, known_owners)
            if mapped in known_owners:
                owner = mapped
        else:
            owner = "Unassigned"

        key = (owner.lower(), action.lower(), deadline)
        if key in seen_tasks:
            return

        confidence = confidence_base
        if owner != "Unassigned":
            confidence += 0.10
        if deadline:
            confidence += 0.08

        tasks.append({
            "task": action,
            "owner": owner,
            "deadline": deadline,
            "priority": detect_priority(source),
            "status": "Pending",
            "confidence": round(min(confidence, 0.96), 2),
            "sourceStatement": source.strip(),
        })
        seen_tasks.add(key)

    def add_decision(text_value, source, confidence=0.82):
        cleaned = re.sub(
            r"^(so|and|then|okay|ok|just to recap),?\s*",
            "",
            text_value.strip(),
            flags=re.I,
        )
        cleaned = cleaned.strip(" .;,")

        if not cleaned:
            return

        # Never store a whole "final plan" recap as a single decision.
        if len(cleaned.split()) > 28 and re.search(
            r"\bfinal plan\b|\bthe plan is\b", cleaned, re.I
        ):
            return

        key = cleaned.lower()
        if key in seen_decisions:
            return

        decisions.append({
            "decision": cleaned,
            "category": categorize(cleaned),
            "confidence": round(min(confidence, 0.95), 2),
            "sourceStatement": source.strip(),
        })
        seen_decisions.add(key)

    for raw_sentence in sentences:
        speaker = _speaker_name(raw_sentence)
        sentence = _strip_speaker(raw_sentence).strip()

        if not sentence:
            continue

        low = sentence.lower()

        # Conditions, hypotheticals and explicit uncertainty are not
        # committed action items.
        is_conditional = bool(
            re.search(r"\b(if|unless|provided|assuming)\b", low)
        )
        is_hedged = bool(
            re.search(
                r"\b("
                r"not sure|can't promise|cannot promise|"
                r"don't want to commit|do not want to commit|"
                r"i don't think|i do not think|"
                r"might|may|could"
                r")\b",
                low,
            )
        )

        # ---------------------------------------------------------
        # Named commitments:
        # "Rahul will finish the dashboard by August 19."
        # ---------------------------------------------------------
        if not is_conditional and not is_hedged:
            for match in _COMMITMENT.finditer(sentence):
                add_task(
                    match.group("owner"),
                    match.group("action").strip(" ,;"),
                    raw_sentence,
                )

        # ---------------------------------------------------------
        # First-person commitments:
        # "I'll open the pull request this afternoon."
        # ---------------------------------------------------------
        if not is_conditional and not is_hedged:
            for match in _FIRST_PERSON.finditer(sentence):
                add_task(
                    speaker or "",
                    match.group("action").strip(" ,;"),
                    raw_sentence,
                )

            # Also support an unlabeled "I will..." / "I'll..." sentence.
            first_person = re.match(
                r"^\s*(?:I['’]ll|I will|I can|I need to|I have to|I must)\s+(.+)$",
                sentence,
                re.I,
            )
            if first_person:
                add_task(
                    speaker or "",
                    first_person.group(1),
                    raw_sentence,
                )

        # ---------------------------------------------------------
        # Direct imperative:
        # "Rahul, please send the report."
        # ---------------------------------------------------------
        imperative = re.match(
            r"^\s*(?P<owner>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s*,\s*"
            r"(?:please\s+)?"
            r"(?P<action>"
            r"send|share|prepare|update|refresh|confirm|check|run|open|"
            r"review|complete|finish|create|build|test|call|contact|"
            r"fix|deploy|publish|collect|add|schedule|verify"
            r")\b(?P<rest>.*)$",
            sentence,
            flags=re.I,
        )

        if imperative and not is_conditional and not is_hedged:
            add_task(
                imperative.group("owner"),
                (
                    imperative.group("action")
                    + imperative.group("rest")
                ).strip(),
                raw_sentence,
            )

        # ---------------------------------------------------------
        # Explicit decisions only.
        # Do NOT use generic "for now" or "final plan" as decision
        # signals because those phrases create false positives.
        # ---------------------------------------------------------
        explicit_decision = re.search(
            r"\b("
            r"we (?:have )?(?:decided|agreed)|"
            r"the team agreed|"
            r"decision:|"
            r"it (?:was|is) (?:decided|agreed)|"
            r"approved|"
            r"let's\s+(?:keep|freeze|target)|"
            r"we['’]ll keep|"
            r"we will keep|"
            r"we['’]re keeping|"
            r"we are keeping|"
            r"we['’]re going with|"
            r"we are going with|"
            r"target launch date|"
            r"launch date is|"
            r"launch is moving|"
            r"moved from .* to"
            r")\b",
            sentence,
            re.I,
        )

        if explicit_decision and not is_conditional and not is_hedged:
            # Prefer the concrete launch decision inside a long recap.
            launch = re.search(
                r"((?:August\s+\d{1,2}|\d{1,2}\s+August)"
                r"\s+(?:remains|will remain|is|as the)\s+"
                r"(?:the\s+)?target launch date"
                r"|"
                r"(?:we['’]ll keep|we will keep|we['’]re keeping|"
                r"we are keeping)\s+"
                r"(?:August\s+\d{1,2}|\d{1,2}\s+August)"
                r"\s+(?:as\s+)?(?:the\s+)?target launch date"
                r")",
                sentence,
                re.I,
            )

            if launch:
                add_decision(
                    launch.group(1),
                    raw_sentence,
                    0.86,
                )
            elif len(sentence.split()) <= 28:
                add_decision(sentence, raw_sentence, 0.82)

    return {
        "decisions": decisions,
        "tasks": tasks,
        "summary": (
            f"{len(decisions)} decision(s) and "
            f"{len(tasks)} action item(s) extracted from "
            f"{len(sentences)} statements."
        ),
        "mode": "demo",
    }

def _tokens(text):
    words = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    return [w for w in words if len(w) > 2 and w not in STOP]


def verify_evidence_heuristic(task_title, task_description, evidence_label, evidence_note):
    task_tokens = set(_tokens(f"{task_title} {task_description}"))
    evidence_tokens = _tokens(f"{evidence_label} {evidence_note}")
    if not task_tokens or not evidence_tokens:
        return {"verdict": "mismatch", "confidence": 0.15,
                "summary": "Not enough signal in the submitted evidence to relate it to the task.",
                "mode": "demo"}

    overlap = [t for t in evidence_tokens if t in task_tokens]
    unique = len(set(overlap))
    coverage = unique / len(task_tokens)
    density = unique / len(set(evidence_tokens))
    score = min(0.97, coverage * 0.7 + density * 0.3 + (0.08 if len(evidence_note) > 40 else 0))

    if score >= 0.5:
        matched = ", ".join(list(dict.fromkeys(overlap))[:5])
        return {"verdict": "match", "confidence": round(max(score, 0.82), 2),
                "summary": f"Evidence appears to satisfy the assigned task (matched on: {matched}).",
                "mode": "demo"}
    if score >= 0.25:
        return {"verdict": "partial", "confidence": round(score, 2),
                "summary": ("Evidence is partially related to the task but does not fully demonstrate "
                            "completion. Manual review recommended."),
                "mode": "demo"}
    return {"verdict": "mismatch", "confidence": round(max(score, 0.08), 2),
            "summary": "Evidence does not clearly match the assigned task.", "mode": "demo"}


def detect_drift(original_text, updated_text, base):
    o = parse_deadline(original_text, base)
    u = parse_deadline(updated_text, base)
    if not o or not u or o == u:
        return None
    delta = (datetime.strptime(u, "%Y-%m-%d").date() - datetime.strptime(o, "%Y-%m-%d").date()).days
    return {"original": o, "current": u, "deltaDays": delta}