# dashboard/app.py
import os, sys
from datetime import timedelta
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.pool import SimpleConnectionPool
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import matplotlib
import matplotlib.pyplot as plt
from river.drift import ADWIN

# ===== Repo root import =====
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from db.db_config import DB_CONFIG  

# ===== Page config =====
st.set_page_config(page_title='Network Anomaly Detection Dashboard', layout='wide')
st.title('Real-Time Network Anomaly Detection Dashboard')

# ===== Resources (connection pool) =====
@st.cache_resource
def get_pool():
    # 보수적으로 minconn=1, maxconn=8 (부하에 맞게 조정)
    return SimpleConnectionPool(minconn=1, maxconn=8, **DB_CONFIG)

# ===== Helpers =====
def to_utc_ts(x):
    """x를 UTC tz-aware pandas Timestamp로 통일"""
    t = pd.Timestamp(x)
    if t.tzinfo is None:
        return t.tz_localize('UTC')
    return t.tz_convert('UTC')

def ensure_cols(df: pd.DataFrame, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df

def ema(series: pd.Series, alpha: float):
    if series is None or len(series) == 0:
        return series
    return series.ewm(alpha=alpha, adjust=False).mean()

def human_bps(x):
    # bps 단위 자동 변환
    if x is None or np.isnan(x):
        return "n/a"
    units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"]
    i = 0
    while abs(x) >= 1000 and i < len(units)-1:
        x /= 1000.0
        i += 1
    return f"{x:.2f} {units[i]}"

def dual_axis_lines(df, x, y_left, y_right, title_left, title_right, anom_mask=None, smooth_alpha=None):
    yl = df[y_left].copy()
    yr = df[y_right].copy()
    if smooth_alpha and 0 < smooth_alpha < 1:
        yl = ema(yl, smooth_alpha)
        yr = ema(yr, smooth_alpha)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scattergl(x=df[x], y=yl, name=y_left, mode='lines'), secondary_y=False)
    fig.add_trace(go.Scattergl(x=df[x], y=yr, name=y_right, mode='lines'), secondary_y=True)
    if anom_mask is not None and anom_mask.any():
        dfa = df.loc[anom_mask]
        fig.add_trace(
            go.Scattergl(x=dfa[x], y=dfa[y_left], mode='markers', name='Anomaly',
                         marker=dict(size=8, symbol='x', color='red', line=dict(width=1))),
            secondary_y=False
        )
    fig.update_yaxes(title_text=title_left, secondary_y=False)
    fig.update_yaxes(title_text=title_right, secondary_y=True)
    fig.update_xaxes(title_text="Time (UTC)")
    fig.update_layout(margin=dict(l=40, r=20, t=30, b=30), height=320, legend_title_text="")
    return fig

def contiguous_blocks(mask_bool: pd.Series, time_col: pd.Series):
    blocks = []
    run = None
    for i in range(len(mask_bool)):
        if mask_bool.iloc[i] and run is None:
            run = i
        if run is not None and (i == len(mask_bool)-1 or not mask_bool.iloc[i+1]):
            s = time_col.iloc[run]; e = time_col.iloc[i]
            blocks.append((s, e)); run = None
    return blocks

def l1_divergence(p: pd.Series, q: pd.Series):
    idx = p.index.union(q.index)
    p = p.reindex(idx, fill_value=0.0)
    q = q.reindex(idx, fill_value=0.0)
    return (p - q).abs().sum()

def kl_divergence(p: pd.Series, q: pd.Series, eps=1e-12):
    idx = p.index.union(q.index)
    p = p.reindex(idx, fill_value=0.0).astype(float) + eps
    q = q.reindex(idx, fill_value=0.0).astype(float) + eps
    p /= p.sum(); q /= q.sum()
    return float((p * np.log(p / q)).sum())

def js_divergence(p: pd.Series, q: pd.Series, eps=1e-12):
    """ Jensen–Shannon divergence (대칭/유한) """
    idx = p.index.union(q.index)
    p = p.reindex(idx, fill_value=0.0).astype(float) + eps
    q = q.reindex(idx, fill_value=0.0).astype(float) + eps
    p = p / p.sum(); q = q / q.sum()
    m = 0.5 * (p + q)
    kl_pm = (p * np.log(p / m)).sum()
    kl_qm = (q * np.log(q / m)).sum()
    return float(0.5 * (kl_pm + kl_qm))

def cat_dist(series: pd.Series, smoothing=1.0):
    """ 카테고리 시리즈 → 라플라스 스무딩된 확률분포(Series) """
    vc = series.fillna("NA").value_counts()
    counts = vc.astype(float) + smoothing
    probs = counts / counts.sum()
    probs.index = vc.index  # index 보존
    return probs

# ===== Data layer =====
@st.cache_data(ttl=4, show_spinner=False)
def load_data(start_dt_utc, proto_filter, service_filter, state_filter, limit_rows=None) -> pd.DataFrame:
    where_clauses = ["stime >= %s"]
    params = [start_dt_utc]
    if proto_filter:
        where_clauses.append("proto = ANY(%s)")
        params.append(proto_filter)
    if service_filter:
        where_clauses.append("service = ANY(%s)")
        params.append(service_filter)
    if state_filter:
        where_clauses.append("state = ANY(%s)")
        params.append(state_filter)

    where_sql = " AND ".join(where_clauses)
    limit_sql = f"LIMIT {int(limit_rows)}" if limit_rows else ""

    q = f"""
        SELECT 
            stime, source, score, label, proto, state, service,
            sload, dload, spkts, dpkts, sjit, djit, sttl, dttl, dur,
            tcprtt, synack, ackdat, ct_state_ttl
        FROM public.anomaly_scores
        WHERE {where_sql}
        ORDER BY stime
        {limit_sql}
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        df = pd.read_sql(q, conn, params=params)
    finally:
        pool.putconn(conn)

    if df.empty:
        return df

    # types
    df['stime'] = pd.to_datetime(df['stime'], utc=True)
    for c in ['score','label','sload','dload','spkts','dpkts','sjit','djit',
              'sttl','dttl','dur','tcprtt','synack','ackdat','ct_state_ttl']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

# ===== Controls =====
with st.sidebar:
    st.markdown("### Window & Refresh")
    minutes = st.slider("Recent minutes", 1, 240, 15, step=1)
    enable_autorefresh = st.checkbox("Auto refresh", value=True)
    refresh_ms = st.slider("Interval (ms)", min_value=1000, max_value=15000, value=4000, step=500)

    st.markdown("---")
    st.markdown("### Thresholds")
    score_threshold = st.number_input("Anomaly score threshold", 0.0, 1.0, 0.5, 0.01, format="%.2f")

    st.markdown("### Burst (window-based)")
    burst_win_min = st.number_input("Burst window (minutes)", min_value=1, max_value=120, value=5, step=1)
    burst_min_hits = st.number_input("Min anomalies in window", min_value=1, max_value=100000, value=5, step=1)

    st.markdown("---")

    st.markdown("### Drift detectors")
    enable_adwin = st.checkbox("Enable ADWIN on score", value=True)
    adwin_delta = st.slider("ADWIN delta (smaller = sensitive)", min_value=1e-4, max_value=1e-1, value=2e-3, step=1e-3, format="%.4f")
    regime_high = st.slider("High-score regime mean >", min_value=0.0, max_value=1.0, value=0.5, step=0.05)

    ref_minutes = st.slider("Ref window for proto/state (min)", min_value=10, max_value=720, value=60, step=5)
    drift_warn_js = st.slider("Warn if JS >", min_value=0.0, max_value=0.5, value=0.10, step=0.01)
    drift_warn_l1 = st.slider("Warn if L1 >", min_value=0.0, max_value=2.0, value=0.30, step=0.05)
    
    st.markdown("---")
    
    st.markdown("### Filters")
    def to_list(x): return [t.strip() for t in x.split(",") if t.strip()] if x else []
    proto_filter   = to_list(st.text_input("proto (comma-separated)", value="").strip()) or None
    service_filter = to_list(st.text_input("service (comma-separated)", value="").strip()) or None
    state_filter   = to_list(st.text_input("state (comma-separated)", value="").strip()) or None

    st.markdown("---")
    st.markdown("### Performance guardrails")
    limit_rows = st.number_input("Row cap (0 = unlimited)", min_value=0, max_value=1_000_000, value=100_000, step=10_000)
    limit_rows = None if limit_rows == 0 else limit_rows
    smooth_alpha = st.slider("EMA smoothing (0=off)", min_value=0.0, max_value=0.9, value=0.0, step=0.1)

    st.markdown("---")
    st.markdown("### Viz options")
    show_human_units = st.checkbox("Show human-readable bps in KPI labels", value=True)
    topk_state = st.slider("Top-K states", min_value=1, max_value=3, value=3, step=1)

 
# ===== Load data =====
now_utc = pd.Timestamp.now(tz='UTC')
start_time_utc = now_utc - pd.Timedelta(minutes=minutes)
df = load_data(start_time_utc, proto_filter, service_filter, state_filter, limit_rows)

if df.empty:
    st.info("No data available for the selected window/filters.")
    if enable_autorefresh:
        st_autorefresh(interval=refresh_ms, key="auto-refresh-empty")
    st.stop()

df_recent = df.copy()
df_recent.sort_values('stime', inplace=True)

# ===== KPIs (Ops) =====
total = len(df_recent)
anom_hits = int(df_recent['label'].fillna(0).astype(int).sum())
rate = (anom_hits / total * 100) if total > 0 else 0.0
last_ts = df_recent['stime'].max()
first_ts = df_recent['stime'].min()
elapsed_sec = max((last_ts - first_ts).total_seconds(), 1.0)
eps = total / elapsed_sec

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Records (window)", f"{total:,}")
k2.metric("Anomalies", f"{anom_hits:,}")
k3.metric("Anomaly Rate", f"{rate:.2f}%")
k4.metric("Events/sec", f"{eps:.2f}")
k5.metric("Last event (UTC)", f"{last_ts.strftime('%H:%M:%S')}")

st.markdown("---")

# ===== Score timeline =====
st.subheader("Anomaly Scores Over Time")

# 필수 컬럼 체크
if 'stime' not in df_recent.columns or 'score' not in df_recent.columns:
    st.warning("Missing 'stime' or 'score' in dataframe.")
    st.stop()

# 시계열 준비
df_s = (
    df_recent[['stime', 'score']]
    .copy()
    .sort_values('stime')
)
# stime은 load_data에서 UTC tz-aware로 변환됨. 혹시 모를 누락 대비
df_s['stime'] = pd.to_datetime(df_s['stime'], utc=True, errors='coerce')
df_s.dropna(subset=['stime'], inplace=True)

# score 정리: 숫자화 + NaN→0 + [0,1] 클리핑
df_s['score'] = pd.to_numeric(df_s['score'], errors='coerce').fillna(0.0)
df_s['score'] = df_s['score'].clip(0.0, 1.0)

if df_s.empty:
    st.info("No score data to plot in the selected window.")
    st.stop()

# 옵션 스무딩
if smooth_alpha and (0.0 < smooth_alpha < 1.0):
    df_s['score_smooth'] = ema(df_s['score'], smooth_alpha)
    y_col = 'score_smooth'
else:
    y_col = 'score'

# 임계 초과 마커
mask_anom = df_s[y_col] > float(score_threshold)

# === ADWIN 초기화 / 유지 ===
if 'adwin' not in st.session_state or st.session_state.get('adwin_delta') != adwin_delta:
    st.session_state.adwin = ADWIN(delta=float(adwin_delta))
    st.session_state.adwin_delta = float(adwin_delta)
    st.session_state.adwin_events = []  # (UTC tz-aware timestamp, estimation)

adwin = st.session_state.adwin
adwin_events = st.session_state.adwin_events

# 현재 창 경계 (UTC tz-aware)
win_start = df_s['stime'].min().tz_convert('UTC')
win_end   = df_s['stime'].max().tz_convert('UTC')

# 창 이전 이벤트만 유지하고, 창 데이터로 재학습
adwin_events = [(to_utc_ts(t), est) for (t, est) in adwin_events if to_utc_ts(t) < win_start]
st.session_state.adwin = ADWIN(delta=float(adwin_delta))
adwin = st.session_state.adwin

for ts, sc in zip(df_s['stime'].values, df_s[y_col].fillna(0.0).astype(float).values):
    adwin.update(float(sc))
    if adwin.drift_detected:
        adwin_events.append((to_utc_ts(ts), float(adwin.estimation)))

# 세션 갱신
st.session_state.adwin_events = adwin_events

# === Plotly ===
fig = go.Figure()

# 시계열 라인
fig.add_trace(go.Scatter(
    x=df_s['stime'], y=df_s[y_col],
    mode='lines', name=y_col,
    hovertemplate='%{x|%Y-%m-%d %H:%M:%S UTC}<br>score=%{y:.3f}<extra></extra>'
))

# 임계선
fig.add_hline(
    y=float(score_threshold),
    line_dash="dash",
    line_color="crimson",
    line_width=2.5,
    opacity=0.9,
    annotation_text=f"threshold={float(score_threshold):.2f}",
    annotation_position="top left"
)

# 히트 마커
if mask_anom.any():
    fig.add_trace(go.Scatter(
        x=df_s.loc[mask_anom, 'stime'],
        y=df_s.loc[mask_anom, y_col],
        mode='markers', name='Anomaly hits',
        marker=dict(size=8, symbol='x', color='red', line=dict(width=1, color='darkred'))
    ))

# ADWIN 경계선 (최근 N개)
if enable_adwin and adwin_events:
    for t, est in adwin_events[-8:]:
        fig.add_vline(x=t, line_dash="dot", line_width=1)

fig.update_layout(
    xaxis_title="Time (UTC)",
    yaxis_title="Anomaly Score",
    yaxis=dict(range=[0, 1]),
    height=380, legend_title_text="",
    margin=dict(l=40, r=20, t=40, b=40),
    xaxis_rangeslider_visible=False
)

st.plotly_chart(fig, use_container_width=True)

# === ADWIN 상태/알림 ===
if enable_adwin:
    cur_mean = float(getattr(adwin, 'estimation', np.nan))
    regime = "anomaly" if cur_mean > float(regime_high) else "normal"
    st.caption(f"ADWIN mean≈{cur_mean:.3f} → regime: **{regime}** (cutoff {float(regime_high):.2f})")

    # 최근 1분 내 드리프트 감지 경고
    if adwin_events:
        last_event_ts = to_utc_ts(adwin_events[-1][0])
        if (win_end - last_event_ts) <= pd.Timedelta(minutes=1):
            st.warning(
                f"ADWIN drift at {last_event_ts.strftime('%H:%M:%S')} "
                f"(mean≈{adwin_events[-1][1]:.3f})"
            )

# ===== Input drift metrics (proto/state) =====
st.markdown("---")
st.subheader("Input drift — proto/state vs reference window")

WINDOW_SEC = 180  # 최근창 길이(초) — 아래 분포/차트 섹션과 동일하게 사용
now2 = pd.to_datetime(df_recent['stime'].max())
df_now = df_recent[df_recent['stime'] >= now2 - pd.Timedelta(seconds=WINDOW_SEC)].copy()

# 참조창: 최근창 직전 구간
ref_end = now2 - pd.Timedelta(seconds=WINDOW_SEC)
ref_start = ref_end - pd.Timedelta(minutes=ref_minutes)
df_ref = df_recent[(df_recent['stime'] >= ref_start) & (df_recent['stime'] < ref_end)].copy()

if df_now.empty:
    st.info(f"No events in the last {WINDOW_SEC}s.")
else:
    if df_ref.empty:
        st.info(f"Reference window empty ({ref_minutes} min before recent window).")
    else:
        # 분포 추정 (라플라스 스무딩)
        p_ref_proto = cat_dist(df_ref['proto'])
        p_now_proto = cat_dist(df_now['proto'])
        p_ref_state = cat_dist(df_ref['state'])
        p_now_state = cat_dist(df_now['state'])

        # JS / L1 계산
        js_proto = js_divergence(p_now_proto, p_ref_proto)
        l1_proto = l1_divergence(p_now_proto, p_ref_proto)
        js_state = js_divergence(p_now_state, p_ref_state)
        l1_state = l1_divergence(p_now_state, p_ref_state)

        cA, cB, cC, cD = st.columns(4)
        cA.metric("JS(proto)", f"{js_proto:.3f}")
        cB.metric("L1(proto)", f"{l1_proto:.3f}")
        cC.metric("JS(state)", f"{js_state:.3f}")
        cD.metric("L1(state)", f"{l1_state:.3f}")

        proto_alert = (js_proto > float(drift_warn_js)) or (l1_proto > float(drift_warn_l1))
        state_alert = (js_state > float(drift_warn_js)) or (l1_state > float(drift_warn_l1))

        if proto_alert and state_alert:
            st.error("Proto & State drift detected (JS/L1 over thresholds).")
        elif proto_alert or state_alert:
            st.warning("Drift signal detected in one of proto/state.")
        else:
            st.success("No proto/state drift against reference window.")

# ===== Label distribution =====
st.markdown("---")
st.subheader(f"Normal vs Anomaly ({minutes}-minute window)")
label_mapping = {0: "Normal", 1: "Anomaly"}
lab = df_recent['label'].fillna(0).astype(int).map(label_mapping)
order = pd.Index(["Normal","Anomaly"])
label_counts = lab.value_counts().reindex(order, fill_value=0).reset_index()
label_counts.columns = ['Label', 'Count']
fig_pie = px.pie(label_counts, names='Label', values='Count',
                 color='Label',
                 category_orders={'Label': ["Normal", "Anomaly"]},
                 color_discrete_map={"Normal": "skyblue", "Anomaly": "salmon"},
                 hole=0.3)
fig_pie.update_layout(height=420, margin=dict(l=10,r=10,t=30,b=10))
st.plotly_chart(fig_pie, use_container_width=True)

st.markdown("---")

# ===== RAW KPIs (최근 N초 뷰) =====
st.subheader("Network KPIs — RAW (recent window)")
window_sec = 300  # 5분
now = pd.to_datetime(df_recent['stime'].max())
t0 = now - pd.Timedelta(seconds=window_sec)
df_live = (df_recent[df_recent['stime'] >= t0].copy().sort_values('stime'))
df_live['has_anom'] = (df_live.get('label', 0) > 0)

# sload/dload label (human units) for subtitle
if show_human_units and not df_live.empty:
    last_sload = human_bps(df_live['sload'].iloc[-1]) if 'sload' in df_live else "n/a"
    last_dload = human_bps(df_live['dload'].iloc[-1]) if 'dload' in df_live else "n/a"
    st.caption(f"Last s/d load: {last_sload} / {last_dload}")

c1, c2 = st.columns(2)
with c1:
    st.markdown("Traffic (Sload / Dload) — RAW (dual axis)")
    ensure_cols(df_live, ['sload','dload'])
    fig_sd = dual_axis_lines(df_live, 'stime', 'sload', 'dload',
                             "sload (bps)", "dload (bps)",
                             anom_mask=df_live['has_anom'], smooth_alpha=smooth_alpha)
    st.plotly_chart(fig_sd, use_container_width=True)

with c2:
    st.markdown("Packets (Spkts / Dpkts) — RAW")
    ensure_cols(df_live, ['spkts', 'dpkts'])
    ycols = ['spkts','dpkts']
    plot_df = df_live.copy()
    if smooth_alpha and smooth_alpha > 0:
        for c in ycols:
            if c in plot_df: plot_df[c] = ema(plot_df[c], smooth_alpha)
    fig_pk = px.line(plot_df, x='stime', y=ycols,
                     labels={'value': f'packets/{window_sec}s', 'stime': 'Time (UTC)'},
                     render_mode='webgl')
    dfa = df_live[df_live['has_anom']]
    fig_pk.add_trace(go.Scattergl(
        x=dfa['stime'], y=dfa['spkts'],
        mode='markers', name='Anomaly',
        marker=dict(size=8, symbol='x', color='red', line=dict(width=1))
    ))
    fig_pk.update_layout(margin=dict(l=40, r=20, t=30, b=30), height=320, legend_title_text="")
    st.plotly_chart(fig_pk, use_container_width=True)

c3, c4 = st.columns(2)
with c3:
    st.markdown("Jitter (Sjit / Djit) — RAW (dual axis)")
    ensure_cols(df_live, ['sjit','djit'])
    fig_jit = dual_axis_lines(df_live, 'stime', 'sjit', 'djit',
                              "sjit (ms)", "djit (ms)",
                              anom_mask=df_live['has_anom'], smooth_alpha=smooth_alpha)
    st.plotly_chart(fig_jit, use_container_width=True)

with c4:
    st.markdown("TCP Handshake (tcprtt / synack / ackdat) — RAW")
    ensure_cols(df_live, ['tcprtt','synack','ackdat'])
    ycols = ['tcprtt','synack','ackdat']
    plot_df = df_live.copy()
    if smooth_alpha and smooth_alpha > 0:
        for c in ycols:
            if c in plot_df: plot_df[c] = ema(plot_df[c], smooth_alpha)
    fig_tcp = px.line(plot_df, x='stime', y=ycols,
                      labels={'value': 'ms', 'stime': 'Time (UTC)'},
                      render_mode='webgl')
    dfa = df_live[df_live['has_anom']]
    fig_tcp.add_trace(go.Scattergl(
        x=dfa['stime'], y=dfa['tcprtt'],
        mode='markers', name='Anomaly',
        marker=dict(size=8, symbol='x', color='red', line=dict(width=1))
    ))
    fig_tcp.update_layout(margin=dict(l=40, r=20, t=30, b=30), height=320, legend_title_text="")
    st.plotly_chart(fig_tcp, use_container_width=True)

st.markdown("---")

# ===== Protocol / State distributions (recent window + drift) =====
st.subheader("Protocol / State Distributions — recent window")

# WINDOW_SEC / df_now는 위의 Input drift 섹션과 동일 객체 사용
if df_now.empty:
    st.info(f"No events in the last {WINDOW_SEC}s.")
else:
    # 라벨 문자열 보정
    if 'label_str' not in df_now.columns:
        df_now['label_str'] = np.where(df_now.get('label', 0) > 0, 'Anomaly', 'Normal')

    b1, b2 = st.columns(2)

    # 1) Protocol share (percent stacked)
    with b1:
        st.markdown(f"Protocol share — last {WINDOW_SEC}s")
        fig_proto = px.histogram(
            df_now,
            x='proto',
            color='label_str',
            barmode='stack',
            barnorm='percent',         # 비율로 보기
            text_auto='.1f',
            category_orders={'label_str': ['Normal','Anomaly']},
            color_discrete_map={'Normal':'skyblue','Anomaly':'salmon'}
        )
        fig_proto.update_layout(
            xaxis_title='proto',
            yaxis_title='%',
            margin=dict(l=20, r=10, t=10, b=10),
            height=360
        )
        st.plotly_chart(fig_proto, use_container_width=True)

    # 2) State share (Top-K + Other, percent stacked)
    with b2:
        st.markdown(f"State share (Top-{topk_state}) — last {WINDOW_SEC}s")
        # Top-K + Other 처리
        vc = df_now['state'].value_counts()
        keep = set(vc.head(topk_state).index)
        df_now['state_top'] = np.where(df_now['state'].isin(keep), df_now['state'], 'Other')

        fig_state = px.histogram(
            df_now,
            x='state_top',
            color='label_str',
            barmode='stack',
            barnorm='percent',
            text_auto='.1f',
            category_orders={'label_str': ['Normal','Anomaly']},
            color_discrete_map={'Normal':'skyblue','Anomaly':'salmon'}
        )
        fig_state.update_layout(
            xaxis_title='state',
            yaxis_title='%',
            margin=dict(l=20, r=10, t=10, b=10),
            height=360
        )
        st.plotly_chart(fig_state, use_container_width=True)

    st.caption(
        f"Events: {len(df_now):,}  |  Anomaly rate: "
        f"{100*(df_now['label_str']=='Anomaly').mean():.2f}%  |  Window: {WINDOW_SEC}s"
    )

st.markdown("---")

# ===== ct_state_ttl heatmap (grouped) =====
st.subheader("State+TTL pattern (ct_state_ttl heatmap, grouped)")
src = df_recent[['stime', 'ct_state_ttl']].dropna().copy()
if src.empty:
    st.info("ct_state_ttl is empty for current window.")
else:
    resample_rule = "1T"  # 1-minute buckets
    src['bucket'] = src['stime'].dt.floor(resample_rule)
    src['ct_state_ttl'] = pd.to_numeric(src['ct_state_ttl'], errors='coerce').round().astype('Int64')
    src['ct_state_ttl_group'] = src['ct_state_ttl'].apply(lambda x: str(x) if x in [0,1,2] else "3-6")
    order_vals = ["0","1","2","3-6"]
    heat = (src.groupby(['ct_state_ttl_group','bucket']).size().reset_index(name='count'))
    pivot = (heat.pivot(index='ct_state_ttl_group', columns='bucket', values='count')
                  .reindex(order_vals).fillna(0))

    c1, c2, c3 = st.columns([1,1,1])
    with c1: norm = st.selectbox("Normalize", ["none","per-time","per-row"], index=0, key="ttl_norm")
    with c2: colorscale = st.selectbox("Colorscale", ["Viridis","Plasma","Magma","Cividis","Inferno"], index=0, key="ttl_color")
    with c3: pct = st.slider("Z max percentile", min_value=90, max_value=100, value=99, key="ttl_pct")

    z = pivot.copy()
    if norm == "per-time":
        colsum = z.sum(axis=0).replace(0, np.nan)
        z = z.divide(colsum, axis=1).fillna(0.0); zmin, zmax = 0.0, 1.0
    elif norm == "per-row":
        rowsum = z.sum(axis=1).replace(0, np.nan)
        z = z.divide(rowsum, axis=0).fillna(0.0); zmin, zmax = 0.0, 1.0
    else:
        zmin = 0.0; zmax = float(np.nanpercentile(z.values, pct))

    fig_heat = go.Figure(data=go.Heatmap(
        z=z.values, x=z.columns, y=[str(v) for v in z.index],
        coloraxis="coloraxis", zmin=zmin, zmax=zmax,
        hovertemplate=("time=%{x|%Y-%m-%d %H:%M:%S}<br>"
                       "ct_state_ttl_group=%{y}<br>"
                       "value=%{z}<extra></extra>")
    ))
    fig_heat.update_layout(
        coloraxis=dict(colorscale=colorscale),
        xaxis_title="Time (UTC)", yaxis_title="ct_state_ttl",
        yaxis=dict(type="category", categoryorder="array", categoryarray=order_vals),
        height=420, margin=dict(l=60, r=30, t=40, b=50)
    )
    st.plotly_chart(fig_heat, use_container_width=True)

st.markdown("---")

# ===== Recent anomalies / Top-N (download) =====
st.subheader("Recent anomalies (window)")
df_anom = df_recent[df_recent['label'] == 1].sort_values('stime', ascending=False).copy()
if df_anom.empty:
    st.info("No anomalies in window.")
else:
    cols_show = ['stime','score','proto','state','service','sload','dload','spkts','dpkts','dur','tcprtt']
    ensure_cols(df_anom, cols_show)
    
    # 색상 맵 준비 (연노랑 → 진빨강)
    cmap = matplotlib.cm.get_cmap('Reds')  # Reds 컬러맵
    norm = matplotlib.colors.Normalize(vmin=df_anom['score'].min(), vmax=df_anom['score'].max())

    def highlight_score(row):
        color = matplotlib.colors.rgb2hex(cmap(norm(row['score'])))
        return [f'background-color: {color}; color: black;'] * len(row)

    styled = (
        df_anom[cols_show].head(100)
        .style.apply(highlight_score, axis=1)
        .format({'score':'{:.3f}','sload':'{:,.0f}','dload':'{:,.0f}','dur':'{:.3f}','tcprtt':'{:.3f}'})
    )

    st.dataframe(styled, use_container_width=True)

    csv_anom = df_anom[cols_show].to_csv(index=False).encode('utf-8')
    st.download_button("Download anomalies (CSV)", data=csv_anom,
                       file_name="anomalies_window.csv", mime="text/csv",
                       key="download_anoms_window_v2")

st.subheader("Top 10 by score (window)")
df_top = df_recent[df_recent['label'] == 1].sort_values('score', ascending=False).head(10).copy()
cols_top = ['stime','score','proto','state','service','sload','dload','dur']
ensure_cols(df_top, cols_top)

# Top 10도 동일하게 적용
styled_top = (
    df_top[cols_top]
    .style.apply(lambda r: [f'background-color: {matplotlib.colors.rgb2hex(cmap(norm(r["score"])))}; color: black;'] * len(r), axis=1)
    .format({'score':'{:.3f}','sload':'{:,.0f}','dload':'{:,.0f}','dur':'{:.3f}'})
)

st.dataframe(styled_top, use_container_width=True)

csv_top = df_top[cols_top].to_csv(index=False).encode('utf-8')
st.download_button("Download Top 10 anomalies (CSV)", data=csv_top,
                   file_name="anomalies_top10_window.csv", mime="text/csv",
                   key="download_anoms_top10_v2")

# ===== Auto-refresh =====
if enable_autorefresh:
    st_autorefresh(interval=refresh_ms, key="auto-refresh")
