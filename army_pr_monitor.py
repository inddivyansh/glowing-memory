from __future__ import annotations

import csv
import json
import logging
import os
import random as r
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ollama
import schedule
from dotenv import load_dotenv
from instagrapi import Client


ROOT = Path(__file__).resolve().parent
SESSION_FILE = ROOT / ".instagram_session.json"
AUDIT_FILE = ROOT / "audit_log.csv"
LOG_FILE = ROOT / "monitor.log"


@dataclass(frozen=True)
class AuditRecord:
    media_id: str
    username: str
    permalink: str
    caption: str
    detected_issue: str
    confidence: float
    comment_text: str
    status: str
    collected_at: str


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}. Add it to .env before running this program.")
    return value


def _extract_login_error(client: Client, exc: Exception) -> str:
    """Extract a friendly explanation from Instagram's response payload when login fails."""
    raw_text = ""
    try:
        if getattr(client, "last_json", None):
            raw_text = json.dumps(client.last_json)
        elif getattr(client, "last_response", None) and hasattr(client.last_response, "text"):
            raw_text = client.last_response.text
    except Exception:
        raw_text = ""

    if "Incorrect password" in raw_text or "The password you entered is incorrect" in raw_text:
        return "Incorrect password. The password provided in .env was rejected by Instagram."
    if "two_factor" in raw_text or "two_step" in raw_text:
        return "Two-factor authentication is required for this account."
    if "checkpoint_required" in raw_text or "challenge_required" in raw_text:
        return "Instagram challenge/checkpoint required. Log into Instagram in your browser to verify the device."
    if "feedback_required" in raw_text or "Please wait a few minutes" in raw_text:
        return "Instagram temporary rate limit/action block. Please wait before attempting to log in again."
    return str(exc)


def login(client: Client, username: str = "", password: str = "", sessionid: str = "") -> None:
    """Reuse a stored session when valid, otherwise log in and save it."""
    # 1. Try loading existing saved session
    if SESSION_FILE.exists():
        try:
            client.load_settings(SESSION_FILE)
            client.get_timeline_feed()
            logging.info("Logged in using saved session")
            return
        except Exception as exc:
            logging.warning("Saved session is invalid or expired: %s", exc)
            try:
                old_settings = client.get_settings()
                client.set_settings({})
                if "uuids" in old_settings:
                    client.set_uuids(old_settings["uuids"])
            except Exception:
                pass

    # 2. Login via Session ID if provided (most reliable method to bypass bot checks)
    if sessionid:
        logging.info("Logging in using INSTAGRAM_SESSIONID...")
        try:
            client.login_by_sessionid(sessionid)
            client.dump_settings(SESSION_FILE)
            logging.info("Logged in using session ID and saved session")
            return
        except Exception as exc:
            err = _extract_login_error(client, exc)
            raise RuntimeError(f"Session ID login failed: {err}") from exc

    # 3. Standard login with CAA and legacy fallback
    logging.info("Attempting login with username and password...")
    try:
        client.login(username, password)
    except Exception as exc:
        err = _extract_login_error(client, exc)
        # If it's explicitly an incorrect password or 2FA, don't retry legacy as it's guaranteed to fail
        if "Incorrect password" in err or "Two-factor" in err:
            raise RuntimeError(err) from exc
        logging.warning("Standard login failed (%s). Retrying with legacy flow...", err)
        try:
            client.login_legacy(username, password)
        except Exception as legacy_exc:
            legacy_err = _extract_login_error(client, legacy_exc)
            raise RuntimeError(f"{err} | Legacy fallback failed: {legacy_err}") from exc

    client.dump_settings(SESSION_FILE)
    logging.info("Logged in and saved a session")


def analyse_caption(caption: str, model: str, official_source: str) -> dict[str, Any] | None:
    """Return an analysis draft when a caption makes a factual claim."""
    prompt = f"""You support a public-information team responding to misinformation
about the Indian Army. You are triaging captions for a human reviewer.
Return JSON only with these keys: candidate (boolean), issue (string), confidence
(number from 0 to 1), draft (string), reviewer_notes (string).

Set candidate to true only if the caption makes a specific, checkable factual
claim about the Indian Army which could materially mislead readers if false or
missing important context. Prioritize fabricated operational claims, false
attribution, altered media claims, and claims contradicted by a primary source.
Do not flag criticism, political opinions, satire, grief, or personal accounts
solely because they are unflattering.

Your draft is a starting point, not a published response. Make it clear,
professional and factual: directly correct the specific assertion *only after
the reviewer verifies it*, point to the verified official position, and include
the official information source below. Do not insult, threaten, mock, diagnose
motives, use hashtags, or claim certainty that has not been verified. Keep it
below 240 characters. If there is no suitable factual claim, set candidate false
and leave draft empty.

Official information source: {official_source}

Caption:
{caption[:1500] or '(no caption)'}"""
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0},
        )
        result = json.loads(response["message"]["content"])
    except Exception as exc:
        logging.warning("Could not analyse caption: %s", exc)
        return None

    if not isinstance(result, dict) or result.get("candidate") is not True:
        return None
    try:
        confidence = float(result.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1 or confidence < 0.70:
        return None
    return result


def read_existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as file:
        return {row.get("media_id", "") for row in csv.DictReader(file) if row.get("media_id")}


def append_audit_log(record: AuditRecord) -> None:
    write_header = not AUDIT_FILE.exists()
    with AUDIT_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(AuditRecord.__dataclass_fields__.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(record))
    logging.info("Audit logged for media %s (status: %s)", record.media_id, record.status)


def check_user(client: Client, user_id: str, follower_threshold: int = 0, follow_businesses: bool = True) -> bool:
    if follower_threshold <= 0 and follow_businesses:
        return True
    try:
        user = client.user_info(user_id)
    except Exception as exc:
        logging.warning("Could not fetch user %s: %s", user_id, exc)
        return False
    if not follow_businesses and getattr(user, "is_business", False):
        return False
    if follower_threshold > 0 and getattr(user, "follower_count", 0) >= follower_threshold:
        return False
    return True


def process_hashtag(
    client: Client,
    hashtag: str,
    model: str,
    official_source: str,
    max_comments: int = 3,
    min_delay: int = 60,
    max_delay: int = 180,
    fetch_amount: int = 25,
    follower_threshold: int = 0,
    follow_businesses: bool = True,
) -> int:
    existing_ids = read_existing_ids(AUDIT_FILE)
    logging.info("Starting session for #%s (target max %d comment(s))", hashtag, max_comments)
    try:
        media_items = client.hashtag_medias_recent(hashtag, amount=fetch_amount)
    except Exception as exc:
        logging.error("Could not retrieve posts for #%s: %s", hashtag, exc)
        return 0

    r.shuffle(media_items)
    comments_left = 0

    for media in media_items:
        if comments_left >= max_comments:
            break

        media_id = str(media.id)
        if media_id in existing_ids:
            continue

        username = getattr(media.user, "username", "unknown")
        user_id = str(getattr(media.user, "pk", ""))

        if user_id and not check_user(client, user_id, follower_threshold, follow_businesses):
            time.sleep(r.uniform(3, 8))
            continue

        caption = (media.caption_text or "").strip()
        analysis = analyse_caption(caption, model, official_source)
        if not analysis:
            continue

        comment_text = str(analysis.get("draft", "")).strip()[:240]
        if not comment_text:
            continue

        status = "pending"
        try:
            client.media_comment(media.id, comment_text)
            status = "posted"
            comments_left += 1
            logging.info("Commented on @%s (%s): \"%s\"", username, media.id, comment_text)
        except Exception as exc:
            status = f"failed: {exc}"
            logging.error("Failed to comment on @%s (%s): %s", username, media.id, exc)

        record = AuditRecord(
            media_id=media_id,
            username=username,
            permalink=f"https://www.instagram.com/p/{media.code}/",
            caption=caption.replace("\n", " "),
            detected_issue=str(analysis.get("issue", "Checkable factual claim")),
            confidence=float(analysis["confidence"]),
            comment_text=comment_text,
            status=status,
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        append_audit_log(record)
        existing_ids.add(media_id)

        if status == "posted":
            delay = r.uniform(min_delay, max_delay)
            logging.info("Waiting %.0fs before next action...", delay)
            time.sleep(delay)

    logging.info("Session complete for #%s - commented on %d post(s)", hashtag, comments_left)
    return comments_left


def run_session(
    client: Client,
    hashtags: list[str],
    model: str,
    official_source: str,
    max_comments: int,
    min_delay: int,
    max_delay: int,
    follower_threshold: int,
    follow_businesses: bool,
) -> None:
    hashtag = r.choice(hashtags)
    process_hashtag(
        client=client,
        hashtag=hashtag,
        model=model,
        official_source=official_source,
        max_comments=max_comments,
        min_delay=min_delay,
        max_delay=max_delay,
        fetch_amount=max(20, max_comments * 8),
        follower_threshold=follower_threshold,
        follow_businesses=follow_businesses,
    )


def schedule_todays_sessions(session_func: Any) -> None:
    schedule.clear("sessions")
    num_sessions = r.randint(1, 2)
    chosen_times: list[str] = []

    while len(chosen_times) < num_sessions:
        hour = r.randint(8, 22)
        minute = r.randint(0, 59)
        slot = f"{hour:02d}:{minute:02d}"
        if all(abs(hour - int(t[:2])) >= 2 for t in chosen_times):
            chosen_times.append(slot)
    for slot in chosen_times:
        schedule.every().day.at(slot).do(session_func).tag("sessions")
    logging.info("Scheduled %d session(s) today at: %s", num_sessions, ", ".join(sorted(chosen_times)))


def main() -> int:
    load_dotenv(ROOT / ".env")
    configure_logging()
    sessionid = os.getenv("INSTAGRAM_SESSIONID", "").strip()
    username = os.getenv("INSTAGRAM_USERNAME", "").strip()
    password = os.getenv("INSTAGRAM_PASSWORD", "").strip()
    try:
        hashtags = [tag.strip().lstrip("#") for tag in required_env("HASHTAGS").split(",") if tag.strip()]
        if not sessionid and (not username or not password):
            raise RuntimeError("Provide either INSTAGRAM_SESSIONID or both INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD in .env")
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 2

    client = Client()
    try:
        login(client, username=username, password=password, sessionid=sessionid)
    except Exception as exc:
        logging.error("Login failed: %s", exc)
        return 1

    model = os.getenv("OLLAMA_MODEL", "llama3.2").strip()
    official_source = os.getenv(
        "OFFICIAL_INFORMATION_SOURCE", "the Indian Army's official public-information channels"
    ).strip()
    max_comments = int(os.getenv("MAX_COMMENTS_PER_SESSION", "3"))
    min_delay = int(os.getenv("MIN_DELAY_SECONDS", "60"))
    max_delay = int(os.getenv("MAX_DELAY_SECONDS", "180"))
    follower_threshold = int(os.getenv("FOLLOWER_THRESHOLD", "0"))
    follow_businesses = os.getenv("FOLLOW_BUSINESSES", "true").strip().lower() == "true"
    schedule_mode = os.getenv("SCHEDULE_MODE", "false").strip().lower() == "true" or "--schedule" in sys.argv

    def session_runner() -> None:
        run_session(
            client=client,
            hashtags=hashtags,
            model=model,
            official_source=official_source,
            max_comments=max_comments,
            min_delay=min_delay,
            max_delay=max_delay,
            follower_threshold=follower_threshold,
            follow_businesses=follow_businesses,
        )

    logging.info("Executing initial session run...")
    session_runner()

    if schedule_mode:
        logging.info("Schedule mode active. Setting up daily schedules...")
        schedule.every().day.at("00:01").do(lambda: schedule_todays_sessions(session_runner))
        schedule_todays_sessions(session_runner)
        while True:
            schedule.run_pending()
            time.sleep(30)

    logging.info("Run finished. Records stored in %s", AUDIT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
