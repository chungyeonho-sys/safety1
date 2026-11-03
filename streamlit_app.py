"""안전골든벨 퀴즈게임 - Streamlit 버전

실행:  streamlit run streamlit_app.py
문제:  questions.json (웹 버전과 같은 파일을 사용)
순위:  rankings.json (서버에 저장, 접속한 모든 사람이 같은 순위를 봄)
"""

from __future__ import annotations

import html
import json
import os
import random
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import streamlit as st

# ===== 상수 =====
BASE_DIR = Path(__file__).parent
QUESTIONS_FILE = BASE_DIR / "questions.json"
RANKINGS_FILE = BASE_DIR / "rankings.json"

CATEGORIES: list[tuple[str, str]] = [
    ("안전", "🦺"),
    ("보건", "🩺"),
    ("환경", "🌿"),
    ("소방", "🔥"),
    ("위험물", "⚠️"),
    ("시험실화학물질", "🧪"),
]
CATEGORY_NAMES = [name for name, _ in CATEGORIES]
ALL_CATEGORY = "전체"
ALL_ICON = "🏆"
CATEGORY_COLORS = {
    "안전": "#ff8a00",
    "보건": "#14b8a6",
    "환경": "#22c55e",
    "소방": "#ef4444",
    "위험물": "#facc15",
    "시험실화학물질": "#a78bfa",
    ALL_CATEGORY: "#f5b700",
}

POINTS_PER_QUESTION = 10
TIME_LIMIT_SEC = 20
NAME_MAX = 10
RANKING_LIMIT = 10   # 순위표에 보여줄 인원
RANKING_KEEP = 100   # 카테고리별로 보관할 최대 기록 수
OPTION_MARKS = ["①", "②", "③", "④", "⑤"]
MEDALS = ["🥇", "🥈", "🥉"]
KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="안전골든벨", page_icon="🔔", layout="centered")


# ===== 유틸 =====
def esc(text: Any) -> str:
    """HTML로 그릴 때 사용자 입력·문제 문장을 안전하게 바꿉니다."""
    return html.escape(str(text))


def category_icon(name: str | None) -> str:
    if name == ALL_CATEGORY:
        return ALL_ICON
    return dict(CATEGORIES).get(name or "", "")


def format_time(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}분 {s}초" if m else f"{s}초"


def format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y.%m.%d %H:%M")
    except (TypeError, ValueError):
        return "-"


def get_grade(rate: int) -> str:
    if rate == 100:
        return "🔔 골든벨 달성!"
    if rate >= 80:
        return "안전 전문가"
    if rate >= 60:
        return "안전 실천가"
    return "조금 더 공부해요"


# ===== 문제 데이터 =====
@st.cache_data
def load_questions() -> list[dict[str, Any]]:
    data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    valid = [
        q for q in data
        if q.get("category") in CATEGORY_NAMES
        and isinstance(q.get("options"), list) and len(q["options"]) == 5
        and isinstance(q.get("answer"), int) and 0 <= q["answer"] <= 4
    ]
    if len(valid) != len(data):
        raise ValueError(f"형식이 잘못된 문제가 {len(data) - len(valid)}개 있습니다.")
    return valid


# ===== 순위 기록 (rankings.json) =====
@st.cache_resource
def rankings_lock() -> threading.Lock:
    # 스크립트는 매번 다시 실행되므로, 잠금은 cache_resource로 하나만 만들어 공유합니다.
    return threading.Lock()


def is_valid_record(r: Any) -> bool:
    def is_num(v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    return (
        isinstance(r, dict)
        and isinstance(r.get("name"), str)
        and isinstance(r.get("category"), str)
        and is_num(r.get("score"))
        and is_num(r.get("timeSec"))
        and isinstance(r.get("date"), str)
    )


def sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
    # 점수 내림차순 → 소요 시간 오름차순 → 기록 일시 오름차순
    return (-r["score"], r["timeSec"], r["date"])


def load_records() -> list[dict[str, Any]]:
    try:
        data = json.loads(RANKINGS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as err:
        print(f"[안전골든벨] 순위 기록을 읽지 못했습니다: {err}")
        return []
    return [r for r in data if is_valid_record(r)] if isinstance(data, list) else []


def prune_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_category.setdefault(r["category"], []).append(r)
    return [r for rows in by_category.values() for r in sorted(rows, key=sort_key)[:RANKING_KEEP]]


def write_records(records: list[dict[str, Any]]) -> None:
    # 임시 파일에 쓴 뒤 바꿔치기해서, 쓰는 도중 문제가 생겨도 파일이 깨지지 않게 합니다.
    fd, tmp = tempfile.mkstemp(dir=BASE_DIR, prefix=".rankings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        os.replace(tmp, RANKINGS_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_record(record: dict[str, Any]) -> bool:
    try:
        with rankings_lock():
            records = load_records()
            records.append(record)
            write_records(prune_records(records))
        return True
    except OSError as err:
        print(f"[안전골든벨] 순위 기록을 저장하지 못했습니다: {err}")
        return False


def clear_records() -> None:
    try:
        with rankings_lock():
            RANKINGS_FILE.unlink(missing_ok=True)
    except OSError as err:
        print(f"[안전골든벨] 순위 기록을 초기화하지 못했습니다: {err}")


def get_ranking(category: str) -> list[dict[str, Any]]:
    """카테고리 전체 순위. 방금 기록은 저장에 실패했어도 포함합니다."""
    rows = [r for r in load_records() if r["category"] == category]
    mine = st.session_state.last_record
    if mine and mine["category"] == category and not any(r.get("id") == mine["id"] for r in rows):
        rows.append(mine)
    return sorted(rows, key=sort_key)


def is_mine(r: dict[str, Any]) -> bool:
    mine = st.session_state.last_record
    return bool(mine and r.get("id") == mine["id"])


# ===== 게임 상태 =====
def init_state() -> None:
    defaults: dict[str, Any] = {
        "screen": "start",          # start / category / quiz / result / ranking
        "player_name": "",
        "category": None,
        "questions": [],
        "index": 0,
        "score": 0,
        "answers": [],              # {question, selected(None=시간 초과), correct}
        "start_time": 0.0,
        "question_start": 0.0,
        "locked": False,            # 현재 문제의 답이 확정되었는지
        "frozen_remaining": TIME_LIMIT_SEC,
        "result": None,
        "celebrate": False,
        "last_record": None,
        "rank_cat": CATEGORY_NAMES[0],
        "confirm_quit": False,
        "confirm_reset": False,
        "name_error": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go(screen: str) -> None:
    st.session_state.screen = screen
    st.session_state.confirm_quit = False
    st.session_state.confirm_reset = False


def handle_start() -> None:
    s = st.session_state
    name = s.name_input.strip()
    if not 1 <= len(name) <= NAME_MAX:
        s.name_error = f"이름을 1~{NAME_MAX}자로 입력해 주세요."
        return
    s.name_error = ""
    s.player_name = name
    go("category")


def start_game(category: str) -> None:
    s = st.session_state
    pool = load_questions() if category == ALL_CATEGORY else [
        q for q in load_questions() if q["category"] == category
    ]
    questions = pool[:]
    random.shuffle(questions)
    now = time.time()
    s.update(
        category=category,
        questions=questions,
        index=0,
        score=0,
        answers=[],
        start_time=now,
        question_start=now,
        locked=False,
        frozen_remaining=TIME_LIMIT_SEC,
        last_record=None,
        result=None,
    )
    go("quiz")


def remaining_seconds() -> int:
    elapsed = time.time() - st.session_state.question_start
    return max(0, TIME_LIMIT_SEC - int(elapsed))


def submit_answer(selected: int | None) -> None:
    """클릭·시간 초과 모두 이 함수 하나로 처리합니다. locked로 중복 처리를 막습니다."""
    s = st.session_state
    if s.locked or s.screen != "quiz":
        return
    # 서버 기준으로 제한시간을 넘겼으면 클릭이 늦게 도착했어도 시간 초과로 처리합니다.
    if selected is not None and time.time() - s.question_start > TIME_LIMIT_SEC + 0.5:
        selected = None
    s.locked = True
    s.frozen_remaining = remaining_seconds()
    q = s.questions[s.index]
    correct = selected == q["answer"]
    if correct:
        s.score += POINTS_PER_QUESTION
    s.answers.append({"question": q, "selected": selected, "correct": correct})


def go_next() -> None:
    s = st.session_state
    if not s.locked or s.screen != "quiz":
        return
    if s.index >= len(s.questions) - 1:
        finish_game()
        return
    s.index += 1
    s.locked = False
    s.question_start = time.time()
    s.frozen_remaining = TIME_LIMIT_SEC


def ask_quit() -> None:
    st.session_state.confirm_quit = True


def cancel_quit() -> None:
    st.session_state.confirm_quit = False


def quit_game() -> None:
    st.session_state.locked = True
    go("category")


def finish_game() -> None:
    s = st.session_state
    total = len(s.questions)
    correct_count = sum(1 for a in s.answers if a["correct"])
    rate = round(correct_count / total * 100)
    time_sec = max(1, round(time.time() - s.start_time))
    record = {
        "id": uuid.uuid4().hex,
        "name": s.player_name,
        "category": s.category,
        "score": s.score,
        "correct": correct_count,
        "total": total,
        "timeSec": time_sec,
        "date": datetime.now(timezone.utc).isoformat(),
    }
    saved = save_record(record)
    s.last_record = record
    s.result = {"total": total, "correct": correct_count, "rate": rate, "time_sec": time_sec, "saved": saved}
    s.celebrate = rate == 100
    go("result")


def show_ranking(category: str | None = None) -> None:
    st.session_state.rank_cat = category or CATEGORY_NAMES[0]
    go("ranking")


def on_rank_tab_change() -> None:
    st.session_state.rank_cat = st.session_state.rank_radio


def ask_reset() -> None:
    st.session_state.confirm_reset = True


def cancel_reset() -> None:
    st.session_state.confirm_reset = False


def do_reset() -> None:
    clear_records()
    st.session_state.last_record = None
    st.session_state.confirm_reset = False


# ===== 디자인 =====
def inject_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
:root {
  --gb-surface: #13254a; --gb-surface-2: #1a3160; --gb-border: #2f4c84;
  --gb-text: #f4f6fb; --gb-muted: #b8c3dc;
  --gb-gold: #f5b700; --gb-gold-strong: #ffcc33; --gb-on-gold: #1a1300;
  --gb-correct: #1b7a43; --gb-wrong: #c62828;
  --gb-correct-text: #7ee2a8; --gb-wrong-text: #ff9a9a;
}
html, body, [class*="st-"], button, input { font-family: "Noto Sans KR", sans-serif; }
.stApp { background: radial-gradient(ellipse 80% 50% at 50% -10%, #17305f, transparent 70%), #0b1730; }
.stButton > button { min-height: 52px; font-size: 1.05rem; font-weight: 700; border-radius: 12px; }
/* 골드 주 버튼은 어두운 글자 (Streamlit 버전마다 data-testid가 달라 넓게 지정) */
.stApp button[kind*="rimary"], .stApp button[data-testid*="rimary"],
.stApp button[kind*="rimary"] p, .stApp button[data-testid*="rimary"] p { color: var(--gb-on-gold) !important; }
.gb-hero { text-align: center; padding: 8px 0 4px; }
.gb-bell { font-size: 4rem; line-height: 1; display: inline-block; transform-origin: 50% 10%;
  animation: gb-swing 2.4s ease-in-out infinite; filter: drop-shadow(0 6px 20px rgba(245,183,0,.55)); }
@keyframes gb-swing { 0%,60%,100% { transform: rotate(0); } 10% { transform: rotate(14deg); }
  20% { transform: rotate(-12deg); } 30% { transform: rotate(8deg); } 40% { transform: rotate(-5deg); } }
.gb-title { font-size: clamp(2.4rem, 9vw, 3.6rem); font-weight: 900; margin: 4px 0 0; color: var(--gb-text); }
.gb-title span { color: var(--gb-gold-strong); }
.gb-sub { color: var(--gb-muted); word-break: keep-all; }
.gb-card { background: var(--gb-surface); border: 1px solid var(--gb-border); border-radius: 16px;
  padding: 18px 20px; margin: 8px 0 12px; }
.gb-card ul { margin: 0; padding-left: 1.2em; }
.gb-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.gb-chip { padding: 4px 14px; border-radius: 999px; background: var(--gb-surface);
  border: 1px solid var(--gb-border); font-weight: 700; }
.gb-chip.score { color: var(--gb-gold-strong); }
.gb-timer { font-weight: 700; font-size: 1.05rem; }
.gb-timer.warning { color: #ff6b6b; }
.gb-question { font-size: clamp(1.2rem, 3.6vw, 1.5rem); font-weight: 700; line-height: 1.5;
  word-break: keep-all; border-left: 6px solid var(--gb-cat, var(--gb-gold)); }
.gb-option { display: flex; align-items: center; gap: 12px; padding: 12px 16px; margin-bottom: 8px;
  border-radius: 12px; border: 2px solid var(--gb-border); background: var(--gb-surface); opacity: .62; }
.gb-option.correct { background: var(--gb-correct); border-color: #6fdc9d; color: #fff; opacity: 1; }
.gb-option.wrong { background: var(--gb-wrong); border-color: #ff9a9a; color: #fff; opacity: 1; }
.gb-option .mark { font-weight: 900; color: var(--gb-gold-strong); }
.gb-option.correct .mark, .gb-option.wrong .mark { color: #fff; }
.gb-option .text { flex: 1; word-break: keep-all; }
.gb-option .res { font-size: 1.3rem; font-weight: 900; }
.gb-feedback { border-radius: 16px; padding: 14px 18px; border: 2px solid; margin: 8px 0 12px; }
.gb-feedback.ok { background: rgba(46,204,113,.16); border-color: var(--gb-correct); }
.gb-feedback.ng { background: rgba(239,83,80,.16); border-color: var(--gb-wrong); }
.gb-feedback .title { font-size: 1.3rem; font-weight: 900; margin: 0 0 4px; }
.gb-feedback.ok .title { color: var(--gb-correct-text); }
.gb-feedback.ng .title { color: var(--gb-wrong-text); }
.gb-feedback p { margin: 4px 0; word-break: keep-all; }
.gb-result { text-align: center; }
.gb-score { font-size: clamp(3.2rem, 15vw, 5rem); font-weight: 900; color: var(--gb-gold-strong); line-height: 1.1; }
.gb-grade { display: inline-block; padding: 6px 20px; border-radius: 999px; font-weight: 900;
  border: 2px solid var(--gb-gold); color: var(--gb-gold-strong); background: rgba(245,183,0,.16); }
.gb-grade.golden { background: var(--gb-gold); color: var(--gb-on-gold); }
.gb-table { width: 100%; border-collapse: collapse; }
.gb-table th, .gb-table td { padding: 10px 8px; border-bottom: 1px solid var(--gb-border); text-align: left; }
.gb-table th { color: var(--gb-muted); font-weight: 500; white-space: nowrap; }
.gb-table td:first-child, .gb-table th:first-child { text-align: center; width: 3.5em; font-weight: 900; }
.gb-table td.score { color: var(--gb-gold-strong); font-weight: 700; white-space: nowrap; }
.gb-table td.time { white-space: nowrap; }
.gb-table td.name { word-break: break-all; }
.gb-table tr.mine td { background: rgba(245,183,0,.16); border-top: 2px solid var(--gb-gold); border-bottom: 2px solid var(--gb-gold); }
.gb-table tr.gap td { text-align: center; color: var(--gb-muted); padding: 2px; }
.gb-badge { display: inline-block; margin-left: 6px; padding: 0 8px; border-radius: 999px;
  background: var(--gb-gold); color: var(--gb-on-gold); font-weight: 900; white-space: nowrap; }
@media (max-width: 520px) { .gb-table th:nth-child(5), .gb-table td:nth-child(5) { display: none; } }
@media (prefers-reduced-motion: reduce) { .gb-bell { animation: none; } }
</style>
""",
        unsafe_allow_html=True,
    )


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


# ===== 화면: 시작 (FR-01) =====
def render_start() -> None:
    s = st.session_state
    html_block(
        '<div class="gb-hero"><div class="gb-bell">🔔</div>'
        '<p class="gb-title">안전<span>골든벨</span></p>'
        '<p class="gb-sub">안전 · 보건 · 환경 · 소방 · 위험물 · 시험실화학물질</p></div>'
        '<div class="gb-card"><b>게임 방법</b><ul>'
        "<li>5지선다 객관식 퀴즈입니다.</li>"
        "<li>카테고리를 고르면 해당 분야 10문제가 출제됩니다.</li>"
        f"<li>문제당 {TIME_LIMIT_SEC}초, 한 문제에 {POINTS_PER_QUESTION}점입니다.</li>"
        "<li>답을 고르면 바로 정답과 해설을 알려 드립니다.</li></ul></div>"
    )
    # form 안에서는 이름 칸에서 Enter를 눌러도 시작됩니다.
    with st.form("start_form", border=False):
        st.text_input(
            "참가자 이름", value=s.player_name, max_chars=NAME_MAX,
            placeholder=f"1~{NAME_MAX}자로 입력하세요", key="name_input",
        )
        st.form_submit_button("게임 시작", type="primary", use_container_width=True, on_click=handle_start)
    if s.name_error:
        st.error(s.name_error)
    st.button("🏆 순위 보기", use_container_width=True, on_click=show_ranking)


# ===== 화면: 카테고리 선택 (FR-02) =====
def render_category() -> None:
    questions = load_questions()
    st.subheader(f"{st.session_state.player_name}님, 도전할 분야를 고르세요")
    cols = st.columns(3)
    for i, (name, icon) in enumerate(CATEGORIES):
        count = sum(1 for q in questions if q["category"] == name)
        cols[i % 3].button(
            f"{icon} {name}  \n{count}문제", key=f"cat_{name}",
            use_container_width=True, on_click=start_game, args=(name,),
        )
    st.button(
        f"🏆 전체 도전 ({len(questions)}문제)", type="primary",
        use_container_width=True, on_click=start_game, args=(ALL_CATEGORY,),
    )
    st.button("← 처음으로 (이름 바꾸기)", use_container_width=True, on_click=go, args=("start",))


# ===== 화면: 문제 풀이 (FR-03, FR-04) =====
def timer_html(remaining: int) -> str:
    cls = "gb-timer warning" if remaining <= 5 else "gb-timer"
    return f'<div class="{cls}">⏱ 남은 시간 {remaining}초</div>'


@st.fragment(run_every=1)
def live_timer() -> None:
    """1초마다 이 부분만 다시 그립니다. 시간이 다 되면 시간 초과로 처리하고 화면 전체를 새로 그립니다."""
    s = st.session_state
    if s.screen != "quiz" or s.locked:
        return
    remaining = remaining_seconds()
    if remaining <= 0:
        submit_answer(None)
        st.rerun()
    html_block(timer_html(remaining))
    st.progress(remaining / TIME_LIMIT_SEC)


def render_quiz() -> None:
    s = st.session_state
    q = s.questions[s.index]
    total = len(s.questions)
    color = CATEGORY_COLORS.get(s.category, "#f5b700")

    html_block(
        '<div class="gb-chips">'
        f'<span class="gb-chip" style="border-color:{color}">{category_icon(s.category)} {esc(s.category)}</span>'
        f'<span class="gb-chip">{s.index + 1} / {total}</span>'
        f'<span class="gb-chip score">{s.score}점</span></div>'
    )
    st.progress((s.index + 1) / total)

    if s.locked:
        html_block(timer_html(s.frozen_remaining).replace(" warning", ""))
    else:
        live_timer()

    html_block(f'<div class="gb-card gb-question" style="--gb-cat:{color}">{esc(q["question"])}</div>')

    if not s.locked:
        for i, option in enumerate(q["options"]):
            st.button(
                f"{OPTION_MARKS[i]}  {option}", key=f"opt_{s.index}_{i}",
                use_container_width=True, on_click=submit_answer, args=(i,),
            )
    else:
        render_feedback(q, s.answers[-1])
        is_last = s.index >= total - 1
        st.button("결과 보기" if is_last else "다음 문제", type="primary",
                  use_container_width=True, on_click=go_next)

    st.write("")
    if s.confirm_quit:
        st.warning("게임을 그만둘까요? 이번 게임 기록은 저장되지 않습니다.")
        c1, c2 = st.columns(2)
        c1.button("그만두기", use_container_width=True, on_click=quit_game)
        c2.button("계속하기", type="primary", use_container_width=True, on_click=cancel_quit)
    else:
        st.button("그만두기", on_click=ask_quit)


def render_feedback(q: dict[str, Any], answer: dict[str, Any]) -> None:
    selected = answer["selected"]
    rows = []
    for i, option in enumerate(q["options"]):
        if i == q["answer"]:
            cls, mark = "correct", "✔"
        elif i == selected:
            cls, mark = "wrong", "✖"
        else:
            cls, mark = "", ""
        rows.append(
            f'<div class="gb-option {cls}"><span class="mark">{OPTION_MARKS[i]}</span>'
            f'<span class="text">{esc(option)}</span><span class="res">{mark}</span></div>'
        )
    html_block("".join(rows))

    if answer["correct"]:
        title, cls, extra = "✔ 정답입니다!", "ok", ""
    else:
        title = "⏰ 시간 초과! 오답입니다" if selected is None else "✖ 오답입니다"
        cls = "ng"
        extra = f'<p><b>정답: {OPTION_MARKS[q["answer"]]} {esc(q["options"][q["answer"]])}</b></p>'
    html_block(
        f'<div class="gb-feedback {cls}"><p class="title">{title}</p>{extra}'
        f'<p>💡 {esc(q["explanation"])}</p></div>'
    )


# ===== 화면: 결과 (FR-05) =====
def render_result() -> None:
    s = st.session_state
    r = s.result
    if s.celebrate:
        st.balloons()
        s.celebrate = False

    grade_cls = "gb-grade golden" if r["rate"] == 100 else "gb-grade"
    html_block(
        '<div class="gb-card gb-result">'
        f'<p class="gb-sub">{esc(s.player_name)}님 · {category_icon(s.category)} {esc(s.category)}</p>'
        f'<div class="gb-score">{s.score}점</div>'
        f'<span class="{grade_cls}">{get_grade(r["rate"])}</span></div>'
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("정답", f'{r["correct"]} / {r["total"]}')
    c2.metric("정답률", f'{r["rate"]}%')
    c3.metric("소요 시간", format_time(r["time_sec"]))
    if not r["saved"]:
        st.warning("순위 기록을 저장하지 못했습니다. 이번 기록은 이 화면에서만 볼 수 있습니다.")

    wrongs = [a for a in s.answers if not a["correct"]]
    if not wrongs:
        st.success("틀린 문제가 없습니다. 완벽해요!")
    else:
        with st.expander(f"틀린 문제 다시 보기 ({len(wrongs)}개)"):
            for a in wrongs:
                q, sel = a["question"], a["selected"]
                mine = "시간 초과" if sel is None else f"{OPTION_MARKS[sel]} {q['options'][sel]}"
                html_block(
                    f'<div class="gb-card"><p><b>{esc(q["question"])}</b></p>'
                    f'<p style="color:var(--gb-wrong-text)">✖ 내 답: {esc(mine)}</p>'
                    f'<p style="color:var(--gb-correct-text)">✔ 정답: {OPTION_MARKS[q["answer"]]} {esc(q["options"][q["answer"]])}</p>'
                    f'<p class="gb-sub">{esc(q["explanation"])}</p></div>'
                )

    c1, c2, c3 = st.columns(3)
    c1.button("🔄 다시 하기", type="primary", use_container_width=True, on_click=start_game, args=(s.category,))
    c2.button("📚 다른 카테고리", use_container_width=True, on_click=go, args=("category",))
    c3.button("🏆 순위 보기", use_container_width=True, on_click=show_ranking, args=(s.category,))


# ===== 화면: 순위 (FR-06) =====
def ranking_row(r: dict[str, Any], rank: int) -> str:
    mine = is_mine(r)
    rank_cell = MEDALS[rank - 1] if rank <= 3 else str(rank)
    badge = '<span class="gb-badge">방금 기록</span>' if mine else ""
    return (
        f'<tr class="{"mine" if mine else ""}"><td>{rank_cell}</td>'
        f'<td class="name">{esc(r["name"])}{badge}</td>'
        f'<td class="score">{int(r["score"])}점</td>'
        f'<td class="time">{format_time(int(r["timeSec"]))}</td>'
        f'<td>{format_date(r["date"])}</td></tr>'
    )


def render_ranking() -> None:
    s = st.session_state
    st.subheader("🏆 명예의 전당")
    tabs = CATEGORY_NAMES + [ALL_CATEGORY]
    st.radio(
        "카테고리", tabs, index=tabs.index(s.rank_cat), horizontal=True,
        format_func=lambda n: f"{category_icon(n)} {n}",
        key="rank_radio", on_change=on_rank_tab_change, label_visibility="collapsed",
    )

    ranking = get_ranking(s.rank_cat)
    if not ranking:
        st.info("아직 기록이 없습니다.")
    else:
        rows = [ranking_row(r, i + 1) for i, r in enumerate(ranking[:RANKING_LIMIT])]
        my_index = next((i for i, r in enumerate(ranking) if is_mine(r)), -1)
        if my_index >= RANKING_LIMIT:  # 방금 기록이 10위 밖이면 구분선 아래에 내 순위
            rows.append('<tr class="gap"><td colspan="5">⋯</td></tr>')
            rows.append(ranking_row(ranking[my_index], my_index + 1))
        html_block(
            '<div class="gb-card"><table class="gb-table"><thead><tr>'
            "<th>순위</th><th>이름</th><th>점수</th><th>소요 시간</th><th>일시</th>"
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        )

    st.button("처음으로", type="primary", use_container_width=True, on_click=go, args=("start",))
    if s.confirm_reset:
        st.warning("모든 카테고리의 순위 기록이 삭제됩니다. 초기화할까요?")
        c1, c2 = st.columns(2)
        c1.button("초기화", use_container_width=True, on_click=do_reset)
        c2.button("취소", type="primary", use_container_width=True, on_click=cancel_reset)
    else:
        st.button("순위 초기화", on_click=ask_reset)


# ===== 실행 =====
def main() -> None:
    init_state()
    inject_css()
    try:
        load_questions()
    except (OSError, ValueError) as err:
        st.error(f"문제를 불러오지 못했습니다. questions.json 파일을 확인해 주세요. ({err})")
        st.stop()

    screens = {
        "start": render_start,
        "category": render_category,
        "quiz": render_quiz,
        "result": render_result,
        "ranking": render_ranking,
    }
    screen = st.session_state.screen
    if screen == "result" and not st.session_state.result:
        screen = "start"
    screens.get(screen, render_start)()


main()
