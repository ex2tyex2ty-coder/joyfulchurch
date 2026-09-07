"""Private, notification-only Supabase Realtime authorization.

The browser gets a publishable key and its own anonymous Auth session only.
Message bodies stay behind AudioStore's server-side authorization.
"""
import base64
import json
import re
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from audio_requests import AudioError, digest


def validate_settings(url, key):
    url = url.rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", url):
        raise AudioError("[R01] AUDIO_SUPABASE_URL에는 Supabase Project URL을 넣어 주세요.")
    if not key.startswith("sb_publishable_"):
        raise AudioError("[R01] AUDIO_SUPABASE_PUBLISHABLE_KEY에는 Publishable key를 넣어 주세요. 비밀 키는 사용하지 않아요.")
    return url


def verify_browser(url, key, token):
    """Do not trust a browser-supplied UID or unsigned JWT claims."""
    url = validate_settings(url, key)
    try:
        if not isinstance(token, str) or not 30 <= len(token) <= 12000:
            raise ValueError()
        request = Request(url + "/auth/v1/user", headers={"apikey": key, "Authorization": "Bearer " + token})
        with urlopen(request, timeout=8) as response:
            user = json.load(response)
        uid = str(uuid.UUID(user["id"]))
        # Auth validated the signature above. Expiry only bounds the DB lease.
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if claims.get("sub") != uid or claims.get("role") != "authenticated":
            raise ValueError()
        expires = min(float(claims["exp"]), time.time()+3600)
        if expires <= time.time()+10:
            raise ValueError()
        return uid, expires
    except Exception:
        raise AudioError("[R02] 실시간 수신 인증을 확인하지 못했어요. 다시 연결해 주세요.") from None


def install(store):
    if store.test_path:
        return
    sql = Path(__file__).with_name("audio_realtime.sql").read_text(encoding="utf-8")
    with store.transaction() as conn:
        # This is fixed bundled SQL, never user input; no credential interpolation.
        conn.execute(sql, prepare=False)


def authorize(store, uid, expires, *, participant_token=None, room_id=None, engineer_until=0):
    with store.transaction() as conn:
        if participant_token:
            person = store.person(conn, participant_token)
            room = store.room(conn, person["room_id"])
            topic = "sound:person:" + person["id"]
        else:
            if engineer_until <= time.time():
                raise AudioError("음향석 접근번호를 다시 입력해 주세요.")
            room = store.room(conn, room_id)
            topic = "sound:room:" + room["id"]
            expires = min(expires, engineer_until)
        expires = min(expires, room["expires_at"])
        store.sql(conn, "INSERT INTO sound_receivers(user_id,topic,expires_at) VALUES(?,?,?) ON CONFLICT(user_id,topic) DO UPDATE SET expires_at=excluded.expires_at", (uid,topic,expires))
        return topic, expires


def authorization_key(token, scope):
    return digest(token + "|" + scope)
