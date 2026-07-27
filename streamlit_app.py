from __future__ import annotations

import csv
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from latin_poster.config import AppConfig
from latin_poster.linkedin import (
    LinkedInError,
    authorization_url,
    exchange_code,
    format_post,
    get_userinfo,
    publish_text_post,
)
from latin_poster.scheduling import generate_schedule
from latin_poster.security import (
    encrypt_secret,
    new_oauth_state,
    oauth_state_matches,
)
from latin_poster.state import append_event, new_state
from latin_poster.state_store import GitHubStateStore, LocalStateStore
from latin_poster.worker import PosterWorker, recover_stale_claims


ROOT = Path(__file__).parent
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

st.set_page_config(page_title="Latin LinkedIn Poster", page_icon="🏛️", layout="wide")


def load_seed_sayings() -> list[dict[str, Any]]:
    with (ROOT / "data" / "sayings.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["approved"] = str(row.get("approved", "")).lower() == "true"
    return rows


def load_config() -> AppConfig:
    try:
        source = dict(st.secrets)
    except FileNotFoundError:
        source = {}
    return AppConfig.from_mapping(source)


@st.cache_resource
def get_store(
    backend: str,
    repository: str,
    token: str,
    branch: str,
    state_path: str,
    local_path: str,
) -> Any:
    initial = new_state(load_seed_sayings())
    if backend == "local":
        store = LocalStateStore(local_path, initial)
    else:
        store = GitHubStateStore(repository, token, branch, state_path, initial)
    store.ensure_ready()
    return store


@st.cache_resource
def start_worker(store: Any, fernet_key: str, timezone_name: str) -> PosterWorker:
    recover_stale_claims(store)
    return PosterWorker(store, fernet_key, timezone_name).start()


def authenticated(config: AppConfig) -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.title("🏛️ Latin LinkedIn Poster")
    st.caption("This control panel is password protected.")
    with st.form("login"):
        password = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Open control panel", type="primary")
    if submitted and secrets.compare_digest(password, config.admin_password):
        st.session_state["authenticated"] = True
        st.rerun()
    elif submitted:
        st.error("Incorrect password.")
    return False


def saying_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in state["sayings"]}


def queue_frame(state: dict[str, Any], timezone_name: str) -> pd.DataFrame:
    sayings = saying_map(state)
    rows = []
    for item in state["queue"]:
        saying = sayings.get(item["saying_id"], {})
        scheduled = pd.Timestamp(item["scheduled_for"]).tz_convert(timezone_name)
        rows.append(
            {
                "When": scheduled.strftime("%Y-%m-%d %H:%M %Z"),
                "Status": item["status"],
                "Latin": saying.get("latin", "Missing saying"),
                "Attribution": saying.get("attribution", ""),
                "Error": item.get("error", ""),
            }
        )
    return pd.DataFrame(rows)


def begin_linkedin_oauth(store: Any, config: AppConfig) -> str:
    raw, state_hash = new_oauth_state()

    def save(state: dict[str, Any]) -> None:
        state["oauth"] = {
            "state_hash": state_hash,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        }

    store.update(save)
    return authorization_url(config.linkedin_client_id, config.linkedin_redirect_uri, raw)


def handle_oauth_callback(store: Any, config: AppConfig) -> None:
    code = st.query_params.get("code")
    returned_state = st.query_params.get("state")
    error = st.query_params.get("error")
    if not code and not error:
        return
    if error:
        st.error(f"LinkedIn authorization was not completed: {error}")
        st.query_params.clear()
        return
    state, _ = store.load()
    oauth = state.get("oauth", {})
    expires = oauth.get("expires_at", "")
    valid = (
        bool(returned_state)
        and bool(oauth.get("state_hash"))
        and oauth_state_matches(returned_state, oauth["state_hash"])
        and bool(expires)
        and datetime.fromisoformat(expires) > datetime.now(timezone.utc)
    )
    if not valid:
        st.error("The LinkedIn authorization link is invalid or expired. Start again.")
        st.query_params.clear()
        return
    try:
        token_data = exchange_code(
            code,
            config.linkedin_client_id,
            config.linkedin_client_secret,
            config.linkedin_redirect_uri,
        )
        profile = get_userinfo(token_data["access_token"])
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(token_data.get("expires_in", 5184000))
        )

        def connect(current: dict[str, Any]) -> None:
            current["linkedin"] = {
                "connected": True,
                "encrypted_access_token": encrypt_secret(
                    token_data["access_token"], config.fernet_key
                ),
                "expires_at": expires_at.isoformat(),
                "person_id": profile["sub"],
                "display_name": profile.get("name", "LinkedIn member"),
            }
            current["oauth"] = {}
            append_event(current, "info", "LinkedIn account connected.")

        store.update(connect)
        st.session_state.pop("linkedin_connect_url", None)
        st.query_params.clear()
        st.success("LinkedIn account connected. Sign in to continue.")
    except (LinkedInError, KeyError, ValueError) as exc:
        st.query_params.clear()
        st.error(f"Could not connect LinkedIn: {exc}")


def render_dashboard(state: dict[str, Any], worker: PosterWorker, timezone_name: str) -> None:
    st.header("Dashboard")
    settings = state["settings"]
    linked = state["linkedin"]
    queued = sum(item["status"] == "queued" for item in state["queue"])
    attention = sum(item["status"] == "needs_review" for item in state["queue"])
    cols = st.columns(4)
    cols[0].metric("Automation", "On" if settings["automation_enabled"] else "Paused")
    cols[1].metric("LinkedIn", "Connected" if linked["connected"] else "Not connected")
    cols[2].metric("Queued", queued)
    cols[3].metric("Needs review", attention)
    if settings["dry_run"]:
        st.warning("Dry-run mode is on. Scheduled items will not be published.")
    if worker.last_error:
        st.error(f"Worker error: {worker.last_error}")
    elif worker.last_tick:
        st.caption(f"Worker last checked at {worker.last_tick}.")
    frame = queue_frame(state, timezone_name)
    st.subheader("Upcoming and recent queue")
    if frame.empty:
        st.info("No posts are scheduled yet.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)


def render_sayings(store: Any, state: dict[str, Any]) -> None:
    st.header("Sayings library")
    st.caption(
        "Seed entries begin unapproved. Review the Latin, translation, attribution, "
        "and whether the Latin is original or a modern rendering."
    )
    columns = ["approved", "latin", "translation", "attribution", "latin_kind", "note"]
    editor = pd.DataFrame(state["sayings"])[columns]
    edited = st.data_editor(
        editor,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={"approved": st.column_config.CheckboxColumn("Approved")},
        key=f"sayings-{state['revision']}",
    )
    if st.button("Save sayings", type="primary"):
        records = edited.fillna("").to_dict("records")
        originals = state["sayings"]
        for index, record in enumerate(records):
            record["id"] = (
                originals[index]["id"] if index < len(originals) else secrets.token_hex(8)
            )
            record["approved"] = bool(record["approved"])
            text = format_post(record)
            if len(text) > int(state["settings"]["max_post_chars"]):
                st.error(
                    f"One entry is {len(text)} characters; the configured maximum is "
                    f"{state['settings']['max_post_chars']}."
                )
                return

        def save(current: dict[str, Any]) -> None:
            current["sayings"] = records
            append_event(current, "info", "Sayings library updated.", count=len(records))

        store.update(save)
        st.success("Sayings saved.")
        st.rerun()
    csv_bytes = edited.to_csv(index=False).encode()
    st.download_button("Download CSV", csv_bytes, "sayings.csv", "text/csv")


def render_schedule(store: Any, state: dict[str, Any], config: AppConfig) -> None:
    st.header("Schedule")
    settings = state["settings"]
    with st.form("schedule_settings"):
        left, right = st.columns(2)
        minimum = left.number_input(
            "Minimum posts per week", 1, 14, int(settings["posts_per_week_min"])
        )
        maximum = right.number_input(
            "Maximum posts per week", 1, 14, int(settings["posts_per_week_max"])
        )
        chosen_days = st.multiselect(
            "Posting days",
            WEEKDAYS,
            default=[WEEKDAYS[index] for index in settings["allowed_weekdays"]],
        )
        earliest = left.time_input(
            "Earliest time", datetime.strptime(settings["earliest_time"], "%H:%M").time()
        )
        latest = right.time_input(
            "Latest time", datetime.strptime(settings["latest_time"], "%H:%M").time()
        )
        horizon = left.number_input(
            "Schedule horizon (days)", 7, 60, int(settings["schedule_horizon_days"])
        )
        spacing = right.number_input(
            "Minimum spacing (hours)", 1, 168, int(settings["min_spacing_hours"])
        )
        max_chars = left.number_input(
            "Maximum post characters", 100, 3000, int(settings["max_post_chars"])
        )
        visibility = right.selectbox(
            "Visibility", ["PUBLIC", "CONNECTIONS"], index=0 if settings["visibility"] == "PUBLIC" else 1
        )
        dry_run = st.toggle("Dry-run mode", value=bool(settings["dry_run"]))
        submitted = st.form_submit_button("Save schedule settings", type="primary")
    if submitted:
        if minimum > maximum:
            st.error("Minimum posts cannot exceed maximum posts.")
        elif not chosen_days:
            st.error("Choose at least one posting day.")
        elif earliest > latest:
            st.error("Earliest time must be before latest time.")
        else:
            def save(current: dict[str, Any]) -> None:
                current["settings"].update(
                    {
                        "posts_per_week_min": int(minimum),
                        "posts_per_week_max": int(maximum),
                        "allowed_weekdays": [WEEKDAYS.index(day) for day in chosen_days],
                        "earliest_time": earliest.strftime("%H:%M"),
                        "latest_time": latest.strftime("%H:%M"),
                        "schedule_horizon_days": int(horizon),
                        "min_spacing_hours": int(spacing),
                        "max_post_chars": int(max_chars),
                        "visibility": visibility,
                        "dry_run": dry_run,
                    }
                )
                append_event(current, "info", "Schedule settings updated.")
            store.update(save)
            st.success("Settings saved.")
            st.rerun()

    col1, col2 = st.columns(2)
    if col1.button("Fill randomized schedule", type="primary"):
        try:
            added = store.update(lambda current: generate_schedule(current, config.timezone))
            st.success(f"Added {added} scheduled post(s).")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    enabled = bool(settings["automation_enabled"])
    action = "Pause automation" if enabled else "Enable automation"
    if col2.button(action):
        if not enabled and not state["linkedin"]["connected"]:
            st.error("Connect LinkedIn before enabling automation.")
        elif not enabled and settings["dry_run"]:
            st.error("Turn off dry-run mode before enabling live automation.")
        else:
            def toggle(current: dict[str, Any]) -> None:
                current["settings"]["automation_enabled"] = not enabled
                append_event(
                    current,
                    "warning" if enabled else "info",
                    "Automation paused." if enabled else "Automation enabled.",
                )
            store.update(toggle)
            st.rerun()


def render_setup(store: Any, state: dict[str, Any], config: AppConfig) -> None:
    st.header("LinkedIn & setup")
    linkedin = state["linkedin"]
    if linkedin["connected"]:
        st.success(f"Connected as {linkedin['display_name']}")
        st.caption(f"Token expiry: {linkedin['expires_at']}")
    if st.button("Prepare LinkedIn connection"):
        st.session_state["linkedin_connect_url"] = begin_linkedin_oauth(store, config)
    if st.session_state.get("linkedin_connect_url"):
        st.link_button(
            "Continue to LinkedIn",
            st.session_state["linkedin_connect_url"],
            type="primary",
        )
    st.caption(
        "Opening this page creates a fresh 10-minute authorization link. LinkedIn "
        "access commonly needs periodic reconnection."
    )

    st.subheader("Connection test")
    approved = [item for item in state["sayings"] if item.get("approved")]
    confirm = st.checkbox(
        "I understand this immediately publishes one approved saying to my connections."
    )
    if st.button("Publish connections-only test", disabled=not confirm):
        if not linkedin["connected"]:
            st.error("Connect LinkedIn first.")
        elif not approved:
            st.error("Approve at least one saying first.")
        else:
            from latin_poster.security import decrypt_secret

            try:
                post_id = publish_text_post(
                    decrypt_secret(
                        linkedin["encrypted_access_token"], config.fernet_key
                    ),
                    linkedin["person_id"],
                    format_post(approved[0]),
                    "CONNECTIONS",
                )
                store.update(
                    lambda current: append_event(
                        current, "info", "Connections-only test published.", post_id=post_id
                    )
                )
                st.success("Test post published.")
            except (LinkedInError, ValueError) as exc:
                st.error(f"Test failed: {exc}")

    st.subheader("Runtime configuration")
    checks = {
        "Admin password": bool(config.admin_password),
        "GitHub state store": config.state_backend == "local"
        or bool(config.github_repository and config.github_state_token),
        "LinkedIn application": bool(
            config.linkedin_client_id and config.linkedin_client_secret
        ),
        "Redirect URI": bool(config.linkedin_redirect_uri),
        "Encryption key": bool(config.fernet_key),
    }
    st.dataframe(
        pd.DataFrame(
            [{"Setting": name, "Ready": "Yes" if ready else "No"} for name, ready in checks.items()]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.code(config.linkedin_redirect_uri or "LINKEDIN_REDIRECT_URI is not configured")
    parsed = urlparse(config.linkedin_redirect_uri)
    if parsed.scheme != "https":
        st.warning("The LinkedIn redirect URI should be the exact HTTPS Streamlit app URL.")


def render_logs(state: dict[str, Any]) -> None:
    st.header("Activity")
    events = list(reversed(state["events"]))
    if not events:
        st.info("No activity recorded yet.")
        return
    st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)


def main() -> None:
    config = load_config()
    missing = config.missing()
    if missing:
        st.title("Configuration required")
        st.error("Add these values in Streamlit → App settings → Secrets:")
        st.code("\n".join(missing))
        st.stop()
    try:
        store = get_store(
            config.state_backend,
            config.github_repository,
            config.github_state_token,
            config.github_state_branch,
            config.github_state_path,
            config.local_state_path,
        )
    except Exception as exc:
        st.error(f"State storage could not be initialized: {exc}")
        st.stop()

    handle_oauth_callback(store, config)
    if not authenticated(config):
        st.stop()

    worker = start_worker(store, config.fernet_key, config.timezone)
    state, _ = store.load()
    st.sidebar.title("Latin Poster")
    st.sidebar.caption(f"Timezone: {config.timezone}")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()

    dashboard, sayings, schedule, setup, logs = st.tabs(
        ["Dashboard", "Sayings", "Schedule", "LinkedIn & setup", "Activity"]
    )
    with dashboard:
        render_dashboard(state, worker, config.timezone)
    with sayings:
        render_sayings(store, state)
    with schedule:
        render_schedule(store, state, config)
    with setup:
        render_setup(store, state, config)
    with logs:
        render_logs(state)


if __name__ == "__main__":
    main()
