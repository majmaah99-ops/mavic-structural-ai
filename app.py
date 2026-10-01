"""
app.py - خادم ويب لـ MIZAN by MAVIC على Render
===============================================

Flask web service that exposes the MIZAN audit pipeline.

Endpoints / المسارات:
    GET /                        → التقرير التفاعلي الكامل (HTML)
    GET /report                  → نفس التقرير (اسم بديل)
    GET /api/violations          → كل المخالفات (JSON)
    GET /api/violations/arch     → المخالفات المعمارية فقط (R9-R11)
    GET /api/violations/struct   → المخالفات الإنشائية فقط (R1-R8)
    GET /api/health              → فحص صحي للخدمة

On startup / عند التشغيل:
    - يحمّل النموذج من ``sample_model.json``
    - يشغّل محرك القواعد (11 قاعدة)
    - يُثري المخالفات بطبقة الذكاء الاصطناعي (offline mode)
    - يولّد التقرير HTML في مجلد ``docs/``
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory

from ai_layer import enhance_all
from report_generator import generate_report
from rules_engine import RulesEngine, load_model

# ---------------------------------------------------------------------------
# Config / الإعدادات
# ---------------------------------------------------------------------------
SERVICE_NAME = "mizan-by-mavic"
SERVICE_VERSION = "2.0.0"
TOTAL_RULES = 11
ARCH_RULE_IDS = {9, 10, 11}

MODEL_PATH = Path(os.environ.get("MODEL_PATH", "sample_model.json"))
REPORT_DIR = Path("docs")
REPORT_FILE = REPORT_DIR / "compliance_report.html"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Core audit / التدقيق الأساسي
# ---------------------------------------------------------------------------
def run_audit() -> dict:
    """
    تشغيل التدقيق الكامل وإرجاع ملخص.
    Runs the full audit and returns a summary dict.
    """
    model = load_model(MODEL_PATH)
    t0 = time.perf_counter()
    violations = RulesEngine.default().run(model)
    elapsed = time.perf_counter() - t0
    enriched = enhance_all(violations, model)

    REPORT_DIR.mkdir(exist_ok=True)
    generate_report(model, violations, enriched, str(REPORT_FILE), elapsed)

    # Split violations by category
    arch = [v.model_dump() for v in violations if v.rule_id in ARCH_RULE_IDS]
    struct = [v.model_dump() for v in violations if v.rule_id not in ARCH_RULE_IDS]

    return {
        "project": model.get("project", {}),
        "violations_count": len(violations),
        "arch_count": len(arch),
        "struct_count": len(struct),
        "elapsed_seconds": round(elapsed, 3),
        "report_path": str(REPORT_FILE),
        "violations": [v.model_dump() for v in violations],
        "arch_violations": arch,
        "struct_violations": struct,
        "enriched": enriched,
    }


# نُشغّل التدقيق عند بدء التطبيق (مرة واحدة)
try:
    _AUDIT = run_audit()
    print(
        f"✅ MIZAN by MAVIC audit complete: "
        f"{_AUDIT['violations_count']} violations "
        f"({_AUDIT['struct_count']} structural + {_AUDIT['arch_count']} architectural) "
        f"in {_AUDIT['elapsed_seconds']}s"
    )
except Exception as exc:  # noqa: BLE001
    print(f"⚠️  Startup audit failed: {type(exc).__name__}: {exc}")
    _AUDIT = {"error": str(exc)}


# ---------------------------------------------------------------------------
# Routes / المسارات
# ---------------------------------------------------------------------------
@app.route("/")
def index() -> Response:
    """التقرير الرئيسي. / Main report."""
    if REPORT_FILE.exists():
        return send_from_directory(REPORT_DIR, REPORT_FILE.name)
    return Response(
        f"<h1>MIZAN by MAVIC</h1>"
        f"<p>Report not yet generated. Error: {_AUDIT.get('error', 'unknown')}</p>",
        mimetype="text/html",
    )


@app.route("/report")
def report() -> Response:
    """اسم بديل للتقرير. / Alias for the report."""
    return index()


@app.route("/api/violations")
def api_violations():
    """كل المخالفات بصيغة JSON. / All violations as JSON."""
    return jsonify({
        "project": _AUDIT.get("project", {}),
        "violations_count": _AUDIT.get("violations_count", 0),
        "arch_count": _AUDIT.get("arch_count", 0),
        "struct_count": _AUDIT.get("struct_count", 0),
        "elapsed_seconds": _AUDIT.get("elapsed_seconds", 0),
        "violations": _AUDIT.get("violations", []),
    })


@app.route("/api/violations/arch")
def api_violations_arch():
    """المخالفات المعمارية فقط (R9, R10, R11)."""
    arch = _AUDIT.get("arch_violations", [])
    return jsonify({
        "category": "architectural",
        "rules": sorted(ARCH_RULE_IDS),
        "count": len(arch),
        "violations": arch,
    })


@app.route("/api/violations/struct")
def api_violations_struct():
    """المخالفات الإنشائية فقط (R1-R8)."""
    struct = _AUDIT.get("struct_violations", [])
    return jsonify({
        "category": "structural",
        "rules": [1, 2, 3, 4, 5, 6, 7, 8],
        "count": len(struct),
        "violations": struct,
    })


@app.route("/api/health")
def api_health():
    """فحص صحي. / Health check."""
    return jsonify({
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "rules_total": TOTAL_RULES,
        "rules_breakdown": {
            "structural": 8,
            "architectural": 3,
        },
        "violations_detected": _AUDIT.get("violations_count", 0),
        "audit_time_seconds": _AUDIT.get("elapsed_seconds", 0),
    })


# ---------------------------------------------------------------------------
# Entry point / نقطة التشغيل
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
