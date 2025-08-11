CREATE TABLE IF NOT EXISTS anomaly_scores (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stime           TIMESTAMPTZ NOT NULL,
    source          VARCHAR(50),
    score           DOUBLE PRECISION,
    label           INT,

    proto           TEXT,
    state           TEXT,

    sload           DOUBLE PRECISION,              
    dload           DOUBLE PRECISION,               
    spkts           INT,                             
    dpkts           INT,                             
    sjit            DOUBLE PRECISION,               
    djit            DOUBLE PRECISION,             
    sttl            INT,                             
    dttl            INT,                           
    dur             DOUBLE PRECISION,             
    tcprtt          DOUBLE PRECISION,              
    synack          DOUBLE PRECISION,              
    ackdat          DOUBLE PRECISION,            
    ct_state_ttl    INT,                            
    service         TEXT,   
                            
    raw_data        JSONB
);

