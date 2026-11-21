import streamlit as st
import hashlib
import requests
import csv
import io
import pandas as pd
from statistics import mean
from datetime import datetime, timezone

DEFAULT_API_URL = "https://script.google.com/macros/s/AKfycbyNZNOE1DYNbd4GbGTISJsGrnJ4PYCuip0yjSw3Lr8KkD6-kadKI9mfpKNfiAHEWb0Osw/exec"
COMMIT_DEADLINE_UTC = datetime(2026, 11, 15, 22, 59, 59, tzinfo=timezone.utc)
REVEAL_OPEN_UTC = datetime(2026, 11, 15, 23, 0, 0, tzinfo=timezone.utc)

K_FACTOR = 2 / 3
ALLOWED_MIN, ALLOWED_MAX = 0, 100

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def parse_ts(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None

def get_csv(url: str):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))

st.set_page_config(page_title="Decentralized Beauty Contest", layout="wide")
st.title("Decentralized Keynesian Beauty Contest")
st.caption("NEOMA Fintech & DeFi Course — Commit-Reveal & Deterministic Consensus")

with st.sidebar:
    st.header("Configuration")
    api_url = st.text_input("Apps Script API URL", value=DEFAULT_API_URL)
    ignore_deadlines = st.checkbox("Bypass deadline checks (for testing/demo)", value=True)

tab_commit, tab_reveal, tab_consensus = st.tabs([
    "1. Commit Phase", 
    "2. Reveal Phase", 
    "3. Consensus & Results"
])

with tab_commit:
    st.subheader("Commit Your Guess")
    now = datetime.now(timezone.utc)
    if not ignore_deadlines and now > COMMIT_DEADLINE_UTC:
        st.error("⛔ Commit window is CLOSED (Deadline: 15 Nov 2026 23:59:59 Paris).")
    else:
        with st.form("commit_form"):
            c_uid = st.text_input("University ID").strip()
            c_num = st.number_input("Choose your number (0–100)", min_value=0, max_value=100, step=1)
            c_nonce = st.text_input("Secret Nonce (keep this safe!)", type="password").strip()
            submitted_commit = st.form_submit_button("Submit Commit")

        if submitted_commit:
            if not c_uid or not c_nonce:
                st.warning("University ID and Nonce cannot be empty.")
            else:
                preimage = f"{c_uid}|{int(c_num)}|{c_nonce}"
                commit_hash = sha256(preimage)
                payload = {"kind": "commit", "uni_id": c_uid, "commit": commit_hash}
                try:
                    r = requests.post(api_url, json=payload, timeout=15)
                    st.success(f"Commit sent! Server status: {r.status_code} ({r.text})")
                    st.code(f"Hash: {commit_hash}\nPreimage (SAVE THIS): {preimage}")
                except Exception as e:
                    st.error(f"Network error: {e}")

with tab_reveal:
    st.subheader("Reveal Your Guess")
    now = datetime.now(timezone.utc)
    if not ignore_deadlines and now < REVEAL_OPEN_UTC:
        st.error("⛔ Reveal window is NOT open yet.")
    else:
        with st.form("reveal_form"):
            r_uid = st.text_input("University ID").strip()
            r_num = st.number_input("Your committed number (0–100)", min_value=0, max_value=100, step=1)
            r_nonce = st.text_input("Your secret nonce", type="password").strip()
            submitted_reveal = st.form_submit_button("Submit Reveal")

        if submitted_reveal:
            if not r_uid or not r_nonce:
                st.warning("University ID and Nonce cannot be empty.")
            else:
                payload = {"kind": "reveal", "uni_id": r_uid, "number": int(r_num), "nonce": r_nonce}
                try:
                    r = requests.post(api_url, json=payload, timeout=15)
                    st.success(f"Reveal sent! Server status: {r.status_code} ({r.text})")
                except Exception as e:
                    st.error(f"Network error: {e}")

with tab_consensus:
    st.subheader("Run Deterministic Consensus & View Ledger")
    if st.button("Fetch Ledger & Compute Winners", type="primary"):
        try:
            commits_raw = get_csv(f"{api_url}?table=commits")
            reveals_raw = get_csv(f"{api_url}?table=reveals")

            commits = {}
            for r in commits_raw:
                uid = (r.get("uni_id") or "").strip()
                ch = (r.get("commit") or "").strip()
                ts = (r.get("timestamp_utc") or "").strip()
                if uid and ch:
                    commits.setdefault(uid, []).append({
                        "timestamp_utc": ts, "ts_parsed": parse_ts(ts), "uni_id": uid, "commit": ch
                    })

            reveals = {}
            for r in reveals_raw:
                uid = (r.get("uni_id") or "").strip()
                num = (r.get("number") or "").strip()
                nonce = (r.get("nonce") or "").strip()
                ts = (r.get("timestamp_utc") or "").strip()
                if uid and num and nonce:
                    reveals.setdefault(uid, []).append({
                        "timestamp_utc": ts, "ts_parsed": parse_ts(ts), "uni_id": uid, "number_raw": num, "nonce": nonce
                    })

            verified_rows = []
            for uid, rlist in reveals.items():
                latest_rev = sorted(rlist, key=lambda x: (x["ts_parsed"] or datetime.min))[-1]
                ts_rev = latest_rev["ts_parsed"] or datetime.min

                try:
                    num = int(latest_rev["number_raw"])
                except Exception:
                    num = None

                cands = [c for c in commits.get(uid, []) if (c["ts_parsed"] or datetime.min) <= ts_rev]
                cands.sort(key=lambda x: (x["ts_parsed"] or datetime.min))
                chosen_commit = cands[-1] if cands else None

                reason = "ok"
                verified = False
                if chosen_commit is None:
                    reason = "no_commit_before_reveal"
                elif num is None:
                    reason = "number_not_int"
                elif not (ALLOWED_MIN <= num <= ALLOWED_MAX):
                    reason = "out_of_range"
                else:
                    pre = f"{uid}|{num}|{latest_rev['nonce']}"
                    verified = (sha256(pre) == chosen_commit["commit"])
                    if not verified:
                        reason = "hash_mismatch"

                verified_rows.append({
                    "uni_id": uid,
                    "number": num,
                    "verified": verified,
                    "reason": reason,
                    "commit": chosen_commit["commit"] if chosen_commit else "",
                    "nonce": latest_rev["nonce"],
                    "timestamp_utc": latest_rev["timestamp_utc"],
                })

            valid = [(r["uni_id"], r["number"]) for r in verified_rows if r["verified"] and r["number"] is not None]

            if valid:
                avg_val = mean(n for _, n in valid)
                target = K_FACTOR * avg_val
                for r in verified_rows:
                    r["distance"] = round(abs(r["number"] - target), 6) if r["verified"] else None

                min_dist = min(r["distance"] for r in verified_rows if r["verified"])
                winners = [r["uni_id"] for r in verified_rows if r["verified"] and abs(r["distance"] - min_dist) < 1e-12]

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Valid Participants", len(valid))
                col2.metric("Class Average", f"{avg_val:.4f}")
                col3.metric("Target (2/3 Avg)", f"{target:.4f}")
                col4.metric("Winner(s)", ", ".join(winners))
            else:
                st.warning("No valid verified reveals found yet.")

            df_leader = pd.DataFrame(verified_rows)
            st.markdown("### Class Leaderboard")
            st.dataframe(df_leader, use_container_width=True)

            st.download_button(
                "Download class_leaderboard.csv",
                data=df_leader.to_csv(index=False).encode("utf-8"),
                file_name="class_leaderboard.csv",
                mime="text/csv"
            )
        except Exception as e:
            st.error(f"Error fetching or processing ledger: {e}")
