"""Participant categories and deliberately ordered, unambiguous request presets."""
GROUPS = ("싱어", "세션", "키즈룸")
INSTRUMENTS = ("메인", "세컨", "베이스", "드럼", "일렉", "어쿠", "카혼")
CUSTOM_INSTRUMENT = "직접 입력"


def clean_instrument(location, instrument):
    # Preserve legacy 예배팀 memberships; never infer someone's instrument/role.
    if location not in (*GROUPS, "예배팀"):
        raise ValueError("싱어, 세션, 키즈룸 중에서 선택해 주세요.")
    if location != "세션":
        return ""
    value = " ".join(str(instrument or "").split())
    if not value or len(value) > 30 or value == CUSTOM_INSTRUMENT:
        raise ValueError("악기를 선택하거나 악기 이름을 1~30자로 직접 입력해 주세요.")
    return value


def selected_instrument(location, preset="", custom=""):
    return clean_instrument(location, custom.strip() or ("" if preset == CUSTOM_INSTRUMENT else preset))


def request_sender(request):
    parts = [request.get("location") or "예배팀", request.get("instrument", ""), request["alias"]]
    return " · ".join(dict.fromkeys(p for p in parts if p))


def request_groups(person):
    """Order is a practical default, not inferred from usage analytics.

    Each row is (short button label, full request stored for the engineer).
    Volume adjustments explicitly name the requester's monitor, not the PA.
    """
    group = person.get("location", "예배팀")
    if group == "키즈룸":
        return [(s, s) for s in ("예배 소리 키워주세요", "예배 소리 줄여주세요", "예배 소리가 안 들려요", "도움이 필요해요")], []
    if group == "싱어":
        common = [
            ("내 목소리 키워주세요", "제 모니터에서 제 목소리를 키워주세요."),
            ("내 목소리 줄여주세요", "제 모니터에서 제 목소리를 줄여주세요."),
            ("반주 키워주세요", "제 모니터에서 반주 소리를 키워주세요."),
            ("반주 줄여주세요", "제 모니터에서 반주 소리를 줄여주세요."),
            ("모니터가 안 들려요", "제 모니터에서 소리가 들리지 않아요. 확인해 주세요."),
            ("도움이 필요해요", "도움이 필요해요"),
        ]
        extra = [
            ("마이크 소리 확인", "마이크 소리가 나오지 않는 것 같아요. 확인해 주세요."),
            ("마이크가 끊겨요", "마이크 소리가 중간중간 끊겨요. 확인해 주세요."),
            ("삐 소리·하울링", "삐 소리(하울링)가 나요. 확인해 주세요."),
            ("마이크 배터리 확인", "마이크 배터리 상태를 확인해 주세요."),
        ]
        return common, extra
    if group == "세션":
        instrument = person.get("instrument") or person["alias"]
        common = [
            ("내 악기 키워주세요", f"제 모니터에서 {instrument} 소리를 키워주세요."),
            ("내 악기 줄여주세요", f"제 모니터에서 {instrument} 소리를 줄여주세요."),
            ("싱어 소리 키워주세요", "제 모니터에서 싱어 목소리를 키워주세요."),
            ("싱어 소리 줄여주세요", "제 모니터에서 싱어 목소리를 줄여주세요."),
            ("모니터가 안 들려요", "제 모니터에서 소리가 들리지 않아요. 확인해 주세요."),
            ("도움이 필요해요", "도움이 필요해요"),
        ]
        extra = [
            ("악기 소리 확인", f"{instrument} 소리가 나오지 않는 것 같아요. 신호를 확인해 주세요."),
            ("노이즈·잡음 확인", f"{instrument} 연주 중 노이즈·잡음이 들려요. 확인해 주세요."),
            ("케이블 연결 확인", f"{instrument} 케이블 연결을 확인해 주세요."),
        ]
        # Acoustic percussion usually has no instrument power switch.
        if instrument not in {"드럼", "카혼"}:
            extra += [("장비 전원 켜주세요", f"{instrument} 관련 장비 전원을 켜주세요. 음향석에서 확인 후 조치해 주세요."),
                      ("장비 전원 꺼주세요", f"{instrument} 관련 장비 전원을 꺼주세요. 음향석에서 확인 후 조치해 주세요.")]
        return common, extra
    # Old saved identities retain their controls until explicitly reclassified.
    legacy = ["내 목소리 올려주세요", "내 목소리 내려주세요", "반주 올려주세요", "반주 내려주세요",
              "모니터가 안 들려요", "전원 켜주세요", "전원 꺼주세요", "담당자 도움이 필요해요"]
    return [(s, s) for s in legacy], []
