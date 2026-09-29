"""
main.py - نقطة التشغيل الرئيسية لمشروع MAVIC
==============================================

MAVIC AI Structural Compliance Agent — CLI Entry Point

الاستخدام / Usage:
    python main.py --model sample_model.json --out compliance_report.html
    python main.py --model sample_model.json --no-ai
    python main.py --help

يقوم هذا الملف بتنسيق سير العمل الكامل:
    1. تحميل النموذج الإنشائي من JSON
    2. تشغيل محرك القواعد (8 قواعد SBC)
    3. إثراء المخالفات بطبقة الذكاء الاصطناعي
    4. توليد التقرير التفاعلي HTML
    5. طباعة ملخص ملوَّن في الطرفية

Author: majmaah99-ops
Project: mavic-structural-ai
License: MIT
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from colorama import Fore, Style, init as colorama_init

from rules_engine import RulesEngine, load_model
from ai_layer import enhance_all
from report_generator import generate_report

colorama_init(autoreset=True)

# ----------------------------------------------------------------------------
# Terminal helpers / مساعدات الطرفية
# ----------------------------------------------------------------------------
SEVERITY_COLORS = {
    "CRITICAL": Fore.RED + Style.BRIGHT,
    "HIGH": Fore.YELLOW + Style.BRIGHT,
    "MEDIUM": Fore.BLUE + Style.BRIGHT,
}


def _banner() -> str:
    """شعار MAVIC في الطرفية. / ASCII banner."""
    return (
        f"\n{Fore.CYAN}{Style.BRIGHT}"
        "╔══════════════════════════════════════════════════════════════════╗\n"
        "║                                                                  ║\n"
        "║   MAVIC — AI Structural Compliance Agent                         ║\n"
        "║   المدقق الذكي للامتثال الإنشائي (SBC)                            ║\n"
        "║   IECE 2026 · Track 2 — Engineering Development                  ║\n"
        "║                                                                  ║\n"
        "╚══════════════════════════════════════════════════════════════════╝"
        f"{Style.RESET_ALL}\n"
    )


def _print_summary(violations, elapsed: float, report_path: Path) -> None:
    """طباعة ملخص ملوَّن للمخالفات. / Print a colored violations summary."""
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
    for v in violations:
        counts[v.severity] = counts.get(v.severity, 0) + 1

    print(f"\n{Fore.WHITE}{Style.BRIGHT}── نتيجة التدقيق ────────────────────────────{Style.RESET_ALL}")
    print(f"  ⏱️  زمن التدقيق      : {Fore.CYAN}{elapsed:.3f} ثانية{Style.RESET_ALL}")
    print(f"  🔢  إجمالي المخالفات : {Fore.WHITE}{Style.BRIGHT}{len(violations)}{Style.RESET_ALL}")
    for severity in ("CRITICAL", "HIGH", "MEDIUM"):
        color = SEVERITY_COLORS[severity]
        print(f"      {color}• {severity:<10}{Style.RESET_ALL} : {counts[severity]}")
    print(f"\n  📄  التقرير الكامل   : {Fore.GREEN}{report_path.resolve()}{Style.RESET_ALL}\n")


def _print_violations(violations) -> None:
    """طباعة كل مخالفة بالتفصيل. / Print each violation in detail."""
    print(f"{Fore.WHITE}{Style.BRIGHT}── تفاصيل المخالفات ─────────────────────────{Style.RESET_ALL}")
    for i, v in enumerate(violations, 1):
        color = SEVERITY_COLORS[v.severity]
        print(f"\n  {color}[{i}] ({v.severity}) R{v.rule_id} — {v.element_type} {v.element_id}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTWHITE_EX}{v.message_ar}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTBLACK_EX}{v.sbc_reference}{Style.RESET_ALL}")


# ----------------------------------------------------------------------------
# Main workflow / سير العمل الرئيسي
# ----------------------------------------------------------------------------
def run_audit(
    model_path: str | Path,
    out_path: str | Path,
    use_ai: bool = True,
    verbose: bool = True,
) -> tuple[int, float, Path]:
    """
    تشغيل التدقيق الكامل وإنتاج التقرير.

    Runs the complete audit pipeline:
        load → check → enhance → report.

    Returns:
        (violation_count, elapsed_seconds, report_path)
    """
    print(_banner())

    # 1. Load
    print(f"{Fore.CYAN}[1/4]{Style.RESET_ALL} تحميل النموذج الإنشائي من: {model_path}")
    model = load_model(model_path)
    project = model.get("project", {})
    print(f"       └─ المدينة: {project.get('city', '—')} | "
          f"المنطقة الزلزالية: {project.get('seismic_zone', '—')} | "
          f"عدد العناصر: "
          f"{len(model.get('columns', []))} عمود، "
          f"{len(model.get('beams', []))} جسر")

    # 2. Run rules engine
    print(f"\n{Fore.CYAN}[2/4]{Style.RESET_ALL} تشغيل محرك القواعد (8 قواعد SBC)...")
    t0 = time.perf_counter()
    violations = RulesEngine.default().run(model)
    elapsed = time.perf_counter() - t0
    print(f"       └─ {Fore.YELLOW}{len(violations)}{Style.RESET_ALL} مخالفة في {elapsed:.3f} ثانية")

    # 3. AI enhancement
    if use_ai:
        print(f"\n{Fore.CYAN}[3/4]{Style.RESET_ALL} إثراء المخالفات بطبقة الذكاء الاصطناعي...")
        enriched = enhance_all(violations, model)
        source = enriched[0].get("source", "offline") if enriched else "—"
        source_label = (
            f"{Fore.GREEN}متصل (OpenAI gpt-4o-mini){Style.RESET_ALL}"
            if source == "online"
            else f"{Fore.LIGHTBLACK_EX}غير متصل (قاموس مدمج){Style.RESET_ALL}"
        )
        print(f"       └─ الوضع: {source_label}")
    else:
        print(f"\n{Fore.CYAN}[3/4]{Style.RESET_ALL} تخطّي طبقة الذكاء الاصطناعي (--no-ai)")
        enriched = [{**v.model_dump(), "source": "skipped"} for v in violations]

    # 4. Generate report
    print(f"\n{Fore.CYAN}[4/4]{Style.RESET_ALL} توليد التقرير التفاعلي...")
    report_path = Path(out_path)
    generate_report(model, violations, enriched, str(report_path), elapsed)
    print(f"       └─ {Fore.GREEN}تم بنجاح{Style.RESET_ALL}")

    # Summary
    if verbose:
        _print_violations(violations)
        _print_summary(violations, elapsed, report_path)

    return len(violations), elapsed, report_path


# ----------------------------------------------------------------------------
# CLI / واجهة سطر الأوامر
# ----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """بناء محلل الوسائط. / Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="mavic",
        description="MAVIC — المدقق الذكي للامتثال الإنشائي وفق أكواد SBC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "أمثلة / Examples:\n"
            "  python main.py\n"
            "  python main.py --model sample_model.json --out report.html\n"
            "  python main.py --model sample_model.json --no-ai\n"
        ),
    )
    parser.add_argument(
        "--model", "-m",
        default="sample_model.json",
        help="مسار ملف النموذج الإنشائي JSON (افتراضي: sample_model.json)",
    )
    parser.add_argument(
        "--out", "-o",
        default="compliance_report.html",
        help="مسار ملف التقرير HTML الناتج (افتراضي: compliance_report.html)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="تعطيل طبقة الذكاء الاصطناعي (تسريع العرض)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="إخفاء تفاصيل المخالفات في الطرفية",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """نقطة الدخول. / Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"{Fore.RED}✗ خطأ: الملف غير موجود: {model_path}{Style.RESET_ALL}")
        return 1

    try:
        run_audit(
            model_path=model_path,
            out_path=args.out,
            use_ai=not args.no_ai,
            verbose=not args.quiet,
        )
        return 0
    except Exception as exc:
        print(f"\n{Fore.RED}✗ خطأ غير متوقع: {type(exc).__name__}: {exc}{Style.RESET_ALL}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())