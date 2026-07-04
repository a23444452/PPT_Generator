"""共用的表格 → markdown 表格 helper。

抽出 excel_converter 與 docx_converter 都需要的儲存格跳脫與組行邏輯，
避免兩處各自重複轉義規則（`|`、`\\r`、`\\n`）造成日後修一處漏一處。
"""


def escape_cell(value: str) -> str:
    """儲存格文字跳脫：避免內容中的 `|`／換行破壞 md 表格語法。"""
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def rows_to_markdown_table(rows: list[list[str]]) -> str:
    """把二維字串陣列組成 md 表格，第一列視為表頭。"""
    if not rows:
        return ""
    n_cols = len(rows[0])
    lines = ["| " + " | ".join(escape_cell(c) for c in rows[0]) + " |"]
    lines.append("|" + " --- |" * n_cols)
    for row in rows[1:]:
        lines.append("| " + " | ".join(escape_cell(c) for c in row) + " |")
    return "\n".join(lines)
