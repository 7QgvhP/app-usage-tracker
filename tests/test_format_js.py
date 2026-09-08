"""
test_format_js.py - 画面側（common.js）の時間表記が共通仕様どおりか検証する

表記の規則は Python・JavaScript・Kotlin の3つに実装されている。
コードは共有できないため、tests/duration_cases.py の表を唯一の仕様とし、
3つすべてを同じ内容で検証することで食い違いを防ぐ。

Node.js が無い環境では読み飛ばす（この検証だけのために必須にはしない）。
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.duration_cases import DURATION_CASES, MINUTES_CASES

NODE = shutil.which("node")
COMMON_JS = "static/common.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js が無いため検証できない")


def run_format(tmp_path, method: str, cases: list[tuple[int, str]]) -> list[str]:
    """common.js の format を Node で読み込み、各入力の結果を返す

    common.js は画面から読み込まれる素のスクリプトで、
    読み込んだだけでは DOM に触れないためそのまま評価できる。
    """
    source = open(COMMON_JS, encoding="utf-8").read()
    inputs = [value for value, _ in cases]

    script = tmp_path / "check.js"
    script.write_text(
        f"{source}\n"
        f"const inputs = {json.dumps(inputs)};\n"
        f"console.log(JSON.stringify(inputs.map((v) => format.{method}(v))));\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [NODE, str(script)], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return json.loads(result.stdout)


class TestJavaScriptFormat:
    """画面側の表記が Python・Kotlin と一致すること"""

    def test_秒数の表記が共通仕様と一致する(self, tmp_path):
        actual = run_format(tmp_path, "duration", DURATION_CASES)
        expected = [text for _, text in DURATION_CASES]

        assert actual == expected

    def test_分の表記が共通仕様と一致する(self, tmp_path):
        actual = run_format(tmp_path, "minutes", MINUTES_CASES)
        expected = [text for _, text in MINUTES_CASES]

        assert actual == expected
