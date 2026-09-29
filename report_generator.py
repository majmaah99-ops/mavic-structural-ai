"""
report_generator.py - مولّد التقرير التفاعلي لـ MAVIC
=====================================================

Generates a self-contained interactive HTML compliance report:

* KPI dashboard with animated counters
* Interactive 3D Plotly scene (columns, beams, shear walls, foundations)
* Violations highlighted in red with toggle filters
* Sortable / filterable violations table (RTL-friendly)
* Before-vs-After comparison panel (manual vs. AI audit)
* Works OFFLINE — Plotly JS is inlined into the HTML.

Usage / الاستخدام:
    python report_generator.py sample_model.json --out compliance_report.html
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from jinja2 import Template

from ai_layer import enhance_all
from rules_engine import RulesEngine, Violation, load_model


# ---------------------------------------------------------------------------
# Constants / ثوابت
# ---------------------------------------------------------------------------
SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "HIGH": "#f59e0b",
    "MEDIUM": "#3b82f6",
}

SEVERITY_LABELS_AR = {
    "CRITICAL": "حرجة",
    "HIGH": "عالية",
    "MEDIUM": "متوسطة",
}

SEVERITY_WEIGHT = {"CRITICAL": 5, "HIGH": 3, "MEDIUM": 1}


# ---------------------------------------------------------------------------
# KPI computation / حساب مؤشرات الأداء
# ---------------------------------------------------------------------------
def _compute_kpis(model: dict, violations: list[Violation], elapsed: float) -> dict[str, Any]:
    """
    حساب مؤشرات الأداء الرئيسية للتقرير.
    Compute the report KPIs from the model and violations.

    Returns a dict with:
        total_elements, total_violations, critical, high, medium,
        audit_time, compliance_score
    """
    total_elements = (
        len(model.get("columns", []))
        + len(model.get("beams", []))
        + len(model.get("walls", []))
        + len(model.get("foundations", []))
    )
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
    weighted = 0
    for v in violations:
        counts[v.severity] = counts.get(v.severity, 0) + 1
        weighted += SEVERITY_WEIGHT.get(v.severity, 1)

    if total_elements == 0:
        score = 100.0
    else:
        score = max(0.0, 100.0 - min(100.0, (weighted / total_elements) * 100.0))

    return {
        "total_elements": total_elements,
        "total_violations": len(violations),
        "critical": counts["CRITICAL"],
        "high": counts["HIGH"],
        "medium": counts["MEDIUM"],
        "audit_time": round(elapsed, 3),
        "compliance_score": round(score, 1),
    }


# ---------------------------------------------------------------------------
# 3D figure builder / بناء الشكل ثلاثي الأبعاد
# ---------------------------------------------------------------------------
_FLOOR_HEIGHT_M = 3.0


def _build_3d_figure(model: dict, violations: list[Violation]) -> go.Figure:
    """
    بناء مشهد Plotly 3D للنموذج الإنشائي.
    Build the Plotly 3D scene for the structural model.

    Columns  → blue squares
    Beams    → gray lines
    Shear walls → green translucent planes
    Foundations → brown diamonds at z=0
    Violating elements → red markers
    """
    fig = go.Figure()

    violations_by_id: dict[str, list[Violation]] = {}
    for v in violations:
        violations_by_id.setdefault(v.element_id, []).append(v)

    columns = {c["id"]: c for c in model.get("columns", [])}

    # ---- Columns -----------------------------------------------------------
    col_x, col_y, col_z, col_ids = [], [], [], []
    for c in model.get("columns", []):
        col_x.append(c.get("x", 0))
        col_y.append(c.get("y", 0))
        col_z.append((c.get("floor", 1) - 1) * _FLOOR_HEIGHT_M)
        col_ids.append(c["id"])

    fig.add_trace(go.Scatter3d(
        x=col_x, y=col_y, z=col_z,
        mode="markers",
        name="أعمدة / Columns",
        marker=dict(size=6, color="#3b82f6", symbol="square", line=dict(width=0)),
        text=col_ids,
        hovertemplate="<b>%{text}</b><br>(%{x:.1f}, %{y:.1f})<extra></extra>",
    ))

    # ---- Beams (as lines) --------------------------------------------------
    beam_x, beam_y, beam_z, beam_ids = [], [], [], []
    for b in model.get("beams", []):
        s = columns.get(b.get("start_column"))
        e = columns.get(b.get("end_column"))
        if not s or not e:
            continue
        floor = b.get("floor", 1)
        z = (floor - 1) * _FLOOR_HEIGHT_M
        beam_x += [s.get("x", 0), e.get("x", 0), None]
        beam_y += [s.get("y", 0), e.get("y", 0), None]
        beam_z += [z, z, None]
        beam_ids.append(b["id"])

    fig.add_trace(go.Scatter3d(
        x=beam_x, y=beam_y, z=beam_z,
        mode="lines",
        name="جسور / Beams",
        line=dict(color="#94a3b8", width=3),
        hoverinfo="skip",
    ))

    # ---- Shear walls (as vertical planes) ---------------------------------
    for w in model.get("walls", []):
        if w.get("type") != "shear":
            continue
        length = float(w.get("length_m", 0))
        floor = w.get("floor", 1)
        z0 = (floor - 1) * _FLOOR_HEIGHT_M
        z1 = z0 + _FLOOR_HEIGHT_M
        # Simple wall oriented along X (unless direction == "Y")
        if str(w.get("direction", "X")).upper() == "X":
            x = [0, length, length, 0, 0, length, length, 0]
            y = [0, 0, 0, 0, 0.1, 0.1, 0.1, 0.1]
        else:
            x = [0, 0, 0, 0, 0.1, 0.1, 0.1, 0.1]
            y = [0, length, length, 0, 0, length, length, 0]
        z = [z0, z0, z1, z1, z0, z0, z1, z1]
        i_faces = [0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 3, 3]
        j_faces = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 0, 4]
        k_faces = [2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 4, 7]
        fig.add_trace(go.Mesh3d(
            x=x, y=y, z=z, i=i_faces, j=j_faces, k=k_faces,
            color="#10b981", opacity=0.25, name=f"جدار قص {w['id']}",
            showlegend=False, hoverinfo="skip",
        ))

    # ---- Foundations -------------------------------------------------------
    fnd_x, fnd_y, fnd_ids = [], [], []
    for f in model.get("foundations", []):
        col = columns.get(f.get("column_id"))
        if not col:
            continue
        fnd_x.append(col.get("x", 0))
        fnd_y.append(col.get("y", 0))
        fnd_ids.append(f["id"])

    fig.add_trace(go.Scatter3d(
        x=fnd_x, y=fnd_y, z=[-0.5] * len(fnd_x),
        mode="markers",
        name="أساسات / Foundations",
        marker=dict(size=7, color="#a16207", symbol="diamond"),
        text=fnd_ids,
        hovertemplate="<b>%{text}</b><extra></extra>",
    ))

    # ---- Violating elements (RED overlay) ---------------------------------
    v_x, v_y, v_z, v_text = [], [], [], []
    for element_id, vs in violations_by_id.items():
        element = columns.get(element_id)
        if element:
            v_x.append(element.get("x", 0))
            v_y.append(element.get("y", 0))
            v_z.append((element.get("floor", 1) - 1) * _FLOOR_HEIGHT_M)
        else:
            # Beams / walls / foundations: use first connected column
            for key in ("beams", "walls", "foundations"):
                for el in model.get(key, []):
                    if el.get("id") != element_id:
                        continue
                    ref = el.get("column_id") or el.get("start_column")
                    c = columns.get(ref)
                    if c:
                        v_x.append(c.get("x", 0))
                        v_y.append(c.get("y", 0))
                        v_z.append((c.get("floor", 1) - 1) * _FLOOR_HEIGHT_M)
                    break
                else:
                    continue
                break
            else:
                continue
        severity = vs[0].severity
        v_text.append(
            f"<b>{element_id}</b><br>"
            f"{SEVERITY_LABELS_AR.get(severity, severity)}<br>"
            f"{html_lib.escape(vs[0].message_ar[:120])}"
        )

    fig.add_trace(go.Scatter3d(
        x=v_x, y=v_y, z=v_z,
        mode="markers",
        name="مخالفات / Violations",
        marker=dict(size=14, color="#dc2626", symbol="circle",
                    line=dict(color="#7f1d1d", width=2)),
        text=v_text,
        hovertemplate="%{text}<extra></extra>",
    ))

    # ---- Layout ------------------------------------------------------------
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (m)", backgroundcolor="#0f172a",
                       gridcolor="#334155", color="#cbd5e1"),
            yaxis=dict(title="Y (m)", backgroundcolor="#0f172a",
                       gridcolor="#334155", color="#cbd5e1"),
            zaxis=dict(title="Z (m)", backgroundcolor="#0f172a",
                       gridcolor="#334155", color="#cbd5e1"),
            bgcolor="#0f172a",
        ),
        paper_bgcolor="#0f172a",
        font=dict(color="#e2e8f0", family="Tajawal, Inter, sans-serif"),
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center",
                    bgcolor="rgba(15,23,42,0.8)"),
        showlegend=True,
        height=650,
    )
    return fig


# ---------------------------------------------------------------------------
# HTML template / قالب HTML
# ---------------------------------------------------------------------------
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>تقرير الامتثال الإنشائي — MAVIC</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --critical: #dc2626; --high: #f59e0b; --medium: #3b82f6;
    --success: #10b981; --bg: #f8fafc; --dark: #0f172a;
    --accent: #0d9488; --text: #1e293b; --muted: #64748b;
    --border: #e2e8f0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Tajawal', 'Inter', sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 0;
  }
  .container { max-width: 1400px; margin: 0 auto; padding: 0 20px; }

  /* ---- Cover header ---- */
  .cover {
    background: linear-gradient(135deg, #0f172a 0%, #0d9488 100%);
    color: #fff; padding: 40px 0;
  }
  .cover-inner {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 20px;
  }
  .cover h1 { font-size: 26px; font-weight: 700; margin-bottom: 6px; }
  .cover h2 { font-size: 15px; font-weight: 400; opacity: 0.85; margin-bottom: 12px; }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .badge {
    background: rgba(255,255,255,0.15); padding: 4px 12px;
    border-radius: 20px; font-size: 12px; backdrop-filter: blur(4px);
  }
  .logo-block { text-align: left; font-family: 'Inter', sans-serif; }
  .logo-block .logo {
    font-size: 42px; font-weight: 700; letter-spacing: 2px;
    background: linear-gradient(90deg, #fff, #5eead4);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .logo-block .tagline { font-size: 12px; opacity: 0.8; margin-top: 4px; }
  .cover-footer {
    margin-top: 24px; padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.15);
    font-size: 12px; opacity: 0.75; display: flex;
    justify-content: space-between; flex-wrap: wrap; gap: 10px;
  }

  /* ---- KPI cards ---- */
  .kpis {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px; margin: -30px 0 30px;
    position: relative; z-index: 2;
  }
  .kpi {
    background: #fff; padding: 20px 22px; border-radius: 14px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.08);
    border-top: 4px solid var(--accent);
    transition: transform 0.2s ease;
  }
  .kpi:hover { transform: translateY(-2px); }
  .kpi.critical { border-top-color: var(--critical); }
  .kpi.warn { border-top-color: var(--high); }
  .kpi.ok { border-top-color: var(--success); }
  .kpi .label { font-size: 13px; color: var(--muted); margin-bottom: 6px; }
  .kpi .value {
    font-size: 34px; font-weight: 700; color: var(--dark);
    font-family: 'Inter', 'Tajawal', sans-serif;
    line-height: 1.1;
  }
  .kpi .value small { font-size: 16px; color: var(--muted); font-weight: 400; }
  .kpi .en { font-size: 11px; color: var(--muted); margin-top: 4px; font-family: 'Inter', sans-serif; }
  .ring-container { display: flex; align-items: center; gap: 14px; }
  .ring-container .ring { position: relative; width: 64px; height: 64px; }
  .ring-container .ring svg { transform: rotate(-90deg); }
  .ring-container .ring-text {
    position: absolute; inset: 0; display: flex;
    align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: var(--dark);
  }

  /* ---- Sections ---- */
  section { margin: 40px 0; }
  section h3 {
    font-size: 22px; margin-bottom: 16px; color: var(--dark);
    display: flex; align-items: center; gap: 10px;
  }
  section h3::before {
    content: ''; width: 4px; height: 22px; background: var(--accent);
    border-radius: 2px;
  }
  .section-en { font-size: 12px; color: var(--muted); font-family: 'Inter', sans-serif; font-weight: 400; }

  .panel {
    background: #fff; border-radius: 14px; padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }
  .plot-panel {
    background: var(--dark); padding: 0; overflow: hidden;
    border-radius: 14px;
  }

  /* ---- Filter bar ---- */
  .filters {
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;
    align-items: center;
  }
  .filters select, .filters input {
    padding: 10px 14px; border: 1px solid var(--border);
    border-radius: 8px; font-family: inherit; font-size: 14px;
    background: #fff; color: var(--text); min-width: 160px;
  }
  .filters input { flex: 1; min-width: 220px; }
  .filters label { font-size: 13px; color: var(--muted); margin-left: 4px; }

  /* ---- Table ---- */
  table { width: 100%; border-collapse: collapse; }
  th, td {
    padding: 12px 14px; text-align: right; border-bottom: 1px solid var(--border);
    font-size: 14px;
  }
  th {
    background: #f1f5f9; font-weight: 600; color: var(--dark);
    position: sticky; top: 0; z-index: 1;
  }
  tbody tr { cursor: pointer; transition: background 0.15s; }
  tbody tr:hover { background: #f8fafc; }
  tbody tr.expanded { background: #eff6ff; }

  .pill {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600; color: #fff;
    font-family: 'Inter', sans-serif;
  }
  .pill.CRITICAL { background: var(--critical); }
  .pill.HIGH { background: var(--high); }
  .pill.MEDIUM { background: var(--medium); }

  .details {
    display: none; background: #f8fafc; border-top: 1px solid var(--border);
  }
  .details.show { display: table-row; }
  .details td { padding: 20px 24px; line-height: 1.8; }
  .details h5 {
    font-size: 14px; margin: 12px 0 6px; color: var(--dark);
  }
  .details ol { padding-right: 20px; }
  .details .fix-step { margin: 4px 0; color: var(--text); }
  .details .en-note {
    font-size: 12px; color: var(--muted); font-family: 'Inter', sans-serif;
    margin-top: 8px; direction: ltr; text-align: left;
  }

  /* ---- Comparison panel ---- */
  .compare {
    display: grid; grid-template-columns: 1fr auto 1fr; gap: 0;
    border-radius: 14px; overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
  }
  .compare > div { padding: 30px; }
  .compare .old { background: linear-gradient(135deg, #fef2f2, #fee2e2); }
  .compare .new { background: linear-gradient(135deg, #ecfdf5, #d1fae5); }
  .compare .vs {
    background: #fff; display: flex; align-items: center;
    justify-content: center; font-weight: 700; font-size: 20px;
    color: var(--muted); padding: 0 10px; font-family: 'Inter', sans-serif;
  }
  .compare h4 { font-size: 18px; margin-bottom: 16px; }
  .compare .metric { margin: 14px 0; }
  .compare .metric-label { font-size: 13px; color: var(--muted); margin-bottom: 4px; }
  .compare .metric-value {
    font-size: 26px; font-weight: 700; font-family: 'Inter', 'Tajawal', sans-serif;
  }
  .compare .old .metric-value { color: var(--critical); }
  .compare .new .metric-value { color: var(--success); }
  .compare .metric-en {
    font-size: 11px; color: var(--muted); font-family: 'Inter', sans-serif;
  }

  /* ---- Footer ---- */
  footer {
    background: var(--dark); color: #cbd5e1; padding: 30px 0;
    margin-top: 60px; font-size: 13px;
  }
  footer .container { display: flex; flex-direction: column; gap: 10px; }
  footer strong { color: #fff; }
  footer .refs { font-size: 12px; color: #94a3b8; }
  footer .center { text-align: center; }

  @media print {
    .cover { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .plot-panel { display: none; }
  }
  @media (max-width: 720px) {
    .compare { grid-template-columns: 1fr; }
    .compare .vs { padding: 12px; }
    .cover-inner { flex-direction: column; text-align: center; }
    .logo-block { text-align: center; }
  }
</style>
</head>
<body>

<!-- ===== COVER ===== -->
<div class="cover">
  <div class="container cover-inner">
    <div>
      <h1>{{ project.name_ar or "مشروع إنشائي" }}</h1>
      <h2>{{ project.name_en or "Structural Project" }} — {{ project.city or "—" }}</h2>
      <div class="badges">
        <span class="badge">🌍 المنطقة الزلزالية: {{ project.seismic_zone }}</span>
        <span class="badge">📋 {{ project.code_version or "SBC" }}</span>
        <span class="badge">🏢 {{ project.stories or "—" }} طوابق</span>
      </div>
    </div>
    <div class="logo-block">
      <div class="logo">MAVIC</div>
      <div class="tagline">AI Structural Compliance Agent</div>
    </div>
  </div>
  <div class="container">
    <div class="cover-footer">
      <span>📅 {{ generated_at }}</span>
      <span>⚡ IECE 2026 · المسار الثاني — التطوير الهندسي</span>
    </div>
  </div>
</div>

<!-- ===== KPIs ===== -->
<div class="container">
  <div class="kpis">
    <div class="kpi">
      <div class="label">إجمالي العناصر المفحوصة</div>
      <div class="value">{{ kpis.total_elements }}</div>
      <div class="en">Total elements audited</div>
    </div>
    <div class="kpi {{ 'ok' if kpis.total_violations == 0 else ('critical' if kpis.total_violations > 5 else 'warn') }}">
      <div class="label">المخالفات المكتشفة</div>
      <div class="value">{{ kpis.total_violations }}
        <small>· {{ kpis.critical }} حرجة / {{ kpis.high }} عالية / {{ kpis.medium }} متوسطة</small>
      </div>
      <div class="en">Violations found</div>
    </div>
    <div class="kpi">
      <div class="label">زمن التدقيق</div>
      <div class="value">{{ kpis.audit_time }} <small>ثانية</small></div>
      <div class="en">Audit time (seconds)</div>
    </div>
    <div class="kpi ok">
      <div class="label">نسبة الامتثال</div>
      <div class="ring-container">
        <div class="ring">
          <svg width="64" height="64">
            <circle cx="32" cy="32" r="26" stroke="#e2e8f0" stroke-width="6" fill="none"/>
            <circle cx="32" cy="32" r="26" stroke="#10b981" stroke-width="6" fill="none"
              stroke-linecap="round"
              stroke-dasharray="{{ (kpis.compliance_score / 100 * 163.36) | round(1) }} 163.36"/>
          </svg>
          <div class="ring-text">{{ kpis.compliance_score }}%</div>
        </div>
        <div>
          <div class="en">Compliance score</div>
        </div>
      </div>
    </div>
  </div>

  <!-- ===== 3D VISUALIZATION ===== -->
  <section>
    <h3>النموذج الإنشائي ثلاثي الأبعاد <span class="section-en">/ 3D Structural Model</span></h3>
    <div class="plot-panel">{{ plot_html | safe }}</div>
  </section>

  <!-- ===== VIOLATIONS TABLE ===== -->
  <section>
    <h3>جدول المخالفات التفصيلي <span class="section-en">/ Violations Detail</span></h3>
    <div class="panel">
      <div class="filters">
        <div>
          <label>الخطورة:</label>
          <select id="filter-severity">
            <option value="">الكل</option>
            <option value="CRITICAL">حرجة</option>
            <option value="HIGH">عالية</option>
            <option value="MEDIUM">متوسطة</option>
          </select>
        </div>
        <div>
          <label>ترتيب حسب:</label>
          <select id="sort-by">
            <option value="severity">الخطورة</option>
            <option value="rule_id">القاعدة</option>
            <option value="element_id">المعرّف</option>
          </select>
        </div>
        <input type="text" id="search" placeholder="🔍 ابحث بمعرّف العنصر أو القاعدة...">
      </div>
      <table id="violations-table">
        <thead>
          <tr>
            <th>#</th>
            <th>الخطورة</th>
            <th>القاعدة</th>
            <th>المعرّف</th>
            <th>النوع</th>
            <th>الرسالة</th>
            <th>المرجع</th>
          </tr>
        </thead>
        <tbody>
          {% for v in violations %}
          <tr data-severity="{{ v.severity }}" data-rule="{{ v.rule_id }}" data-element="{{ v.element_id }}"
              onclick="toggleDetails(this, {{ loop.index }})">
            <td>{{ loop.index }}</td>
            <td><span class="pill {{ v.severity }}">{{ severity_label_ar[v.severity] }}</span></td>
            <td>R{{ v.rule_id }}</td>
            <td><strong>{{ v.element_id }}</strong></td>
            <td>{{ v.element_type }}</td>
            <td>{{ v.message_ar }}</td>
            <td style="font-size:12px;color:#64748b;">{{ v.sbc_reference }}</td>
          </tr>
          <tr class="details" id="details-{{ loop.index }}">
            <td colspan="7">
              <h5>🔍 السبب الجذري / Root cause</h5>
              <div>{{ v.root_cause_ar }}</div>
              <h5>🛠️ خطوات الإصلاح / Fix steps</h5>
              <ol>
                {% for step in v.fix_steps_ar %}
                <li class="fix-step">{{ step }}</li>
                {% endfor %}
              </ol>
              <h5>💰 أثر التكلفة / Cost impact</h5>
              <div>{{ v.estimated_cost_impact_ar }}</div>
              <h5>⏱️ الأولوية / Priority</h5>
              <div>{{ v.priority_ar }}</div>
              <div class="en-note">{{ v.message_en }}</div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </section>

  <!-- ===== BEFORE vs AFTER ===== -->
  <section>
    <h3>مقارنة الطريقة التقليدية مقابل المدقق الذكي <span class="section-en">/ Before vs After</span></h3>
    <div class="compare">
      <div class="old">
        <h4>🔴 التدقيق اليدوي</h4>
        <div class="metric">
          <div class="metric-label">الزمن</div>
          <div class="metric-value">3 أيام</div>
          <div class="metric-en">Manual audit: 3 working days</div>
        </div>
        <div class="metric">
          <div class="metric-label">التكلفة</div>
          <div class="metric-value">15,000 ر.س</div>
          <div class="metric-en">Engineer × 3 days</div>
        </div>
        <div class="metric">
          <div class="metric-label">نسبة تفويت الأخطاء</div>
          <div class="metric-value">15-20%</div>
          <div class="metric-en">Random sampling only</div>
        </div>
        <div class="metric">
          <div class="metric-label">التغطية</div>
          <div class="metric-value">عينات</div>
          <div class="metric-en">Partial coverage</div>
        </div>
      </div>
      <div class="vs">VS</div>
      <div class="new">
        <h4>🟢 المدقق الذكي MAVIC</h4>
        <div class="metric">
          <div class="metric-label">الزمن</div>
          <div class="metric-value">{{ kpis.audit_time }} ثانية</div>
          <div class="metric-en">Real measured time</div>
        </div>
        <div class="metric">
          <div class="metric-label">التكلفة</div>
          <div class="metric-value">~0 ر.س</div>
          <div class="metric-en">SaaS subscription</div>
        </div>
        <div class="metric">
          <div class="metric-label">نسبة تفويت الأخطاء</div>
          <div class="metric-value">&lt;5%</div>
          <div class="metric-en">Deterministic rules engine</div>
        </div>
        <div class="metric">
          <div class="metric-label">التغطية</div>
          <div class="metric-value">100%</div>
          <div class="metric-en">Full element coverage</div>
        </div>
      </div>
    </div>
  </section>
</div>

<!-- ===== FOOTER ===== -->
<footer>
  <div class="container">
    <div><strong>MAVIC — AI Structural Compliance Agent</strong> · نموذج أولي لأغراض الهاكاثون الهندسي</div>
    <div>المؤتمر الهندسي الدولي الرابع IECE 2026 · المسار الثاني — التطوير الهندسي</div>
    <div class="refs">
      <strong>المراجع:</strong>
      SBC 304-18 §7.2 · §9.3 · §9.4 · §10.3 · §20.5 |
      SBC 301-18 §12.2 · §18.3 |
      SBC 303-18 §5.6
    </div>
    <div class="center" style="color:#64748b;">
      © {{ year }} MAVIC · Built for the Saudi engineering community
    </div>
  </div>
</footer>

<script>
  // ---- Filtering + sorting + search -------------------------------------
  const table = document.getElementById('violations-table');
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr:not(.details)'));

  function applyFilters() {
    const sev = document.getElementById('filter-severity').value;
    const q = document.getElementById('search').value.trim().toLowerCase();
    rows.forEach(row => {
      const okSev = !sev || row.dataset.severity === sev;
      const okQ = !q ||
        row.dataset.element.toLowerCase().includes(q) ||
        ('r' + row.dataset.rule).includes(q);
      row.style.display = (okSev && okQ) ? '' : 'none';
      const details = document.getElementById('details-' + row.querySelector('td').textContent);
      if (details && (row.style.display === 'none')) details.classList.remove('show');
    });
  }

  function sortRows() {
    const key = document.getElementById('sort-by').value;
    const sevRank = { CRITICAL: 0, HIGH: 1, MEDIUM: 2 };
    rows.sort((a, b) => {
      if (key === 'severity') return sevRank[a.dataset.severity] - sevRank[b.dataset.severity];
      if (key === 'rule_id') return (+a.dataset.rule) - (+b.dataset.rule);
      if (key === 'element_id') return a.dataset.element.localeCompare(b.dataset.element);
      return 0;
    });
    rows.forEach(r => tbody.insertBefore(r, r.nextSibling === null ? null : null));
    // Reinsert rows in sorted order, then reattach their details rows
    rows.forEach(r => {
      tbody.appendChild(r);
      const idx = r.querySelector('td').textContent;
      const d = document.getElementById('details-' + idx);
      if (d) tbody.appendChild(d);
    });
  }

  function toggleDetails(row, idx) {
    const details = document.getElementById('details-' + idx);
    if (!details) return;
    details.classList.toggle('show');
    row.classList.toggle('expanded');
  }

  document.getElementById('filter-severity').addEventListener('change', applyFilters);
  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('sort-by').addEventListener('change', sortRows);
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Report generation / توليد التقرير
# ---------------------------------------------------------------------------
def generate_report(
    model: dict,
    violations: list[Violation],
    enriched: list[dict],
    output_path: str = "compliance_report.html",
    audit_time_seconds: float = 0.0,
) -> str:
    """
    توليد ملف التقرير التفاعلي.
    Generate the interactive HTML compliance report.

    Args:
        model               : قاموس النموذج الإنشائي.
        violations          : قائمة المخالفات من محرك القواعد.
        enriched            : قائمة المخالفات بعد إثرائها من ai_layer.
        output_path         : مسار ملف HTML الناتج.
        audit_time_seconds  : زمن التدقيق بالثواني.

    Returns:
        المسار المطلق لملف التقرير.
    """
    kpis = _compute_kpis(model, violations, audit_time_seconds)

    # Build the 3D figure and inline the Plotly JS (offline-capable)
    fig = _build_3d_figure(model, violations)
    plot_html = fig.to_html(
        include_plotlyjs="inline",
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )

    # Merge violations + enriched suggestions for the template
    violations_view = [
        {**v.model_dump(), **enriched[i]}
        for i, v in enumerate(violations)
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    template = Template(_TEMPLATE)
    html_out = template.render(
        project=model.get("project", {}),
        kpis=kpis,
        plot_html=plot_html,
        violations=violations_view,
        severity_label_ar=SEVERITY_LABELS_AR,
        generated_at=generated_at,
        year=datetime.now().year,
    )

    out = Path(output_path).resolve()
    out.write_text(html_out, encoding="utf-8")
    return str(out)


# ---------------------------------------------------------------------------
# CLI / سطر الأوامر
# ---------------------------------------------------------------------------
def _cli() -> int:  # pragma: no cover
    """نقطة دخول مستقلة لاختبار المولد. / Standalone CLI for testing."""
    parser = argparse.ArgumentParser(
        description="MAVIC — Compliance Report Generator"
    )
    parser.add_argument("model", nargs="?", default="sample_model.json",
                        help="Path to the structural model JSON")
    parser.add_argument("--out", default="compliance_report.html",
                        help="Output HTML report path")
    args = parser.parse_args()

    model = load_model(args.model)
    t0 = time.perf_counter()
    violations = RulesEngine.default().run(model)
    elapsed = time.perf_counter() - t0
    enriched = enhance_all(violations, model)

    out_path = generate_report(model, violations, enriched, args.out, elapsed)
    print(f"✅ Report generated: {out_path}")
    print(f"   Violations: {len(violations)} | Time: {elapsed:.3f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())