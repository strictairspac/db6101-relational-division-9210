from sqlalchemy import text


def _load_staging(db, payload):
    db.execute(text("""
        CREATE TEMP TABLE shift_vehicle (
            asset VARCHAR(64) PRIMARY KEY, category VARCHAR(64) NOT NULL
        ) ON COMMIT DROP
    """))
    db.execute(text("""
        CREATE TEMP TABLE shift_requirement (
            category VARCHAR(64), check_code VARCHAR(64),
            PRIMARY KEY (category, check_code)
        ) ON COMMIT DROP
    """))
    db.execute(text("""
        CREATE TEMP TABLE shift_evidence (
            seq INTEGER PRIMARY KEY, asset VARCHAR(64) NOT NULL REFERENCES shift_vehicle,
            check_code VARCHAR(64) NOT NULL, checked INTEGER NOT NULL,
            expires INTEGER NOT NULL, status VARCHAR(8) NOT NULL
        ) ON COMMIT DROP
    """))
    db.execute(text("INSERT INTO shift_vehicle VALUES (:asset, :category)"), payload["vehicles"])
    if payload["requirements"]:
        db.execute(
            text("INSERT INTO shift_requirement VALUES (:category, :check)"),
            payload["requirements"],
        )
    if payload["evidence"]:
        db.execute(
            text("INSERT INTO shift_evidence VALUES (:seq, :asset, :check, :checked, :expires, :status)"),
            payload["evidence"],
        )


def release_decisions(db, payload, minute):
    _load_staging(db, payload)
    rows = db.execute(text("""
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY asset, check_code ORDER BY checked DESC, seq DESC
            ) AS freshness
            FROM shift_evidence
            WHERE checked <= :minute
        ),
        valid AS (
            SELECT asset, check_code FROM ranked
            WHERE freshness = 1 AND status = 'pass' AND expires > :minute
        ),
        missing AS (
            SELECT v.asset, r.check_code, CASE
                WHEN e.asset IS NULL THEN '无当时回执'
                WHEN e.status = 'fail' THEN '末次检测未通过'
                ELSE '证据已失效'
            END AS reason
            FROM shift_vehicle v
            JOIN shift_requirement r ON r.category = v.category
            LEFT JOIN ranked e ON e.asset = v.asset AND e.check_code = r.check_code AND e.freshness = 1
            WHERE NOT EXISTS (
                SELECT 1 FROM valid ok WHERE ok.asset = v.asset AND ok.check_code = r.check_code
            )
        )
        SELECT v.asset, v.category,
               EXISTS (SELECT 1 FROM shift_requirement r WHERE r.category = v.category)
               AND NOT EXISTS (SELECT 1 FROM missing m WHERE m.asset = v.asset) AS released,
               (SELECT STRING_AGG(m.check_code, ' / ' ORDER BY m.check_code)
                FROM missing m WHERE m.asset = v.asset) AS missing_checks,
               (SELECT STRING_AGG(m.check_code || '（' || m.reason || '）', ' / ' ORDER BY m.check_code)
                FROM missing m WHERE m.asset = v.asset) AS diagnostic
        FROM shift_vehicle v
        ORDER BY v.asset
    """), {"minute": minute}).mappings().all()
    db.execute(text("DROP TABLE shift_evidence, shift_requirement, shift_vehicle"))
    return rows
