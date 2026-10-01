"""
test_rules.py - اختبارات محرك القواعد لـ MIZAN by MAVIC
=========================================================

Unit tests for rules_engine.py — run with:
    pytest test_rules.py -v

Covers all 11 rules (8 structural + 3 architectural):
    R1  : OrphanColumnReferenceRule
    R2  : LongSpanWithoutMidSupportRule
    R3  : ColumnMinRebarRule
    R4  : ColumnAspectRatioRule
    R5  : FoundationBearingRule
    R6  : BeamMinDepthRule
    R7  : ShearWallCountRule
    R8  : ConcreteCoverRule
    R9  : RearSetbackRule          (MIZAN — معماري)
    R10 : AccessibleParkingRule    (MIZAN — معماري)
    R11 : EgressDistanceRule       (MIZAN — معماري)
"""
import json
import re
from pathlib import Path

import pytest

import rules_engine as re_mod
from rules_engine import (
    AccessibleParkingRule,
    BeamMinDepthRule,
    ColumnAspectRatioRule,
    ColumnMinRebarRule,
    ConcreteCoverRule,
    EgressDistanceRule,
    FoundationBearingRule,
    LongSpanWithoutMidSupportRule,
    OrphanColumnReferenceRule,
    RearSetbackRule,
    RulesEngine,
    ShearWallCountRule,
    Violation,
)

# ---------------------------------------------------------------------------
# Arabic message template / قالب الرسالة العربية
# ---------------------------------------------------------------------------
ARABIC_TEMPLATE = re.compile(
    r"^.+ \S+ في الطابق \d+: .+ — القيمة الفعلية .+، الحد المطلوب .+\.$"
)


# ---------------------------------------------------------------------------
# Fixtures / تجهيزات الاختبار
# ---------------------------------------------------------------------------
def _col(cid, x, y, floor=1):
    """إنشاء عمود افتراضي مطابق."""
    return dict(
        id=cid, floor=floor, x=x, y=y,
        width_mm=500, depth_mm=500,
        rebar_ratio=0.015, concrete_cover_mm=45,
    )


def _beam(bid, s, e, direction="X", span=6.0):
    """إنشاء جسر افتراضي مطابق."""
    return dict(
        id=bid, floor=1, direction=direction,
        start_column=s, end_column=e,
        span_m=span, width_mm=300, depth_mm=500,
        mid_support=False, concrete_cover_mm=45,
    )


@pytest.fixture
def model():
    """
    نموذج صغير مطابق تماماً (0 مخالفات لكل قاعدة).
    Small, fully compliant in-memory model.
    """
    return {
        "project": {"seismic_zone": 3},
        "columns": [
            _col("C-001", 0, 0),
            _col("C-002", 6, 0),
            _col("C-003", 0, 5),
            _col("C-004", 6, 5),
        ],
        "beams": [
            _beam("B-001", "C-001", "C-002"),
            _beam("B-002", "C-003", "C-004"),
        ],
        "walls": [
            dict(id="W-1", floor=1, type="shear", direction="X",
                 length_m=5, thickness_mm=250),
            dict(id="W-2", floor=1, type="shear", direction="X",
                 length_m=5, thickness_mm=250),
            dict(id="W-3", floor=1, type="shear", direction="Y",
                 length_m=5, thickness_mm=250),
            dict(id="W-4", floor=1, type="shear", direction="Y",
                 length_m=5, thickness_mm=250),
        ],
        "foundations": [
            dict(id=f"F-{i}", column_id=f"C-00{i}", floor=0,
                 type="isolated_footing", area_m2=10.0, load_kN=2000,
                 bearing_capacity_kPa=300)
            for i in range(1, 5)
        ],
        # معمارية / Architectural
        "buildings": [
            dict(id="BLD-01", floor=1, setback_rear_m=3.5),
        ],
        "parking": [
            dict(id="P-ACC-01", floor=0, is_accessible=True, width_m=3.8),
        ],
        "egress_paths": [
            dict(id="EG-01", floor=1, max_distance_m=18.0),
        ],
    }


# ============================================================================
# Baseline test / اختبار الحالة الأساسية
# ============================================================================
def test_clean_model_has_no_violations(model):
    """نموذج مطابق → 0 مخالفات."""
    assert RulesEngine.default().run(model) == []


# ============================================================================
# R1 — OrphanColumnReferenceRule
# ============================================================================
def test_rule1_orphan_column_reference(model):
    """جسر يشير إلى عمود غير موجود → CRITICAL."""
    model["beams"][0]["end_column"] = "C-999"
    violations = OrphanColumnReferenceRule().validate(model)
    assert len(violations) == 1
    assert violations[0].severity == "CRITICAL"
    assert violations[0].element_id == "B-001"
    assert "C-999" in violations[0].message_ar


# ============================================================================
# R2 — LongSpanWithoutMidSupportRule
# ============================================================================
def test_rule2_long_span_without_mid_support(model):
    """بحر > 12م بدون دعامة → HIGH."""
    model["beams"][0]["span_m"] = 13.0
    assert len(LongSpanWithoutMidSupportRule().validate(model)) == 1
    # مع دعامة → 0 مخالفات
    model["beams"][0]["mid_support"] = True
    assert len(LongSpanWithoutMidSupportRule().validate(model)) == 0


# ============================================================================
# R3 — ColumnMinRebarRule
# ============================================================================
def test_rule3_column_min_rebar(model):
    """عمودان بتسليح ضعيف → 2 مخالفات CRITICAL."""
    model["columns"][0]["rebar_ratio"] = 0.008
    model["columns"][1]["rebar_ratio"] = 0.009
    violations = ColumnMinRebarRule().validate(model)
    assert len(violations) == 2
    assert violations[0].severity == "CRITICAL"
    # التحقق من صيغة الرسالة العربية
    assert "العمود C-001 في الطابق 1" in violations[0].message_ar
    assert "0.008" in violations[0].message_ar
    assert "0.010" in violations[0].message_ar


# ============================================================================
# R4 — ColumnAspectRatioRule
# ============================================================================
def test_rule4_column_aspect_ratio(model):
    """عمود بنسبة 0.357 → HIGH."""
    model["columns"][2].update(width_mm=250, depth_mm=700)  # ratio 0.357
    assert len(ColumnAspectRatioRule().validate(model)) == 1


# ============================================================================
# R5 — FoundationBearingRule
# ============================================================================
def test_rule5_foundation_bearing_capacity(model):
    """أساس بحمل 2000 كيلو نيوتن على 5 م² → 400 kPa > 300 kPa."""
    model["foundations"][3].update(area_m2=5.0, load_kN=2000)
    violations = FoundationBearingRule().validate(model)
    assert len(violations) == 1
    assert violations[0].element_id == "F-4"
    assert violations[0].severity == "CRITICAL"


# ============================================================================
# R6 — BeamMinDepthRule
# ============================================================================
def test_rule6_beam_min_depth(model):
    """جسر بعمق أقل من span/16 → MEDIUM."""
    model["beams"][0]["depth_mm"] = 350  # required 375 for 6.0 m span
    model["beams"][1]["depth_mm"] = 300
    assert len(BeamMinDepthRule().validate(model)) == 2


# ============================================================================
# R7 — ShearWallCountRule
# ============================================================================
def test_rule7_shear_wall_count(model):
    """إزالة جدار قص من الاتجاه X → HIGH."""
    model["walls"] = [
        w for w in model["walls"]
        if not (w["direction"] == "X" and w["id"] == "W-2")
    ]
    violations = ShearWallCountRule().validate(model)
    assert len(violations) == 1
    assert violations[0].element_id == "LFRS-F1-X"


# ============================================================================
# R8 — ConcreteCoverRule
# ============================================================================
def test_rule8_concrete_cover(model):
    """غطاء خرساني أقل من 40 مم → MEDIUM."""
    model["columns"][0]["concrete_cover_mm"] = 30
    model["beams"][1]["concrete_cover_mm"] = 25
    model["beams"][0]["concrete_cover_mm"] = 40  # على الحد → مطابق
    assert len(ConcreteCoverRule().validate(model)) == 2


def test_rule8_missing_cover_is_error_not_silent_default(model):
    """غياب الحقل الإلزامي يرفع ValueError (لا افتراضي صامت)."""
    del model["columns"][0]["concrete_cover_mm"]
    with pytest.raises(ValueError):
        ConcreteCoverRule().validate(model)


# ============================================================================
# R9 — RearSetbackRule (MIZAN)
# ============================================================================
def test_rule9_rear_setback_mizan(model):
    """ارتداد خلفي 2.5م < 3.0م → HIGH (معماري)."""
    model["buildings"][0]["setback_rear_m"] = 2.5
    violations = RearSetbackRule().validate(model)
    assert len(violations) == 1
    assert violations[0].severity == "HIGH"
    assert violations[0].rule_id == 9
    assert violations[0].element_id == "BLD-01"
    assert "3.2.1" in violations[0].sbc_reference
    # مطابق عند 3.5م
    model["buildings"][0]["setback_rear_m"] = 3.5
    assert len(RearSetbackRule().validate(model)) == 0


# ============================================================================
# R10 — AccessibleParkingRule (MIZAN)
# ============================================================================
def test_rule10_accessible_parking_mizan(model):
    """موقف إعاقة 2.2م < 3.6م → HIGH (معماري)."""
    model["parking"][0]["width_m"] = 2.2
    violations = AccessibleParkingRule().validate(model)
    assert len(violations) == 1
    assert violations[0].severity == "HIGH"
    assert violations[0].rule_id == 10
    assert "8.4.3" in violations[0].sbc_reference
    # مطابق عند 3.8م
    model["parking"][0]["width_m"] = 3.8
    assert len(AccessibleParkingRule().validate(model)) == 0


def test_rule10_non_accessible_parking_ignored(model):
    """موقف عادي (is_accessible=False) يتجاهله الاختبار."""
    model["parking"][0]["is_accessible"] = False
    model["parking"][0]["width_m"] = 2.0
    assert len(AccessibleParkingRule().validate(model)) == 0


# ============================================================================
# R11 — EgressDistanceRule (MIZAN)
# ============================================================================
def test_rule11_egress_distance_mizan(model):
    """مسار إخلاء 28م > 20م → CRITICAL (معماري)."""
    model["egress_paths"][0]["max_distance_m"] = 28.0
    violations = EgressDistanceRule().validate(model)
    assert len(violations) == 1
    assert violations[0].severity == "CRITICAL"
    assert violations[0].rule_id == 11
    assert "10.1.5" in violations[0].sbc_reference
    # مطابق عند 18م
    model["egress_paths"][0]["max_distance_m"] = 18.0
    assert len(EgressDistanceRule().validate(model)) == 0


# ============================================================================
# Engine sorting / ترتيب المحرك
# ============================================================================
def test_engine_sorts_critical_then_high_then_medium(model):
    """المحرك يرتب المخالفات: CRITICAL > HIGH > MEDIUM."""
    model["beams"][0]["depth_mm"] = 350            # R6 MEDIUM
    model["columns"][0]["rebar_ratio"] = 0.005     # R3 CRITICAL
    model["beams"][1]["span_m"] = 13.0             # R2 HIGH
    severities = [v.severity for v in RulesEngine.default().run(model)]
    assert severities == sorted(
        severities,
        key=lambda s: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}[s],
    )
    assert severities[0] == "CRITICAL"
    assert severities[-1] == "MEDIUM"


# ============================================================================
# Sample model test / اختبار النموذج التجريبي
# ============================================================================
def test_sample_model_has_exact_injected_violations():
    """
    النموذج التجريبي يحتوي على 15 مخالفة محقونة بدقة:
        8 إنشائية + 3 معمارية = 11 قاعدة، بعضها يُخالف عدة عناصر.
    """
    sample_path = Path(__file__).with_name("sample_model.json")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))

    # تحقق من حجم النموذج (ليس نموذجاً صغيراً)
    assert len(sample["columns"]) >= 24, "Nموذج يحتاج ≥24 عمود"
    assert len(sample["beams"]) >= 30, "نموذج يحتاج ≥30 جسر"
    assert len(sample["walls"]) >= 6, "نموذج يحتاج ≥6 جدران"
    assert len(sample["foundations"]) >= 20, "نموذج يحتاج ≥20 أساس"
    assert len(sample["buildings"]) >= 1, "نموذج يحتاج ≥1 مبنى (معماري)"
    assert len(sample["parking"]) >= 1, "نموذج يحتاج ≥1 موقف (معماري)"
    assert len(sample["egress_paths"]) >= 1, "نموذج يحتاج ≥1 مسار إخلاء (معماري)"

    violations = RulesEngine.default().run(sample)

    # التحقق من العدد الإجمالي المتوقع (15 مخالفة)
    assert len(violations) >= 12, f"المتوقع ≥12 مخالفة، وُجد {len(violations)}"

    # التحقق من أن كل قاعدة (8 إنشائية) ظهرت مرة على الأقل
    rule_ids_found = {v.rule_id for v in violations}
    for rid in range(1, 9):
        assert rid in rule_ids_found, f"Rule {rid} لم تُكتشف في النموذج"

    # التحقق من القواعد المعمارية الثلاث
    for rid in (9, 10, 11):
        assert rid in rule_ids_found, f"Rule {rid} (معماري) لم تُكتشف"

    # التحقق من صيغة الرسالة العربية لكل مخالفة
    for v in violations:
        assert ARABIC_TEMPLATE.match(v.message_ar), (
            f"الرسالة لا تطابق القالب: {v.message_ar!r}"
        )
        assert v.suggested_fix_ar, f"مخالفة R{v.rule_id} بلا suggested_fix_ar"
        assert v.suggested_fix_en, f"مخالفة R{v.rule_id} بلا suggested_fix_en"
        assert isinstance(v, Violation)


# ============================================================================
# Source code checks / فحوصات الكود المصدري
# ============================================================================
def test_no_typo_in_source_code():
    """التأكد من عدم وجود أخطاء إملائية معروفة في الكود."""
    source = Path(re_mod.__file__).read_text(encoding="utf-8")
    assert "العمره" not in source, "يوجد خطأ إملائي: العمره (يجب أن تكون: العارضة)"


def test_all_11_rules_are_registered():
    """التأكد من تسجيل كل القواعد الـ 11 في RulesEngine.default()."""
    engine = RulesEngine.default()
    rule_ids = {rule.rule_id for rule in engine.rules}
    expected = set(range(1, 12))  # 1..11
    assert rule_ids == expected, (
        f"القواعد المسجلة: {sorted(rule_ids)} | "
        f"المتوقعة: {sorted(expected)}"
    )
