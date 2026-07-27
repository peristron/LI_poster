"""li_poster: a self-contained Streamlit LinkedIn scheduler."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import secrets
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken


st.set_page_config(
    page_title="li_poster",
    page_icon="🏛️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Application constants
# ---------------------------------------------------------------------------

APP_NAME = "li_poster"
APP_VERSION = "1.0.0"
GITHUB_API = "https://api.github.com"
LINKEDIN_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_POST_URL = "https://api.linkedin.com/v2/ugcPosts"
STATE_BRANCH = "runtime-state"
STATE_PATH = "runtime/state.json"
MAX_EVENTS = 500
MAX_HISTORY = 500
WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


# Every seed entry starts unapproved. The user must review it before scheduling.
SEED_SAYINGS: list[dict[str, Any]] = [
    {
        "id": "seneca-ep-1",
        "approved": False,
        "latin": "Dum differtur, vita transcurrit.",
        "translation": "While it is postponed, life passes by.",
        "attribution": "Seneca, Epistulae Morales 1.2",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "horace-odes-1-11",
        "approved": False,
        "latin": "Carpe diem, quam minimum credula postero.",
        "translation": "Seize the day, trusting as little as possible in tomorrow.",
        "attribution": "Horace, Odes 1.11",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "terence-heauton-77",
        "approved": False,
        "latin": "Homo sum: humani nihil a me alienum puto.",
        "translation": "I am human; I consider nothing human alien to me.",
        "attribution": "Terence, Heauton Timorumenos 77",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "virgil-aeneid-1-203",
        "approved": False,
        "latin": "Forsan et haec olim meminisse iuvabit.",
        "translation": "Perhaps one day it will please us to remember even these things.",
        "attribution": "Virgil, Aeneid 1.203",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "ovid-remedia-91",
        "approved": False,
        "latin": "Principiis obsta; sero medicina paratur.",
        "translation": "Resist beginnings; a remedy is prepared too late.",
        "attribution": "Ovid, Remedia Amoris 91",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "cicero-officiis-1-22",
        "approved": False,
        "latin": "Non nobis solum nati sumus.",
        "translation": "We are not born for ourselves alone.",
        "attribution": "Cicero, De Officiis 1.22",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "augustine-conf-1-1",
        "approved": False,
        "latin": "Inquietum est cor nostrum, donec requiescat in te.",
        "translation": "Our heart is restless until it rests in you.",
        "attribution": "Augustine, Confessiones 1.1",
        "latin_kind": "original Latin",
        "note": "",
    },
    {
        "id": "ecclesiastes-3-1",
        "approved": False,
        "latin": "Omnia tempus habent.",
        "translation": "For everything there is a season.",
        "attribution": "Ecclesiastes 3:1, Vulgate",
        "latin_kind": "Vulgate Latin",
        "note": "",
    },
    {
        "id": "epictetus-ench-1",
        "approved": False,
        "latin": "Alia in potestate nostra sunt, alia non sunt.",
        "translation": "Some things are within our power; others are not.",
        "attribution": "Epictetus, Enchiridion 1",
        "latin_kind": "modern Latin rendering from Greek",
        "note": "Latin rendering; compare the Greek original before approval.",
    },
    {
        "id": "marcus-aurelius-4-3",
        "approved": False,
        "latin": "Intra te ipsum recede.",
        "translation": "Withdraw into yourself.",
        "attribution": "Marcus Aurelius, Meditations 4.3",
        "latin_kind": "modern Latin rendering from Greek",
        "note": "Latin rendering; compare the Greek original before approval.",
    },
    {
        "id": "confucius-analects-15-24",
        "approved": False,
        "latin": "Quod tibi fieri non vis, alteri ne feceris.",
        "translation": "What you do not wish for yourself, do not do to another.",
        "attribution": "Confucius, Analects 15.24",
        "latin_kind": "modern Latin rendering from Classical Chinese",
        "note": "Latin rendering; compare the Classical Chinese original before approval.",
    },
    {
        "id": "laozi-daodejing-33",
        "approved": False,
        "latin": "Qui alios novit sapiens est; qui se ipsum novit illuminatus est.",
        "translation": "One who knows others is wise; one who knows oneself is enlightened.",
        "attribution": "Laozi, Daodejing 33",
        "latin_kind": "modern Latin rendering from Classical Chinese",
        "note": "Latin rendering; compare the Classical Chinese original before approval.",
    },
    {
        "id": "dhammapada-1-5",
        "approved": False,
        "latin": "Odium odio numquam sedatur; non odio sedatur.",
        "translation": "Hatred is never appeased by hatred; it is appeased by non-hatred.",
        "attribution": "Dhammapada 1.5",
        "latin_kind": "modern Latin rendering from Pali",
        "note": "Latin rendering; compare the Pali original before approval.",
    },
]


# ---------------------------------------------------------------------------
# Configuration and state helpers
# ---------------------------------------------------------------------------

def read_secrets() -> dict[str, str]:
    try:
        raw = dict(st.secrets)
    except FileNotFoundError:
        raw = {}
    return {str(key): str(value).strip() for key, value in raw.items()}


def required_secret_names() -> list[str]:
    return [
        "ADMIN_PASSWORD",
        "GITHUB_REPOSITORY",
        "GITHUB_STATE_TOKEN",
        "LINKEDIN_CLIENT_ID",
        "LINKEDIN_CLIENT_SECRET",
        "LINKEDIN_REDIRECT_URI",
        "FERNET_KEY",
    ]


def new_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": 0,
        "settings": {
            "automation_enabled": False,
            "dry_run": True,
            "posts_per_week_min": 2,
            "posts_per_week_max": 3,
            "allowed_weekdays": [0, 1, 2, 3, 4],
            "earliest_time": "08:30",
            "latest_time": "18:30",
            "min_spacing_hours": 18,
            "schedule_horizon_days": 21,
            "visibility": "PUBLIC",
            "recent_saying_window": 20,
            "max_post_chars": 600,
        },
        "linkedin": {
            "connected": False,
            "encrypted_access_token": "",
            "expires_at": "",
            "person_id": "",
            "display_name": "",
        },
        "oauth": {},
        "sayings": copy.deepcopy(SEED_SAYINGS),
        "queue": [],
        "history": [],
        "events": [],
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    defaults = new_state()
    state.setdefault("schema_version", 1)
    state.setdefault("revision", 0)
    state.setdefault("settings", {})
    for key, value in defaults["settings"].items():
        state["settings"].setdefault(key, value)
    state.setdefault("linkedin", defaults["linkedin"])
    for key, value in defaults["linkedin"].items():
        state["linkedin"].setdefault(key, value)
    state.setdefault("oauth", {})
    state.setdefault("sayings", copy.deepcopy(SEED_SAYINGS))
    state.setdefault("queue", [])
    state.setdefault("history", [])
    state.setdefault("events", [])
    return state


def append_event(
    state: dict[str, Any], level: str, message: str, **details: Any
) -> None:
    event: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    if details:
        event["details"] = details
    state["events"].append(event)
    state["events"] = state["events"][-MAX_EVENTS:]


def format_post(saying: dict[str, Any]) -> str:
    parts = [
        str(saying["latin"]).strip(),
        str(saying["translation"]).strip(),
        f"— {str(saying['attribution']).strip()}",
    ]
    note = str(saying.get("note", "")).strip()
    if note:
        parts.append(note)
    return "\n\n".join(parts)


def encrypt_value(value: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_value(value: str, key: str) -> str:
    try:
        return Fernet(key.encode()).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "The stored LinkedIn credential cannot be decrypted with FERNET_KEY."
        ) from exc


# ---------------------------------------------------------------------------
# Persistent GitHub state
# ---------------------------------------------------------------------------

class StateStoreError(RuntimeError):
    pass


class StateConflictError(StateStoreError):
    pass


class GitHubStateStore:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.lock = threading.RLock()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def repo_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.repository}"

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return requests.request(
                method, url, headers=self.headers, timeout=20, **kwargs
            )
        except requests.RequestException as exc:
            raise StateStoreError(f"GitHub state request failed: {exc}") from exc

    def ensure_ready(self) -> None:
        repository = self.request("GET", self.repo_url)
        if repository.status_code != 200:
            raise StateStoreError(
                f"Cannot access GitHub repository ({repository.status_code})."
            )
        default_branch = repository.json()["default_branch"]
        ref = self.request(
            "GET", f"{self.repo_url}/git/ref/heads/{default_branch}"
        )
        if ref.status_code != 200:
            raise StateStoreError("Cannot read the repository's default branch.")
        create = self.request(
            "POST",
            f"{self.repo_url}/git/refs",
            json={
                "ref": f"refs/heads/{STATE_BRANCH}",
                "sha": ref.json()["object"]["sha"],
            },
        )
        if create.status_code not in (201, 422):
            raise StateStoreError(
                f"Cannot create the runtime-state branch ({create.status_code})."
            )
        try:
            self.load()
        except FileNotFoundError:
            self.save(new_state(), sha=None)

    def load(self) -> tuple[dict[str, Any], str | None]:
        response = self.request(
            "GET",
            f"{self.repo_url}/contents/{STATE_PATH}",
            params={"ref": STATE_BRANCH},
        )
        if response.status_code == 404:
            raise FileNotFoundError(STATE_PATH)
        if response.status_code != 200:
            raise StateStoreError(f"Cannot load runtime state ({response.status_code}).")
        body = response.json()
        content = base64.b64decode(body["content"]).decode("utf-8")
        return normalize_state(json.loads(content)), body["sha"]

    def save(self, state: dict[str, Any], sha: str | None) -> None:
        state["revision"] = int(state.get("revision", 0)) + 1
        encoded = base64.b64encode(
            json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii")
        payload: dict[str, Any] = {
            "message": f"Update li_poster runtime state ({state['revision']})",
            "content": encoded,
            "branch": STATE_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        response = self.request(
            "PUT", f"{self.repo_url}/contents/{STATE_PATH}", json=payload
        )
        if response.status_code in (409, 422):
            raise StateConflictError("Runtime state changed concurrently.")
        if response.status_code not in (200, 201):
            raise StateStoreError(
                f"Cannot save runtime state ({response.status_code})."
            )

    def update(
        self, mutator: Callable[[dict[str, Any]], Any], retries: int = 5
    ) -> Any:
        with self.lock:
            for attempt in range(retries):
                try:
                    state, sha = self.load()
                except FileNotFoundError:
                    state, sha = new_state(), None
                result = mutator(state)
                try:
                    self.save(state, sha)
                    return result
                except StateConflictError:
                    if attempt == retries - 1:
                        raise
            raise StateConflictError("Runtime state update retry limit exceeded.")


@st.cache_resource
def get_store(repository: str, token: str) -> GitHubStateStore:
    store = GitHubStateStore(repository, token)
    store.ensure_ready()
    return store


# ---------------------------------------------------------------------------
# LinkedIn OAuth and posting
# ---------------------------------------------------------------------------

class LinkedInError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ambiguous = ambiguous


def linkedin_authorization_url(
    client_id: str, redirect_uri: str, oauth_state: str
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": oauth_state,
            "scope": "openid profile w_member_social",
        }
    )
    return f"{LINKEDIN_AUTHORIZE_URL}?{query}"


def exchange_linkedin_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict[str, Any]:
    try:
        response = requests.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn token exchange failed: {exc}") from exc
    if response.status_code != 200:
        raise LinkedInError(
            f"LinkedIn rejected the authorization ({response.status_code}).",
            response.status_code,
        )
    return response.json()


def get_linkedin_userinfo(access_token: str) -> dict[str, Any]:
    try:
        response = requests.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn profile lookup failed: {exc}") from exc
    if response.status_code != 200:
        raise LinkedInError(
            f"LinkedIn profile lookup failed ({response.status_code}).",
            response.status_code,
        )
    return response.json()


def publish_linkedin_post(
    access_token: str,
    person_id: str,
    text: str,
    visibility: str,
) -> str:
    payload = {
        "author": f"urn:li:person:{person_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility.upper()
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    try:
        response = requests.post(
            LINKEDIN_POST_URL, headers=headers, json=payload, timeout=25
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise LinkedInError(
            "The post result is uncertain because LinkedIn did not confirm it.",
            ambiguous=True,
        ) from exc
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn post request failed: {exc}") from exc

    if response.status_code not in (200, 201):
        ambiguous = response.status_code >= 500
        try:
            detail = str(response.json().get("message", ""))[:300]
        except ValueError:
            detail = ""
        message = f"LinkedIn rejected the post ({response.status_code})"
        if detail:
            message += f": {detail}"
        raise LinkedInError(message, response.status_code, ambiguous)
    return response.headers.get("X-RestLi-Id", "")


def create_oauth_link(
    store: GitHubStateStore, client_id: str, redirect_uri: str
) -> str:
    raw_state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(raw_state.encode()).hexdigest()

    def save(current: dict[str, Any]) -> None:
        current["oauth"] = {
            "state_hash": state_hash,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
        }

    store.update(save)
    return linkedin_authorization_url(client_id, redirect_uri, raw_state)


def handle_oauth_callback(
    store: GitHubStateStore, config: dict[str, str]
) -> None:
    code = st.query_params.get("code")
    returned_state = st.query_params.get("state")
    error = st.query_params.get("error")
    if not code and not error:
        return
    if error:
        st.query_params.clear()
        st.error(f"LinkedIn authorization was not completed: {error}")
        return

    current, _ = store.load()
    oauth = current.get("oauth", {})
    expected_hash = str(oauth.get("state_hash", ""))
    expires_at = str(oauth.get("expires_at", ""))
    actual_hash = hashlib.sha256(str(returned_state).encode()).hexdigest()
    valid = (
        bool(returned_state)
        and bool(expected_hash)
        and secrets.compare_digest(actual_hash, expected_hash)
        and bool(expires_at)
        and datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
    )
    if not valid:
        st.query_params.clear()
        st.error("The LinkedIn authorization link is invalid or expired.")
        return

    try:
        token_data = exchange_linkedin_code(
            str(code),
            config["LINKEDIN_CLIENT_ID"],
            config["LINKEDIN_CLIENT_SECRET"],
            config["LINKEDIN_REDIRECT_URI"],
        )
        profile = get_linkedin_userinfo(token_data["access_token"])
        expiry = datetime.now(timezone.utc) + timedelta(
            seconds=int(token_data.get("expires_in", 5_184_000))
        )

        def connect(state: dict[str, Any]) -> None:
            state["linkedin"] = {
                "connected": True,
                "encrypted_access_token": encrypt_value(
                    token_data["access_token"], config["FERNET_KEY"]
                ),
                "expires_at": expiry.isoformat(),
                "person_id": str(profile["sub"]),
                "display_name": str(profile.get("name", "LinkedIn member")),
            }
            state["oauth"] = {}
            append_event(state, "info", "LinkedIn account connected.")

        store.update(connect)
        st.session_state.pop("linkedin_connect_url", None)
        st.query_params.clear()
        st.success("LinkedIn account connected. Sign in to continue.")
    except (LinkedInError, KeyError, ValueError) as exc:
        st.query_params.clear()
        st.error(f"Could not connect LinkedIn: {exc}")


# ---------------------------------------------------------------------------
# Randomized scheduling
# ---------------------------------------------------------------------------

def parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def random_local_datetime(
    day: date, earliest: time, latest: time, zone: ZoneInfo
) -> datetime:
    start_minute = earliest.hour * 60 + earliest.minute
    end_minute = latest.hour * 60 + latest.minute
    selected = random.SystemRandom().randint(start_minute, end_minute)
    return datetime.combine(
        day, time(selected // 60, selected % 60), tzinfo=zone
    )


def is_spaced(
    candidate: datetime, occupied: list[datetime], minimum_hours: int
) -> bool:
    return all(
        abs((candidate - existing).total_seconds()) >= minimum_hours * 3600
        for existing in occupied
    )


def generate_schedule(
    state: dict[str, Any],
    timezone_name: str,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    settings = state["settings"]
    approved = [item for item in state["sayings"] if bool(item.get("approved"))]
    if not approved:
        raise ValueError("Approve at least one saying before generating a schedule.")

    earliest = parse_clock(settings["earliest_time"])
    latest = parse_clock(settings["latest_time"])
    if earliest > latest:
        raise ValueError("Earliest posting time must be before latest posting time.")

    allowed = {int(day) for day in settings["allowed_weekdays"]}
    final_day = local_now.date() + timedelta(
        days=int(settings["schedule_horizon_days"])
    )
    eligible_days: list[date] = []
    cursor = local_now.date()
    while cursor <= final_day:
        if cursor.weekday() in allowed:
            eligible_days.append(cursor)
        cursor += timedelta(days=1)

    days_by_week: dict[tuple[int, int], list[date]] = {}
    for eligible_day in eligible_days:
        iso = eligible_day.isocalendar()
        days_by_week.setdefault((iso.year, iso.week), []).append(eligible_day)

    pending = [
        item
        for item in state["queue"]
        if item["status"] in ("queued", "publishing")
    ]
    occupied = [
        datetime.fromisoformat(item["scheduled_for"]) for item in pending
    ]
    recent_window = int(settings["recent_saying_window"])
    completed_times = [
        datetime.fromisoformat(item.get("posted_at", item["scheduled_for"]))
        for item in state["history"]
        if item.get("posted_at") or item.get("scheduled_for")
    ]
    occupied.extend(completed_times[-recent_window:])

    recently_used = {item["saying_id"] for item in pending}
    recently_used.update(
        item["saying_id"] for item in state["history"][-recent_window:]
    )

    rng = random.SystemRandom()
    added = 0
    for week_days in days_by_week.values():
        target = rng.randint(
            int(settings["posts_per_week_min"]),
            int(settings["posts_per_week_max"]),
        )
        existing = sum(
            datetime.fromisoformat(item["scheduled_for"])
            .astimezone(zone)
            .date()
            in week_days
            for item in pending
        )
        existing += sum(
            datetime.fromisoformat(item.get("posted_at", item["scheduled_for"]))
            .astimezone(zone)
            .date()
            in week_days
            for item in state["history"]
        )
        needed = max(0, target - existing)
        candidate_days = rng.sample(
            week_days, min(len(week_days), needed * 2 + 1)
        )
        for candidate_day in candidate_days:
            if needed <= 0:
                break
            candidate = random_local_datetime(
                candidate_day, earliest, latest, zone
            )
            if candidate <= local_now:
                continue
            if not is_spaced(
                candidate, occupied, int(settings["min_spacing_hours"])
            ):
                continue
            choices = [
                item for item in approved if item["id"] not in recently_used
            ]
            if not choices:
                recently_used.clear()
                choices = approved
            saying = rng.choice(choices)
            state["queue"].append(
                {
                    "id": str(uuid.uuid4()),
                    "saying_id": saying["id"],
                    "scheduled_for": candidate.astimezone(timezone.utc).isoformat(),
                    "status": "queued",
                    "created_at": now.isoformat(),
                    "attempts": 0,
                }
            )
            occupied.append(candidate)
            recently_used.add(saying["id"])
            needed -= 1
            added += 1
    state["queue"].sort(key=lambda item: item["scheduled_for"])
    return added


def find_due_item(
    state: dict[str, Any], now: datetime | None = None
) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    for item in state["queue"]:
        if (
            item["status"] == "queued"
            and datetime.fromisoformat(item["scheduled_for"]) <= now
        ):
            return item
    return None


# ---------------------------------------------------------------------------
# Background posting worker
# ---------------------------------------------------------------------------

class PosterWorker:
    def __init__(
        self,
        store: GitHubStateStore,
        fernet_key: str,
        timezone_name: str,
    ) -> None:
        self.store = store
        self.fernet_key = fernet_key
        self.timezone_name = timezone_name
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_tick = ""
        self.last_error = ""

    def start(self) -> "PosterWorker":
        if self.thread and self.thread.is_alive():
            return self
        self.thread = threading.Thread(
            target=self.run, name="li-poster-worker", daemon=True
        )
        self.thread.start()
        return self

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
            self.last_tick = datetime.now(timezone.utc).isoformat()
            self.stop_event.wait(45)

    def tick(self) -> None:
        state, _ = self.store.load()
        settings = state["settings"]
        linkedin = state["linkedin"]
        if not settings["automation_enabled"] or settings["dry_run"]:
            return
        if not linkedin.get("connected"):
            return
        if linkedin.get("expires_at") and datetime.fromisoformat(
            linkedin["expires_at"]
        ) <= datetime.now(timezone.utc):

            def expire(current: dict[str, Any]) -> None:
                current["linkedin"]["connected"] = False
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "LinkedIn token expired; automation paused.",
                )

            self.store.update(expire)
            return

        candidate = find_due_item(state)
        if candidate is None:
            return
        queue_id = candidate["id"]
        claimed: dict[str, Any] = {}

        def claim(current: dict[str, Any]) -> bool:
            item = next(
                (row for row in current["queue"] if row["id"] == queue_id),
                None,
            )
            if not item or item["status"] != "queued":
                return False
            item["status"] = "publishing"
            item["claimed_at"] = datetime.now(timezone.utc).isoformat()
            item["attempts"] = int(item.get("attempts", 0)) + 1
            claimed.update(copy.deepcopy(item))
            append_event(
                current, "info", "Claimed a scheduled post.", queue_id=queue_id
            )
            return True

        if not self.store.update(claim):
            return

        fresh, _ = self.store.load()
        saying = next(
            row
            for row in fresh["sayings"]
            if row["id"] == claimed["saying_id"]
        )
        try:
            post_id = publish_linkedin_post(
                decrypt_value(
                    fresh["linkedin"]["encrypted_access_token"],
                    self.fernet_key,
                ),
                fresh["linkedin"]["person_id"],
                format_post(saying),
                fresh["settings"]["visibility"],
            )
        except LinkedInError as exc:

            def fail(current: dict[str, Any]) -> None:
                item = next(
                    row for row in current["queue"] if row["id"] == queue_id
                )
                item["status"] = (
                    "needs_review" if exc.ambiguous else "failed"
                )
                item["error"] = str(exc)
                append_event(
                    current,
                    "error",
                    "LinkedIn post was not confirmed.",
                    queue_id=queue_id,
                    ambiguous=exc.ambiguous,
                )

            self.store.update(fail)
            return

        def complete(current: dict[str, Any]) -> None:
            item = next(
                row for row in current["queue"] if row["id"] == queue_id
            )
            item["status"] = "posted"
            item["posted_at"] = datetime.now(timezone.utc).isoformat()
            item["linkedin_post_id"] = post_id
            current["history"].append(copy.deepcopy(item))
            current["history"] = current["history"][-MAX_HISTORY:]
            active = [
                row for row in current["queue"] if row["status"] != "posted"
            ]
            posted = [
                row for row in current["queue"] if row["status"] == "posted"
            ][-100:]
            current["queue"] = sorted(
                active + posted, key=lambda row: row["scheduled_for"]
            )
            append_event(
                current, "info", "Post published.", queue_id=queue_id
            )
            generate_schedule(current, self.timezone_name)

        self.store.update(complete)


def recover_interrupted_posts(store: GitHubStateStore) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    def recover(state: dict[str, Any]) -> int:
        count = 0
        for item in state["queue"]:
            if item["status"] != "publishing":
                continue
            if datetime.fromisoformat(item["claimed_at"]) < cutoff:
                item["status"] = "needs_review"
                item["error"] = (
                    "The app stopped while publishing. Verify on LinkedIn."
                )
                count += 1
        if count:
            append_event(
                state,
                "warning",
                "Interrupted posts moved to manual review.",
                count=count,
            )
        return count

    return store.update(recover)


@st.cache_resource
def start_worker(
    _store: GitHubStateStore, fernet_key: str, timezone_name: str
) -> PosterWorker:
    recover_interrupted_posts(_store)
    return PosterWorker(_store, fernet_key, timezone_name).start()


# ---------------------------------------------------------------------------
# Streamlit interface
# ---------------------------------------------------------------------------

def require_login(admin_password: str) -> bool:
    if st.session_state.get("li_poster_authenticated"):
        return True
    st.title("🏛️ li_poster")
    st.caption("Automated Latin-first posts for LinkedIn")
    with st.form("admin_login"):
        entered = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button(
            "Open control panel", type="primary"
        )
    if submitted and secrets.compare_digest(entered, admin_password):
        st.session_state["li_poster_authenticated"] = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    return False


def queue_dataframe(
    state: dict[str, Any], timezone_name: str
) -> pd.DataFrame:
    sayings = {item["id"]: item for item in state["sayings"]}
    rows = []
    for item in state["queue"]:
        saying = sayings.get(item["saying_id"], {})
        scheduled = pd.Timestamp(item["scheduled_for"]).tz_convert(timezone_name)
        rows.append(
            {
                "when": scheduled.strftime("%Y-%m-%d %H:%M %Z"),
                "status": item["status"],
                "latin": saying.get("latin", "Missing saying"),
                "attribution": saying.get("attribution", ""),
                "error": item.get("error", ""),
            }
        )
    return pd.DataFrame(rows)


def render_dashboard(
    store: GitHubStateStore,
    state: dict[str, Any],
    worker: PosterWorker,
    timezone_name: str,
) -> None:
    st.header("Dashboard")
    settings = state["settings"]
    linkedin = state["linkedin"]
    queued = sum(row["status"] == "queued" for row in state["queue"])
    attention = sum(
        row["status"] == "needs_review" for row in state["queue"]
    )
    columns = st.columns(4)
    columns[0].metric(
        "Automation", "On" if settings["automation_enabled"] else "Paused"
    )
    columns[1].metric(
        "LinkedIn", "Connected" if linkedin["connected"] else "Not connected"
    )
    columns[2].metric("Queued", queued)
    columns[3].metric("Needs review", attention)

    if settings["dry_run"]:
        st.warning(
            "Dry-run mode is on. Scheduled items will not be published."
        )
    if worker.last_error:
        st.error(f"Background worker error: {worker.last_error}")
    elif worker.last_tick:
        st.caption(f"Background worker last checked at {worker.last_tick}.")
    else:
        st.caption("The background worker is starting.")

    st.subheader("Posting queue")
    frame = queue_dataframe(state, timezone_name)
    if frame.empty:
        st.info("No posts are scheduled yet.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)

    review_items = [
        item
        for item in state["queue"]
        if item["status"] in ("needs_review", "failed")
    ]
    if review_items:
        st.subheader("Resolve posting problems")
        saying_lookup = {item["id"]: item for item in state["sayings"]}
        labels = {
            item["id"]: (
                f"{item['status']}: "
                f"{saying_lookup.get(item['saying_id'], {}).get('latin', item['id'])}"
            )
            for item in review_items
        }
        selected_id = st.selectbox(
            "Queue item",
            options=list(labels),
            format_func=lambda value: labels[value],
        )
        checked = st.checkbox(
            "I checked my LinkedIn profile and know whether this item posted."
        )
        left, right = st.columns(2)
        if left.button("Mark as posted", disabled=not checked):

            def mark_posted(current: dict[str, Any]) -> None:
                item = next(
                    row
                    for row in current["queue"]
                    if row["id"] == selected_id
                )
                item["status"] = "posted"
                item["posted_at"] = datetime.now(timezone.utc).isoformat()
                item["resolution"] = "Confirmed manually on LinkedIn."
                current["history"].append(copy.deepcopy(item))
                current["history"] = current["history"][-MAX_HISTORY:]
                append_event(
                    current,
                    "info",
                    "A posting result was confirmed manually.",
                    queue_id=selected_id,
                )

            store.update(mark_posted)
            st.rerun()
        if right.button("Mark as not posted", disabled=not checked):

            def mark_not_posted(current: dict[str, Any]) -> None:
                item = next(
                    row
                    for row in current["queue"]
                    if row["id"] == selected_id
                )
                item["status"] = "dismissed"
                item["resolution"] = "Confirmed manually as not posted."
                append_event(
                    current,
                    "info",
                    "A posting problem was dismissed manually.",
                    queue_id=selected_id,
                )

            store.update(mark_not_posted)
            st.rerun()


def render_sayings(store: GitHubStateStore, state: dict[str, Any]) -> None:
    st.header("Sayings")
    st.caption(
        "Review every entry before approving it. Some entries are modern Latin "
        "renderings of sayings originally written in another language."
    )
    display_columns = [
        "approved",
        "latin",
        "translation",
        "attribution",
        "latin_kind",
        "note",
    ]
    editor = pd.DataFrame(state["sayings"])[display_columns]
    edited = st.data_editor(
        editor,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "approved": st.column_config.CheckboxColumn("approved")
        },
        key=f"sayings_editor_{state['revision']}",
    )
    left, right = st.columns(2)
    if left.button("Save sayings", type="primary"):
        records = edited.fillna("").to_dict("records")
        originals = state["sayings"]
        errors: list[str] = []
        for index, record in enumerate(records):
            record["id"] = (
                originals[index]["id"]
                if index < len(originals)
                else secrets.token_hex(8)
            )
            record["approved"] = bool(record["approved"])
            missing = [
                field
                for field in ("latin", "translation", "attribution")
                if not str(record[field]).strip()
            ]
            if missing:
                errors.append(
                    f"Row {index + 1} is missing: {', '.join(missing)}."
                )
            length = len(format_post(record))
            if length > int(state["settings"]["max_post_chars"]):
                errors.append(
                    f"Row {index + 1} is {length} characters; the maximum is "
                    f"{state['settings']['max_post_chars']}."
                )
        if errors:
            st.error("\n".join(errors))
        else:

            def save(current: dict[str, Any]) -> None:
                current["sayings"] = records
                append_event(
                    current,
                    "info",
                    "Sayings library updated.",
                    count=len(records),
                )

            store.update(save)
            st.success("Sayings saved.")
            st.rerun()

    right.download_button(
        "Download sayings CSV",
        edited.to_csv(index=False).encode("utf-8"),
        "li_poster_sayings.csv",
        "text/csv",
    )

    approved_count = sum(
        bool(item.get("approved")) for item in state["sayings"]
    )
    st.caption(
        f"{approved_count} of {len(state['sayings'])} sayings are approved."
    )


def render_schedule(
    store: GitHubStateStore,
    state: dict[str, Any],
    timezone_name: str,
) -> None:
    st.header("Schedule")
    settings = state["settings"]
    with st.form("schedule_settings"):
        left, right = st.columns(2)
        minimum = left.number_input(
            "Minimum posts per week",
            min_value=1,
            max_value=14,
            value=int(settings["posts_per_week_min"]),
        )
        maximum = right.number_input(
            "Maximum posts per week",
            min_value=1,
            max_value=14,
            value=int(settings["posts_per_week_max"]),
        )
        selected_days = st.multiselect(
            "Posting days",
            WEEKDAYS,
            default=[
                WEEKDAYS[index] for index in settings["allowed_weekdays"]
            ],
        )
        earliest = left.time_input(
            "Earliest posting time",
            datetime.strptime(settings["earliest_time"], "%H:%M").time(),
        )
        latest = right.time_input(
            "Latest posting time",
            datetime.strptime(settings["latest_time"], "%H:%M").time(),
        )
        horizon = left.number_input(
            "Schedule horizon in days",
            min_value=7,
            max_value=60,
            value=int(settings["schedule_horizon_days"]),
        )
        spacing = right.number_input(
            "Minimum spacing in hours",
            min_value=1,
            max_value=168,
            value=int(settings["min_spacing_hours"]),
        )
        maximum_characters = left.number_input(
            "Maximum post characters",
            min_value=100,
            max_value=3000,
            value=int(settings["max_post_chars"]),
        )
        visibility = right.selectbox(
            "Post visibility",
            ["PUBLIC", "CONNECTIONS"],
            index=0 if settings["visibility"] == "PUBLIC" else 1,
        )
        dry_run = st.toggle(
            "Dry-run mode", value=bool(settings["dry_run"])
        )
        submitted = st.form_submit_button(
            "Save schedule settings", type="primary"
        )

    if submitted:
        errors = []
        if minimum > maximum:
            errors.append("Minimum posts cannot exceed maximum posts.")
        if not selected_days:
            errors.append("Choose at least one posting day.")
        if earliest > latest:
            errors.append("Earliest time must be before latest time.")
        if errors:
            st.error("\n".join(errors))
        else:

            def save(current: dict[str, Any]) -> None:
                current["settings"].update(
                    {
                        "posts_per_week_min": int(minimum),
                        "posts_per_week_max": int(maximum),
                        "allowed_weekdays": [
                            WEEKDAYS.index(day) for day in selected_days
                        ],
                        "earliest_time": earliest.strftime("%H:%M"),
                        "latest_time": latest.strftime("%H:%M"),
                        "schedule_horizon_days": int(horizon),
                        "min_spacing_hours": int(spacing),
                        "max_post_chars": int(maximum_characters),
                        "visibility": visibility,
                        "dry_run": bool(dry_run),
                    }
                )
                append_event(current, "info", "Schedule settings updated.")

            store.update(save)
            st.success("Schedule settings saved.")
            st.rerun()

    left, right = st.columns(2)
    if left.button("Fill randomized schedule", type="primary"):
        try:
            added = store.update(
                lambda current: generate_schedule(current, timezone_name)
            )
            st.success(f"Added {added} scheduled post(s).")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    automation_enabled = bool(settings["automation_enabled"])
    action = (
        "Pause automation" if automation_enabled else "Enable automation"
    )
    if right.button(action):
        queued = any(row["status"] == "queued" for row in state["queue"])
        approved = any(
            bool(row.get("approved")) for row in state["sayings"]
        )
        if not automation_enabled and not state["linkedin"]["connected"]:
            st.error("Connect LinkedIn before enabling automation.")
        elif not automation_enabled and settings["dry_run"]:
            st.error("Turn off dry-run mode before enabling automation.")
        elif not automation_enabled and not approved:
            st.error("Approve at least one saying first.")
        elif not automation_enabled and not queued:
            st.error("Fill the randomized schedule first.")
        else:

            def toggle(current: dict[str, Any]) -> None:
                current["settings"]["automation_enabled"] = (
                    not automation_enabled
                )
                append_event(
                    current,
                    "warning" if automation_enabled else "info",
                    "Automation paused."
                    if automation_enabled
                    else "Automation enabled.",
                )

            store.update(toggle)
            st.rerun()

    with st.expander("Cancel queued posts"):
        st.warning(
            "This cancels only items that have not started publishing. "
            "Posted items and history remain unchanged."
        )
        confirmed = st.checkbox(
            "I want to cancel every currently queued post.",
            key="confirm_cancel_queue",
        )
        if st.button("Cancel queued posts", disabled=not confirmed):

            def cancel(current: dict[str, Any]) -> int:
                count = 0
                for item in current["queue"]:
                    if item["status"] == "queued":
                        item["status"] = "cancelled"
                        count += 1
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "Queued posts cancelled and automation paused.",
                    count=count,
                )
                return count

            count = store.update(cancel)
            st.success(f"Cancelled {count} queued post(s).")
            st.rerun()


def render_linkedin_setup(
    store: GitHubStateStore,
    state: dict[str, Any],
    config: dict[str, str],
) -> None:
    st.header("LinkedIn and setup")
    linkedin = state["linkedin"]
    if linkedin["connected"]:
        st.success(f"Connected as {linkedin['display_name']}")
        st.caption(f"Access-token expiry: {linkedin['expires_at']}")
    else:
        st.warning("No LinkedIn account is connected.")

    if st.button("Prepare LinkedIn connection"):
        st.session_state["linkedin_connect_url"] = create_oauth_link(
            store,
            config["LINKEDIN_CLIENT_ID"],
            config["LINKEDIN_REDIRECT_URI"],
        )
    if st.session_state.get("linkedin_connect_url"):
        st.link_button(
            "Continue to LinkedIn",
            st.session_state["linkedin_connect_url"],
            type="primary",
        )
        st.caption(
            "This authorization link expires after ten minutes."
        )

    with st.expander("Publish a connections-only test"):
        approved = [
            item for item in state["sayings"] if bool(item.get("approved"))
        ]
        confirmed = st.checkbox(
            "I understand this immediately publishes the first approved "
            "saying to my LinkedIn connections."
        )
        if st.button(
            "Publish test now",
            disabled=not confirmed,
            type="primary",
        ):
            if not linkedin["connected"]:
                st.error("Connect LinkedIn first.")
            elif not approved:
                st.error("Approve at least one saying first.")
            else:
                try:
                    post_id = publish_linkedin_post(
                        decrypt_value(
                            linkedin["encrypted_access_token"],
                            config["FERNET_KEY"],
                        ),
                        linkedin["person_id"],
                        format_post(approved[0]),
                        "CONNECTIONS",
                    )

                    def record_test(current: dict[str, Any]) -> None:
                        append_event(
                            current,
                            "info",
                            "Connections-only test post published.",
                            post_id=post_id,
                        )

                    store.update(record_test)
                    st.success("Connections-only test post published.")
                except (LinkedInError, ValueError) as exc:
                    st.error(f"Test post failed: {exc}")

    st.subheader("Configuration")
    checks = [
        {
            "setting": "GitHub state repository",
            "ready": "yes"
            if config["GITHUB_REPOSITORY"]
            and config["GITHUB_STATE_TOKEN"]
            else "no",
        },
        {
            "setting": "LinkedIn application",
            "ready": "yes"
            if config["LINKEDIN_CLIENT_ID"]
            and config["LINKEDIN_CLIENT_SECRET"]
            else "no",
        },
        {
            "setting": "HTTPS redirect URI",
            "ready": "yes"
            if urlparse(config["LINKEDIN_REDIRECT_URI"]).scheme == "https"
            else "no",
        },
        {
            "setting": "Encryption key",
            "ready": "yes" if config["FERNET_KEY"] else "no",
        },
    ]
    st.dataframe(pd.DataFrame(checks), hide_index=True, use_container_width=True)
    st.caption("LinkedIn redirect URI")
    st.code(config["LINKEDIN_REDIRECT_URI"])


def render_activity(state: dict[str, Any]) -> None:
    st.header("Activity")
    if not state["events"]:
        st.info("No activity has been recorded yet.")
        return
    st.dataframe(
        pd.DataFrame(list(reversed(state["events"]))),
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    config = read_secrets()
    missing = [
        name for name in required_secret_names() if not config.get(name)
    ]
    if missing:
        st.title("li_poster configuration required")
        st.error(
            "Add the following values under Streamlit App settings → Secrets."
        )
        st.code("\n".join(missing))
        st.stop()

    timezone_name = config.get("TIMEZONE", "America/Toronto")
    try:
        ZoneInfo(timezone_name)
        Fernet(config["FERNET_KEY"].encode())
    except Exception as exc:
        st.error(f"TIMEZONE or FERNET_KEY is invalid: {exc}")
        st.stop()

    try:
        store = get_store(
            config["GITHUB_REPOSITORY"],
            config["GITHUB_STATE_TOKEN"],
        )
    except Exception as exc:
        st.error(f"Runtime state could not be initialized: {exc}")
        st.stop()

    # OAuth must be handled before login. Its random state value is validated.
    handle_oauth_callback(store, config)

    # Start before the password gate so an external app-waker visit is enough
    # to restart the posting worker after Streamlit hibernation.
    worker = start_worker(
        store,
        config["FERNET_KEY"],
        timezone_name,
    )

    if not require_login(config["ADMIN_PASSWORD"]):
        st.stop()

    state, _ = store.load()
    st.sidebar.title("🏛️ li_poster")
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.sidebar.caption(f"Timezone: {timezone_name}")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()

    dashboard, sayings, schedule, linkedin, activity = st.tabs(
        [
            "Dashboard",
            "Sayings",
            "Schedule",
            "LinkedIn and setup",
            "Activity",
        ]
    )
    with dashboard:
        render_dashboard(store, state, worker, timezone_name)
    with sayings:
        render_sayings(store, state)
    with schedule:
        render_schedule(store, state, timezone_name)
    with linkedin:
        render_linkedin_setup(store, state, config)
    with activity:
        render_activity(state)


if __name__ == "__main__":
    main()
