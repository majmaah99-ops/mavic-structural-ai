"""
app.py - خادم ويب لـ MAVIC على Render
=====================================

Converts the MAVIC audit pipeline into a tiny Flask web service so it can
be deployed to Render as a Web Service.

Endpoints / المسارات:
    GET /            → التقرير التفاعلي الكامل (HTML)
    GET /report      → نفس التقرير (اسم بديل)
    GET /api/violations → المخالفات بصيغة JSON
    GET /api/health  → فحص صحي للخدمة

On startup / عند التشغيل:
    - يحمّل النموذج من ``sample_model.json``
    - يشغّل محرك القواعد
    - يُثري المخالفات بطبقة الذكاء الاصطناعي (offline mode)
    - يولّد التقرير HTML في الذاكرة (مؤقتاً حتى التحديث التالي)
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

    return {
        "project": model.get("project", {}),
        "violations_count": len(violations),
        "elapsed_seconds": round(elapsed, 3),
        "report_path": str(REPORT_FILE),
        "violations": [v.model_dump() for v in violations],
        "enriched": enriched,
    }


# نُشغّل التدقيق عند بدء التطبيق (مرة واحدة)
try:
    _AUDIT = run_audit()
    print(f"✅ MAVIC audit complete: {_AUDIT['violations_count']} violations "
          f"in {_AUDIT['elapsed_seconds']}s")
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
        f"<h1>MAVIC</h1><p>Report not yet generated. Error: {_AUDIT.get('error', 'unknown')}</p>",
        mimetype="text/html",
    )


@app.route("/report")
def report() -> Response:
    """اسم بديل للتقرير. / Alias for the report."""
    return index()


@app.route("/api/violations")
def api_violations():
    """المخالفات بصيغة JSON. / Violations as JSON."""
    return jsonify({
        "project": _AUDIT.get("project", {}),
        "violations_count": _AUDIT.get("violations_count", 0),
        "elapsed_seconds": _AUDIT.get("elapsed_seconds", 0),
        "violations": _AUDIT.get("violations", []),
    })


@app.route("/api/health")
def api_health():
    """فحص صحي. / Health check."""
    return jsonify({"status": "ok", "service": "mavic", "version": "1.0.0"})


# ---------------------------------------------------------------------------
# Entry point / نقطة التشغيل
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
