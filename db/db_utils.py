import psycopg2
import json
from db.db_config import DB_CONFIG
from datetime import datetime

def _to_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    try:
        return bool(int(v))
    except Exception:
        return str(v).strip().lower() in ("true", "t", "yes", "y")

def _parse_ts(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    # epoch?
    try:
        if s.isdigit() or s.replace('.', '', 1).isdigit():
            return datetime.fromtimestamp(float(s))
    except Exception:
        pass
    # ISO
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def save_to_db(source: str, score: float, label: int, raw_json: dict):
    sql = """
    INSERT INTO anomaly_scores (
        stime, source, score, label,
        proto, state,
        sload, dload, spkts, dpkts,
        sjit, djit,
        sttl, dttl,
        dur, tcprtt, synack, ackdat,
        ct_state_ttl, service,
        raw_data
    ) VALUES (
        COALESCE(%s, NOW()), %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s,
        %s, %s, %s, %s,
        %s, %s,
        %s, %s,
        %s, %s, %s
    )
    """

    params = (
        _parse_ts(raw_json.get("stime") or raw_json.get("Stime")),
        source,
        float(score) if score is not None else None,
        int(label) if label is not None else None,

        raw_json.get("proto"),
        raw_json.get("state"),

        raw_json.get("sload"),
        raw_json.get("dload"),
        raw_json.get("spkts"),
        raw_json.get("dpkts"),
        raw_json.get("sjit"),
        raw_json.get("djit"),
        raw_json.get("sttl"),
        raw_json.get("dttl"),
        raw_json.get("dur"),
        raw_json.get("tcprtt"),
        raw_json.get("synack"),
        raw_json.get("ackdat"),
        raw_json.get("ct_state_ttl"),
        raw_json.get("service"),


        json.dumps(raw_json, ensure_ascii=False)
    )

    conn = cur = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        print(f"Error saving to database: {e}")
        # 디버깅 도움: 자리수/파라미터 개수 확인
        print(f"[debug] placeholders=26, params={len(params)}")
    finally:
        if cur: cur.close()
        if conn: conn.close()
