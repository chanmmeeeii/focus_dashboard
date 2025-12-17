# app.py
import json
from datetime import datetime, date, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px

# -----------------------------
# Helpers
# -----------------------------
WEEK_ORDER = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_MAP = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}

def weekday_kr(d: date) -> str:
    return WEEKDAY_MAP[d.weekday()]

def parse_time_hhmm(t: str) -> datetime:
    return datetime.strptime(t.strip(), "%H:%M")

def minutes_between(start: str, end: str) -> int:
    s = parse_time_hhmm(start)
    e = parse_time_hhmm(end)
    if e <= s:
        e += timedelta(days=1)
    return int((e - s).total_seconds() // 60)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def init_store():
    # 서버 파일 저장 대신, "사용자 세션(브라우저 세션)"에 저장 → 다른 사람 데이터 섞이지 않음
    if "store" not in st.session_state:
        st.session_state.store = {"days": {}}

def store_to_flat_rows(store: dict) -> list[dict]:
    rows = []
    days = store.get("days", {})
    for date_str in sorted(days.keys()):
        day = days[date_str]
        wd = day.get("weekday", "")
        for s in day.get("sessions", []):
            rows.append({
                "id": s.get("id", ""),
                "date": date_str,
                "weekday": wd,
                "subject": s.get("subject", ""),
                "start": s.get("start", ""),
                "end": s.get("end", ""),
                "duration_min": int(s.get("duration_min", 0)),
                "focused_min": int(s.get("focused_min", 0)),
                "pause_count": int(s.get("pause_count", 0)),
                "created_at": s.get("created_at", ""),
            })
    return rows

def add_session(d: date, subject: str, start: str, end: str, pause: int, focused: int):
    store = st.session_state.store
    ds = d.strftime("%Y-%m-%d")
    if ds not in store["days"]:
        store["days"][ds] = {"weekday": weekday_kr(d), "sessions": []}

    dur = minutes_between(start, end)
    focused = clamp(int(focused), 0, dur)
    pause = max(0, int(pause))

    sid = f"{ds.replace('-','')}-{start.replace(':','')}-{str(abs(hash((ds, start, subject, now_str()))) % 10000).zfill(4)}"
    sess = {
        "id": sid,
        "subject": subject.strip() or "공부",
        "start": start.strip(),
        "end": end.strip(),
        "duration_min": dur,         # duration = 총 학습 시도 시간(분)
        "focused_min": focused,      # focused  = 순수 집중 시간(분)
        "pause_count": pause,        # pause    = 중단 횟수
        "created_at": now_str(),
    }
    store["days"][ds]["sessions"].append(sess)

def delete_session(session_id: str):
    store = st.session_state.store
    days = store.get("days", {})
    empty = []
    for ds, day in days.items():
        before = len(day.get("sessions", []))
        day["sessions"] = [s for s in day.get("sessions", []) if s.get("id") != session_id]
        if before != len(day["sessions"]) and len(day["sessions"]) == 0:
            empty.append(ds)
    for ds in empty:
        days.pop(ds, None)

def compute_kpis(df: pd.DataFrame):
    if df.empty:
        return None

    total = int(df["duration_min"].sum())
    focused = int((df.apply(lambda r: clamp(int(r["focused_min"]), 0, int(r["duration_min"])), axis=1)).sum())
    pause = int(df["pause_count"].sum())

    ratio = (focused / total) if total > 0 else 0.0
    avg_focus = ratio * 5
    pause_rate = (pause / (total / 60)) if total > 0 else 0.0

    return {
        "total": total,
        "focused": focused,
        "pause": pause,
        "ratio": ratio,
        "avg_focus": avg_focus,
        "pause_rate": pause_rate,
        "sessions": len(df),
    }

# -----------------------------
# Page
# -----------------------------
st.set_page_config(page_title="집중도 대시보드", page_icon="📊", layout="wide")
init_store()

st.title("📊 집중도 대시보드")
st.caption("학생 행동 데이터 기반 · 세션 입력/삭제 + 기간 선택 분석")

# -----------------------------
# Sidebar: 입력
# -----------------------------
with st.sidebar:
    st.header("✍️ 세션 기록")

    d = st.date_input("날짜 선택", value=date.today())
    n = st.number_input("세션 개수", min_value=1, max_value=20, value=1, step=1)

    st.divider()
    st.write("아래에서 세션 정보를 입력하세요. (시간 입력 시 총 시간이 자동 계산됩니다)")

    inputs = []
    for i in range(int(n)):
        with st.container(border=True):
            st.subheader(f"세션 {i+1}")

            subject = st.text_input("과목", value="공부", key=f"sub_{i}")
            c1, c2, c3 = st.columns([1, 1, 1])
            start = c1.text_input("시작(HH:MM)", value="10:00", key=f"st_{i}")
            end = c2.text_input("종료(HH:MM)", value="11:00", key=f"en_{i}")

            # 자동 duration 표시
            dur_txt = "-"
            dur_val = None
            try:
                dur_val = minutes_between(start, end)
                dur_txt = f"{dur_val} 분"
            except Exception:
                dur_txt = "시간 형식 오류"

            c3.markdown(f"**총 시간**  \n{dur_txt}")

            pause = st.number_input("중단 횟수", min_value=0, max_value=999, value=0, step=1, key=f"pa_{i}")
            focused = st.number_input("실제 집중 시간(분)", min_value=0, max_value=5000, value=0, step=5, key=f"fo_{i}")

            inputs.append((subject, start, end, pause, focused, dur_val))

    if st.button("✅ 세션 저장", use_container_width=True):
        saved = 0
        errors = []
        for i, (subject, start, end, pause, focused, dur_val) in enumerate(inputs, start=1):
            if dur_val is None:
                errors.append(f"[세션 {i}] 시간 형식 오류 (예: 10:30)")
                continue
            add_session(d, subject, start, end, pause, focused)
            saved += 1

        if saved:
            st.success(f"저장 완료! {saved}개 세션이 기록되었습니다.")
        if errors:
            st.warning("저장 실패 항목:\n" + "\n".join(errors))

    st.divider()
    st.subheader("내 데이터 내보내기/불러오기 (선택)")
    # 공개 사이트에서 서버 저장을 쓰지 않으므로, 사용자에게 JSON 백업 제공(권장)
    store_json = json.dumps(st.session_state.store, ensure_ascii=False, indent=2)
    st.download_button("⬇️ JSON 다운로드", data=store_json.encode("utf-8"), file_name="study_sessions.json")

    up = st.file_uploader("⬆️ JSON 업로드(복구)", type=["json"])
    if up is not None:
        try:
            obj = json.loads(up.read().decode("utf-8"))
            if isinstance(obj, dict) and "days" in obj:
                st.session_state.store = {"days": obj["days"]}
                st.success("업로드 성공! 데이터가 복구되었습니다.")
            else:
                st.error("형식이 올바르지 않습니다. (days 키 필요)")
        except Exception:
            st.error("JSON 파싱 실패")

# -----------------------------
# Main: 데이터/기간 선택
# -----------------------------
rows = store_to_flat_rows(st.session_state.store)
df = pd.DataFrame(rows)

if df.empty:
    st.info("아직 저장된 세션이 없습니다. 왼쪽에서 세션을 기록해 주세요.")
    st.stop()

df["date_obj"] = pd.to_datetime(df["date"])

min_d = df["date_obj"].min().date()
max_d = df["date_obj"].max().date()

st.subheader("📅 기간 설정")
c1, c2 = st.columns(2)
start_date = c1.date_input("시작일", value=min_d, min_value=min_d, max_value=max_d)
end_date = c2.date_input("종료일", value=max_d, min_value=min_d, max_value=max_d)

if end_date < start_date:
    st.error("종료일이 시작일보다 빠릅니다.")
    st.stop()

mask = (df["date_obj"].dt.date >= start_date) & (df["date_obj"].dt.date <= end_date)
fdf = df.loc[mask].copy()

kpi = compute_kpis(fdf)

# -----------------------------
# KPI Cards
# -----------------------------
st.subheader("📌 KPI (선택 기간 기준)")
k1, k2, k3, k4 = st.columns(4)
if kpi is None:
    k1.metric("전체 평균 집중도", "-")
    k2.metric("누적 학습시간", "-")
    k3.metric("전체 집중 비율", "-")
    k4.metric("시간당 중단 빈도", "-")
else:
    k1.metric("전체 평균 집중도", f"{kpi['avg_focus']:.2f} / 5")
    k2.metric("누적 학습시간", f"{kpi['total']} 분")
    k3.metric("전체 집중 비율", f"{kpi['ratio']*100:.1f} %")
    k4.metric("시간당 중단 빈도", f"{kpi['pause_rate']:.2f} 회/시간")

# -----------------------------
# Session Summary + Expander(기준표)
# -----------------------------
with st.container(border=True):
    st.markdown("### 🧾 세션 요약")
    if kpi is None:
        st.write("선택한 기간에 세션이 없습니다.")
    else:
        st.write(f"- 세션 수: **{kpi['sessions']}개**")
        st.write(f"- 누적 총시간: **{kpi['total']}분** · 순수공부: **{kpi['focused']}분** · 중단 합계: **{kpi['pause']}회**")

    st.caption("정의: duration = 총 학습 시도 시간(분), focused = 순수 집중 시간(분), pause = 중단 횟수")

    st.markdown("**KPI 산식**")
    st.code(
        "① 누적 학습시간 = Σ(duration)\n"
        "② 전체 집중 비율 = Σ(focused) / Σ(duration)\n"
        "③ 전체 평균 집중도 = (전체 집중 비율 × 5)\n"
        "④ 시간당 중단 빈도 = Σ(pause) / (Σ(duration) / 60)",
        language="text"
    )

    with st.expander("📌 집중도 산출 기준 자세히 보기"):
        st.markdown("#### ⏱ 시간당 중단 횟수 기준표 (감점 규칙)")
        st.caption("중단은 ‘총 횟수’가 아니라 ‘시간당 빈도’로 정규화하여 장시간 학습자에게 불리하지 않도록 설계합니다.")
        st.table(pd.DataFrame([
            {"시간당 중단(회/시간)": "≤ 1.0", "해석": "집중 흐름 안정", "감점": "0"},
            {"시간당 중단(회/시간)": "≤ 2.0", "해석": "경미한 방해", "감점": "-1"},
            {"시간당 중단(회/시간)": "≤ 3.0", "해석": "집중 붕괴 잦음", "감점": "-2"},
            {"시간당 중단(회/시간)": "> 3.0", "해석": "집중 유지 실패", "감점": "-3"},
        ]))

        st.markdown("#### 🎯 집중 비율 제한 기준표 (점수 상한 규칙)")
        st.caption("실제 집중 시간이 부족한데 점수가 과대평가되는 것을 방지하기 위한 규칙입니다.")
        st.table(pd.DataFrame([
            {"전체 집중 비율": "< 25%", "해석": "대부분 비집중", "집중도 상한": "최대 1점"},
            {"전체 집중 비율": "< 50%", "해석": "집중 유지 어려움", "집중도 상한": "최대 2점"},
            {"전체 집중 비율": "< 70%", "해석": "부분 집중", "집중도 상한": "최대 3점"},
            {"전체 집중 비율": "≥ 70%", "해석": "안정적 집중", "집중도 상한": "상한 없음"},
        ]))

# -----------------------------
# Weekday chart
# -----------------------------
st.subheader("📈 요일별 순수공부시간(분)")

if fdf.empty:
    st.info("선택한 기간에 데이터가 없습니다.")
else:
    # 요일별 focused 합
    fdf["focused_clamped"] = fdf.apply(lambda r: clamp(int(r["focused_min"]), 0, int(r["duration_min"])), axis=1)
    by_w = fdf.groupby("weekday")["focused_clamped"].sum().reindex(WEEK_ORDER, fill_value=0).reset_index()
    by_w.columns = ["weekday", "focused_min_sum"]

    fig = px.bar(by_w, x="weekday", y="focused_min_sum", text="focused_min_sum")
    fig.update_traces(textposition="outside")
    fig.update_layout(
        yaxis_title="Focused Minutes",
        xaxis_title="Weekday",
        height=420,
        margin=dict(l=30, r=20, t=20, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Session list + delete buttons
# -----------------------------
st.subheader("🗂️ 세션 목록 (선택 기간)")
st.caption("잘못 입력한 세션은 여기서 삭제할 수 있습니다. (삭제는 즉시 반영됩니다)")

if fdf.empty:
    st.write("표시할 세션이 없습니다.")
else:
    # 보기 좋게 정렬
    fdf = fdf.sort_values(["date", "start"]).reset_index(drop=True)

    for idx, row in fdf.iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([0.85, 0.15])
            c1.markdown(
                f"**{row['date']} ({row['weekday']})** · {row['subject']} · "
                f"{row['start']}~{row['end']}  \n"
                f"- duration: {row['duration_min']}분 · focused: {row['focused_min']}분 · pause: {row['pause_count']}회"
            )
            if c2.button("삭제", key=f"del_{row['id']}"):
                delete_session(row["id"])
                st.success("삭제 완료")
                st.rerun()
