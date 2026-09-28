"""Render a Figma-importable SVG from the validated benchmark summaries."""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent
FULL = json.loads((ROOT / "full-clio" / "summary.json").read_text())
ONE = json.loads((ROOT / "one-shot" / "summary.json").read_text())
LABELS = {
    "verdict": "판정",
    "root_cause": "원인 분석",
    "code_location": "코드 위치",
    "evidence_quality": "근거 품질",
    "reproduction": "재현 계획",
    "uncertainty": "불확실성 표현",
}


def text(x: int, y: int, value: str, size: int, color: str, weight: int = 400) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Pretendard,Apple SD Gothic Neo,Noto Sans KR,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{escape(value)}</text>'
    )


def rect(x: float, y: float, width: float, height: float, color: str, radius: int = 0) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="{radius}" fill="{color}"/>'


def main() -> None:
    navy = "#132238"
    muted = "#5C697A"
    teal = "#007F77"
    gray = "#AAB5C3"
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">']
    svg.append(rect(0, 0, 1200, 760, "#F8FAFC"))
    svg.append(rect(48, 42, 6, 84, teal, 3))
    svg.append(text(75, 74, "CLIO · 동일 30건 비교 실험", 29, navy, 700))
    svg.append(text(75, 108, "10개 결함 × 보고 문구 3종 · 동일 fixture / oracle / 제한시간", 17, muted))

    svg.append(rect(48, 149, 1104, 111, "#EAF5F3", 16))
    svg.append(text(74, 182, "평균 품질 점수", 15, muted, 600))
    svg.append(text(74, 229, f"{FULL['mean_score']:.1f}", 43, teal, 700))
    svg.append(text(202, 229, "vs", 22, muted))
    svg.append(text(243, 229, f"{ONE['mean_score']:.1f}", 43, navy, 700))
    svg.append(text(425, 215, f"+{FULL['mean_score'] - ONE['mean_score']:.1f}점", 28, teal, 700))
    svg.append(text(425, 240, "full-clio 우세", 14, muted))
    svg.append(text(725, 192, "70점 이상", 15, muted))
    svg.append(text(725, 232, "28/30", 31, teal, 700))
    svg.append(text(855, 232, "vs", 18, muted))
    svg.append(text(898, 232, "24/30", 31, navy, 700))
    svg.append(text(75, 308, "평가 항목별 평균", 22, navy, 700))
    svg.append(rect(830, 291, 16, 16, teal, 3))
    svg.append(text(854, 305, "full-clio", 15, muted))
    svg.append(rect(975, 291, 16, 16, gray, 3))
    svg.append(text(999, 305, "one-shot", 15, muted))

    for index, (key, label) in enumerate(LABELS.items()):
        y = 337 + index * 58
        a = FULL["dimensions"][key] * 100
        b = ONE["dimensions"][key] * 100
        svg.append(text(75, y + 25, label, 17, navy, 600))
        svg.append(rect(280, y, 674, 17, "#E8EDF2", 8))
        svg.append(rect(280, y, 6.74 * a, 17, teal, 8))
        svg.append(rect(280, y + 23, 674, 12, "#E8EDF2", 6))
        svg.append(rect(280, y + 23, 6.74 * b, 12, gray, 6))
        svg.append(text(972, y + 16, f"{a:.1f}%", 16, teal, 700))
        svg.append(text(972, y + 36, f"{b:.1f}%", 14, muted))

    svg.append(rect(48, 704, 1104, 1, "#D8E0E8"))
    svg.append(text(58, 729, "독립 결함 10개 · 단일 실행 · 자동 채점 / 사람 리뷰 필요", 14, muted))
    svg.append(text(823, 729, "분석 평균 소요 +5.3초", 14, muted))
    svg.append("</svg>")
    (ROOT / "benchmark-comparison.svg").write_text("\n".join(svg) + "\n")


if __name__ == "__main__":
    main()
