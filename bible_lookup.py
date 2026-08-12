from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_BASE_URL = "https://rest.api.bible/v1"
FUMS_URL = "https://fums.api.bible/f3"


@dataclass(frozen=True)
class BibleReference:
    book_id: str
    book_name: str
    chapter: int
    verse: int

    @property
    def verse_id(self) -> str:
        return f"{self.book_id}.{self.chapter}.{self.verse}"

    @property
    def display(self) -> str:
        unit = "편" if self.book_id == "PSA" else "장"
        return f"{self.book_name} {self.chapter}{unit} {self.verse}절"


@dataclass(frozen=True)
class BibleVerse:
    reference: BibleReference
    content: str
    api_reference: str
    copyright: str
    fums_token: str


@dataclass(frozen=True)
class LocalBible:
    verses: dict[str, str]
    book_count: int
    invalid_line_count: int


class BibleAPIError(RuntimeError):
    pass


def decode_text_file(data: bytes) -> str:
    """Decode common Korean text-file encodings without silently accepting binary data."""
    if not data:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            raise ValueError("텍스트 파일이 아닌 것으로 보입니다.")
        return text.replace("\r\n", "\n").replace("\r", "\n")
    raise ValueError("TXT 파일의 문자 형식을 읽지 못했습니다. UTF-8 또는 한글 메모장 형식으로 저장해 주세요.")


# Canonical Korean names, API.Bible/USFM book ids, and familiar Korean abbreviations.
BOOKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("창세기", "GEN", ("창세기", "창")),
    ("출애굽기", "EXO", ("출애굽기", "출")),
    ("레위기", "LEV", ("레위기", "레")),
    ("민수기", "NUM", ("민수기", "민")),
    ("신명기", "DEU", ("신명기", "신")),
    ("여호수아", "JOS", ("여호수아", "수")),
    ("사사기", "JDG", ("사사기", "삿")),
    ("룻기", "RUT", ("룻기", "룻")),
    ("사무엘상", "1SA", ("사무엘상", "삼상")),
    ("사무엘하", "2SA", ("사무엘하", "삼하")),
    ("열왕기상", "1KI", ("열왕기상", "왕상")),
    ("열왕기하", "2KI", ("열왕기하", "왕하")),
    ("역대상", "1CH", ("역대상", "대상")),
    ("역대하", "2CH", ("역대하", "대하")),
    ("에스라", "EZR", ("에스라", "스")),
    ("느헤미야", "NEH", ("느헤미야", "느")),
    ("에스더", "EST", ("에스더", "에")),
    ("욥기", "JOB", ("욥기", "욥")),
    ("시편", "PSA", ("시편", "시")),
    ("잠언", "PRO", ("잠언", "잠")),
    ("전도서", "ECC", ("전도서", "전")),
    ("아가", "SNG", ("아가", "아")),
    ("이사야", "ISA", ("이사야", "사")),
    ("예레미야", "JER", ("예레미야", "렘")),
    ("예레미야애가", "LAM", ("예레미야애가", "애가", "애")),
    ("에스겔", "EZK", ("에스겔", "겔")),
    ("다니엘", "DAN", ("다니엘", "단")),
    ("호세아", "HOS", ("호세아", "호")),
    ("요엘", "JOL", ("요엘", "욜")),
    ("아모스", "AMO", ("아모스", "암")),
    ("오바댜", "OBA", ("오바댜", "옵")),
    ("요나", "JON", ("요나", "욘")),
    ("미가", "MIC", ("미가", "미")),
    ("나훔", "NAM", ("나훔", "나")),
    ("하박국", "HAB", ("하박국", "합")),
    ("스바냐", "ZEP", ("스바냐", "습")),
    ("학개", "HAG", ("학개", "학")),
    ("스가랴", "ZEC", ("스가랴", "슥")),
    ("말라기", "MAL", ("말라기", "말")),
    ("마태복음", "MAT", ("마태복음", "마태", "마")),
    ("마가복음", "MRK", ("마가복음", "마가", "막")),
    ("누가복음", "LUK", ("누가복음", "누가", "눅")),
    ("요한복음", "JHN", ("요한복음", "요한", "요")),
    ("사도행전", "ACT", ("사도행전", "행")),
    ("로마서", "ROM", ("로마서", "롬")),
    ("고린도전서", "1CO", ("고린도전서", "고전")),
    ("고린도후서", "2CO", ("고린도후서", "고후")),
    ("갈라디아서", "GAL", ("갈라디아서", "갈")),
    ("에베소서", "EPH", ("에베소서", "엡")),
    ("빌립보서", "PHP", ("빌립보서", "빌")),
    ("골로새서", "COL", ("골로새서", "골")),
    ("데살로니가전서", "1TH", ("데살로니가전서", "살전")),
    ("데살로니가후서", "2TH", ("데살로니가후서", "살후")),
    ("디모데전서", "1TI", ("디모데전서", "딤전")),
    ("디모데후서", "2TI", ("디모데후서", "딤후")),
    ("디도서", "TIT", ("디도서", "딛")),
    ("빌레몬서", "PHM", ("빌레몬서", "몬")),
    ("히브리서", "HEB", ("히브리서", "히")),
    ("야고보서", "JAS", ("야고보서", "약")),
    ("베드로전서", "1PE", ("베드로전서", "벧전")),
    ("베드로후서", "2PE", ("베드로후서", "벧후")),
    ("요한일서", "1JN", ("요한일서", "요일")),
    ("요한이서", "2JN", ("요한이서", "요이")),
    ("요한삼서", "3JN", ("요한삼서", "요삼")),
    ("유다서", "JUD", ("유다서", "유")),
    ("요한계시록", "REV", ("요한계시록", "계시록", "계")),
)


_ALIAS_TO_BOOK: dict[str, tuple[str, str]] = {}
for _book_name, _book_id, _aliases in BOOKS:
    for _alias in _aliases:
        _ALIAS_TO_BOOK[_alias] = (_book_name, _book_id)

_BOOK_PATTERN = "|".join(re.escape(alias) for alias in sorted(_ALIAS_TO_BOOK, key=len, reverse=True))
_RANGE_MARK = r"[~～〜\-–—]"
_KOREAN_REFERENCE_RE = re.compile(
    rf"(?P<book>{_BOOK_PATTERN})\s*(?P<chapter>[0-9]+)\s*(?:장|편)\s*"
    rf"(?P<verse>[0-9]+)\s*(?:절\s*)?(?:{_RANGE_MARK}\s*(?P<endverse>[0-9]+)\s*)?절"
)
_COLON_REFERENCE_RE = re.compile(
    rf"(?P<book>{_BOOK_PATTERN})\s*[:：]?\s*(?P<chapter>[0-9]+)\s*[:：]\s*(?P<verse>[0-9]+)"
    rf"(?:\s*{_RANGE_MARK}\s*(?P<endverse>[0-9]+))?"
)
_BIBLE_LINE_RE = re.compile(r"^\s*(?P<book>[^\d\s]+)(?P<chapter>[0-9]+):(?P<verse>[0-9]+)\s+(?P<content>.+?)\s*$")


def extract_bible_references(text: str, limit: int = 30) -> list[BibleReference]:
    """Extract Korean Bible references in appearance order and remove duplicates."""
    matches: list[tuple[int, list[BibleReference]]] = []
    for pattern in (_KOREAN_REFERENCE_RE, _COLON_REFERENCE_RE):
        for match in pattern.finditer(text or ""):
            chapter = int(match.group("chapter"))
            first_verse = int(match.group("verse"))
            end_verse_text = match.groupdict().get("endverse")
            last_verse = int(end_verse_text) if end_verse_text else first_verse
            if chapter < 1 or first_verse < 1 or last_verse < first_verse:
                continue
            book_name, book_id = _ALIAS_TO_BOOK[match.group("book")]
            references = [
                BibleReference(book_id, book_name, chapter, verse)
                for verse in range(first_verse, last_verse + 1)
            ]
            matches.append((match.start(), references))

    ordered: list[BibleReference] = []
    seen: set[str] = set()
    for _, references in sorted(matches, key=lambda item: item[0]):
        for reference in references:
            if reference.verse_id in seen:
                continue
            seen.add(reference.verse_id)
            ordered.append(reference)
            if len(ordered) >= limit:
                return ordered
    return ordered


def parse_local_bible(data: bytes, minimum_verses: int = 1_000) -> LocalBible:
    """Parse a line-oriented Korean Bible file such as `창1:1 본문`."""
    text = decode_text_file(data)
    verses: dict[str, str] = {}
    book_ids: set[str] = set()
    invalid_line_count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _BIBLE_LINE_RE.match(line)
        if not match or match.group("book") not in _ALIAS_TO_BOOK:
            invalid_line_count += 1
            continue
        chapter = int(match.group("chapter"))
        verse = int(match.group("verse"))
        content = match.group("content").strip()
        if chapter < 1 or verse < 1 or not content:
            invalid_line_count += 1
            continue
        _, book_id = _ALIAS_TO_BOOK[match.group("book")]
        verse_id = f"{book_id}.{chapter}.{verse}"
        if verse_id in verses:
            invalid_line_count += 1
            continue
        verses[verse_id] = content
        book_ids.add(book_id)

    if len(verses) < minimum_verses:
        raise ValueError(
            "성경 전체 본문 파일로 인식하지 못했습니다. 각 줄이 ‘창1:1 본문’ 형식인지 확인해 주세요."
        )
    return LocalBible(verses=verses, book_count=len(book_ids), invalid_line_count=invalid_line_count)


def fetch_local_bible_verse(local_bible: LocalBible, reference: BibleReference, source_label: str) -> BibleVerse:
    content = local_bible.verses.get(reference.verse_id, "")
    if not content:
        raise BibleAPIError("업로드한 성경 TXT에서 이 구절을 찾지 못했습니다.")
    return BibleVerse(
        reference=reference,
        content=content,
        api_reference=reference.display,
        copyright=f"사용자 제공 파일 · {source_label}",
        fums_token="",
    )


def _get_json(path: str, api_key: str, params: dict[str, str] | None = None) -> dict[str, object]:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{API_BASE_URL}{path}{query}",
        headers={"api-key": api_key, "Accept": "application/json", "User-Agent": "JoyfulWorshipOps/1.0"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = str(payload.get("message") or payload.get("error") or "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        if exc.code in {401, 403}:
            raise BibleAPIError("성경 API 키 또는 선택한 번역본의 이용 권한을 확인하세요.") from exc
        if exc.code == 404:
            raise BibleAPIError("선택한 번역본에서 이 구절을 찾지 못했습니다.") from exc
        raise BibleAPIError(f"성경 API 요청을 완료하지 못했습니다 ({exc.code}). {detail}".strip()) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BibleAPIError("성경 API에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from exc


def list_korean_bibles(api_key: str) -> list[dict[str, str]]:
    payload = _get_json("/bibles", api_key, {"language": "kor", "include-full-details": "true"})
    bibles: list[dict[str, str]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        bibles.append(
            {
                "id": str(item["id"]),
                "name": str(item.get("nameLocal") or item.get("name") or item["id"]),
                "abbreviation": str(item.get("abbreviationLocal") or item.get("abbreviation") or ""),
                "description": str(item.get("descriptionLocal") or item.get("description") or ""),
            }
        )
    return sorted(bibles, key=lambda item: (item["name"], item["id"]))


def fetch_bible_verse(api_key: str, bible_id: str, reference: BibleReference) -> BibleVerse:
    payload = _get_json(
        f"/bibles/{quote(bible_id, safe='')}/verses/{quote(reference.verse_id, safe='.')}",
        api_key,
        {
            "content-type": "text",
            "include-notes": "false",
            "include-titles": "false",
            "include-chapter-numbers": "false",
            "include-verse-numbers": "false",
            "include-verse-spans": "false",
            "fums-version": "3",
        },
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BibleAPIError("성경 API 응답에 본문이 없습니다.")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    content = re.sub(r"\s+", " ", str(data.get("content") or "")).strip()
    if not content:
        raise BibleAPIError("선택한 번역본에서 이 구절의 본문을 찾지 못했습니다.")
    return BibleVerse(
        reference=reference,
        content=content,
        api_reference=str(data.get("reference") or reference.display),
        copyright=str(data.get("copyright") or ""),
        fums_token=str(meta.get("fumsToken") or ""),
    )


def report_fums_view(tokens: Iterable[str], device_id: str, session_id: str) -> None:
    clean_tokens = [token for token in tokens if token]
    if not clean_tokens:
        return
    params: list[tuple[str, str]] = [("dId", device_id), ("sId", session_id)]
    params.extend(("t", token) for token in clean_tokens)
    request = Request(f"{FUMS_URL}?{urlencode(params)}", headers={"User-Agent": "JoyfulWorshipOps/1.0"})
    try:
        with urlopen(request, timeout=6):
            pass
    except (HTTPError, URLError, TimeoutError):
        # Tracking must not hide a verse already retrieved successfully.
        return
