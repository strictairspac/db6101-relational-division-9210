def _table(payload, key, fields, *, allow_empty=False):
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) > 400 or (not rows and not allow_empty):
        raise ValueError(f"{key} 须为符合行数限制的列表（最多 400 行）")
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(fields):
            raise ValueError(f"{key} 的行需要字段 {', '.join(fields)}")
    return rows


def _key(row, field):
    value = row[field]
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"{field} 须为 1–64 字符的标识")
    return value


def validate(payload):
    vehicles = _table(payload, "vehicles", ("asset", "category"))
    requirements = _table(payload, "requirements", ("category", "check"), allow_empty=True)
    evidence = _table(
        payload, "evidence", ("seq", "asset", "check", "checked", "expires", "status"),
        allow_empty=True,
    )
    assets = {}
    for row in vehicles:
        asset, category = _key(row, "asset"), _key(row, "category")
        if asset in assets:
            raise ValueError(f"车辆编号重复 {asset}")
        assets[asset] = category
    required = set()
    for row in requirements:
        key = _key(row, "category"), _key(row, "check")
        if key in required:
            raise ValueError(f"车型检测规则重复 {key}")
        required.add(key)
    sequences = set()
    for row in evidence:
        asset, check = _key(row, "asset"), _key(row, "check")
        if asset not in assets or (assets[asset], check) not in required:
            raise ValueError(f"证据无法匹配车辆的检测规则 {asset}/{check}")
        seq, checked, expires = row["seq"], row["checked"], row["expires"]
        if type(seq) is not int or not 1 <= seq <= 1000000 or seq in sequences:
            raise ValueError("证据序号须为唯一的正整数（最多 1000000）")
        sequences.add(seq)
        if any(type(value) is not int for value in (checked, expires)):
            raise ValueError("检测及失效时间须填写当日整数分钟")
        if not 0 <= checked < expires <= 1440:
            raise ValueError("检测时间须早于失效时间，均在当日")
        if row["status"] not in ("pass", "fail"):
            raise ValueError("证据结论仅接受 pass 或 fail")
