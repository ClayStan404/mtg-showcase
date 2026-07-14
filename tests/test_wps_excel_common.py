"""parse_workbook 错误分级测试：单行错误保留有效行，meta 缺失跳过整表。"""

import sys
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wps_excel_common import parse_workbook  # noqa: E402


def _make_xlsx(tmp_path):
    """创建含一个工作表的 xlsx 文件"""
    wb = Workbook()
    wb.active.title = "TestSheet"
    p = tmp_path / "test.xlsx"
    wb.save(p)
    return p


def test_parse_workbook_row_errors_keeps_valid_items(tmp_path):
    """单行错误（errs 非空但 items 也非空）-> 保留该表有效数据"""
    p = _make_xlsx(tmp_path)

    def parse_sheet_fn(ws, name):
        return (
            {"seller": "Alice", "city": "Shanghai", "contact": "xxx"},
            [{"set": "neo", "number": "111"}],  # 有效行
            ["[TestSheet] 第5行：系列与编号须同时填写"],  # 行级错误
        )

    def merge_fn(items):
        return items

    result, errors = parse_workbook(p, parse_sheet_fn, merge_fn)
    assert "TestSheet" in result, "有有效行的表不应被跳过"
    assert len(result["TestSheet"][1]) == 1, "有效行应保留"
    assert len(errors) == 1, "错误仍应上报"


def test_parse_workbook_meta_errors_skips_sheet(tmp_path):
    """meta 缺失（errs 非空且 items 为空）-> 跳过整表"""
    p = _make_xlsx(tmp_path)

    def parse_sheet_fn(ws, name):
        return (
            {"seller": "", "city": "", "contact": ""},  # 空 meta
            [],  # parse_sheet 在 meta 错误时返回空 items
            ["[TestSheet] 缺少必填项「卖家」"],  # meta 错误
        )

    def merge_fn(items):
        return items

    result, errors = parse_workbook(p, parse_sheet_fn, merge_fn)
    assert "TestSheet" not in result, "meta 缺失的表应跳过"
    assert len(errors) == 1


def test_parse_workbook_no_errors_keeps_sheet(tmp_path):
    """无错误 -> 正常保留"""
    p = _make_xlsx(tmp_path)

    def parse_sheet_fn(ws, name):
        return (
            {"seller": "Bob", "city": "Beijing", "contact": "yyy"},
            [{"set": "neo", "number": "222"}],
            [],
        )

    def merge_fn(items):
        return items

    result, errors = parse_workbook(p, parse_sheet_fn, merge_fn)
    assert "TestSheet" in result
    assert len(result["TestSheet"][1]) == 1
    assert errors == []
