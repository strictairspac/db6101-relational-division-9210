from .inputs import validate
from .release_sql import release_decisions

CONFIG = {
    "title": "雁坪地服·行李牵引车放行",
    "team": "雁坪机场地服车辆组（12 人）",
    "description": "在行李车交接前，核对车型的全部必检项目，阻断过期、撤销及缺项车辆。",
    "direction": "SQL 编写 / 关系除法",
    "mechanism": "PostgreSQL 嵌套 NOT EXISTS 对全套必检证据做关系除法。",
    "modules": ["交接班台", "车型与检证", "放行筛查", "缺项交接单"],
    "unit": "交接班批次",
    "max_parameter": 1439,
    "parameter_label": "复核时点（当日分钟）",
    "default_parameter": 480,
    "facts": ["受检数", "可放行", "禁止放行"],
    "palette": 1,
    "fixture": "YP-1124-早班",
}

REGULAR = {
    "vehicles": [
        {"asset": "YP-T12", "category": "电动"},
        {"asset": "YP-T13", "category": "电动"},
        {"asset": "YP-D22", "category": "柴油"},
        {"asset": "YP-U01", "category": "未定型"},
    ],
    "requirements": [
        {"category": "电动", "check": "制动"},
        {"category": "电动", "check": "牵引销"},
        {"category": "柴油", "check": "制动"},
    ],
    "evidence": [
        {"seq": 1, "asset": "YP-T12", "check": "制动", "checked": 450, "expires": 570, "status": "pass"},
        {"seq": 2, "asset": "YP-T12", "check": "牵引销", "checked": 460, "expires": 550, "status": "pass"},
        {"seq": 3, "asset": "YP-T13", "check": "制动", "checked": 450, "expires": 550, "status": "pass"},
        {"seq": 4, "asset": "YP-T13", "check": "制动", "checked": 450, "expires": 550, "status": "fail"},
        {"seq": 5, "asset": "YP-T13", "check": "牵引销", "checked": 481, "expires": 570, "status": "pass"},
        {"seq": 6, "asset": "YP-D22", "check": "制动", "checked": 410, "expires": 480, "status": "pass"},
    ],
}

FIXTURES = [
    {"code": "YP-1124-AM", "title": "YP-1124-早班", "description": "08:00，核对 4 辆车。", "payload": REGULAR},
    {
        "code": "YP-1124-SV", "title": "调车备班·未补制动", "description": "试车只有牵引销证据。",
        "payload": {
            "vehicles": [{"asset": "YP-T99", "category": "电动"}],
            "requirements": REGULAR["requirements"][:2],
            "evidence": [
                {"seq": 1, "asset": "YP-T99", "check": "牵引销", "checked": 450, "expires": 620, "status": "pass"},
            ],
        },
    },
]


def run(payload, parameter, db):
    validate(payload)
    if type(parameter) is not int or not 1 <= parameter <= 1439:
        raise ValueError("复核时点须在当日 1–1439 分钟")
    rows = [
        {
            "车辆": decision["asset"],
            "车型": decision["category"],
            "放行决定": "放行" if decision["released"] else "停放",
            "交接备注": decision["missing_checks"] or (
                "车型未配置必检项目" if not decision["released"] else "全部项目有效"
            ),
            "证据诊断": decision["diagnostic"],
        }
        for decision in release_decisions(db, payload, parameter)
    ]
    released = sum(row["放行决定"] == "放行" for row in rows)
    return {
        "summary": f"{parameter // 60:02d}:{parameter % 60:02d} 复核 {len(rows)} 辆，{released} 辆可放行。",
        "metrics": {"受检数": len(rows), "可放行": released, "禁止放行": len(rows) - released},
        "rows": rows,
    }
