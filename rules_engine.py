"""
rules_engine.py - محرك قواعد التحقق الهندسي لـ MIZAN by MAVIC
===============================================================

MIZAN by MAVIC structural + architectural rules engine.

الهيكل / Design
---------------
* ``Violation``   : pydantic model describing one finding (bilingual).
* ``Rule``        : abstract base class. Each rule declares ``rule_id``,
                    ``severity``, ``sbc_reference`` and implements ``validate``.
* ``RulesEngine`` : runs a list of rules and returns violations sorted
                    CRITICAL > HIGH > MEDIUM (then by rule_id, then element_id).

11 Rules / القواعد الإحدى عشر:
    إنشائي MAVIC:
        1. OrphanColumnReferenceRule     - SBC 304-18 §7.2
        2. LongSpanWithoutMidSupportRule - SBC 304-18 §9.4
        3. ColumnMinRebarRule            - SBC 301-18 §18.3
        4. ColumnAspectRatioRule         - SBC 304-18 §10.3
        5. FoundationBearingRule         - SBC 303-18 §5.6
        6. BeamMinDepthRule              - SBC 304-18 §9.3
        7. ShearWallCountRule            - SBC 301-18 §12.2
        8. ConcreteCoverRule             - SBC 304-18 §20.5

    معماري MIZAN:
        9.  RearSetbackRule              - SBC 201 §3.2.1
        10. AccessibleParkingRule        - SBC 201 §8.4.3
        11. EgressDistanceRule           - SBC 201 §10.1.5

Requires pydantic v2.
"""
from __future__ import annotations

import json
import math
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, field_validator

Model = dict[str, Any]

SEVERITY_RANK: dict[str, int] = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}


# ============================================================================
# Violation / المخالفة
# ============================================================================
class Violation(BaseModel):
    """نموذج مخالفة واحدة (ثنائي اللغة). / One finding (bilingual)."""

    rule_id: int
    severity: str
    element_id: str
    element_type: str
    message_ar: str
    message_en: str
    sbc_reference: str
    suggested_fix_ar: str
    suggested_fix_en: str

    @field_validator("severity")
    @classmethod
    def _severity_must_be_known(cls, value: str) -> str:
        if value not in SEVERITY_RANK:
            raise ValueError(
                f"severity must be one of {sorted(SEVERITY_RANK)}, got {value!r}"
            )
        return value


# ============================================================================
# Helpers / مساعدات
# ============================================================================
def _seismic_zone(model: Model) -> int:
    """قراءة المنطقة الزلزالية من النموذج. / Read seismic zone."""
    return int(model.get("project", {}).get("seismic_zone", 1))


def _require(element: dict[str, Any], key: str, kind: str) -> Any:
    """إفشال صريح عند غياب حقل إلزامي. / Fail loudly on missing mandatory field."""
    if element.get(key) is None:
        raise ValueError(
            f"{kind} {element.get('id', '?')}: missing required field '{key}'"
        )
    return element[key]


def _location_of_missing_end(
    beam: dict[str, Any], columns: dict[str, dict[str, Any]]
):
    """تقدير (x, y) لنهاية جسر مفقودة. / Estimate (x, y) of a missing beam end."""
    start = columns.get(beam.get("start_column"))
    end = columns.get(beam.get("end_column"))
    span = float(beam.get("span_m", 0))
    if start and not end:
        x, y, sign = float(start["x"]), float(start["y"]), 1
    elif end and not start:
        x, y, sign = float(end["x"]), float(end["y"]), -1
    else:
        return None
    if str(beam.get("direction", "X")).upper() == "X":
        x += sign * span
    else:
        y += sign * span
    return round(x, 2), round(y, 2)


# ============================================================================
# Rule base class / الفئة الأساسية للقواعد
# ============================================================================
class Rule(ABC):
    """فئة مجردة لكل قاعدة. / Abstract base class for every rule."""

    rule_id: ClassVar[int]
    severity: ClassVar[str]
    sbc_reference: ClassVar[str]

    def __init__(self) -> None:
        for attr in ("rule_id", "severity", "sbc_reference"):
            if not hasattr(type(self), attr):
                raise TypeError(
                    f"{type(self).__name__} must define class attribute '{attr}'"
                )

    @abstractmethod
    def validate(self, model: Model) -> list[Violation]:
        """إرجاع كل مخالفات هذه القاعدة. / Return every violation of this rule."""

    # ---- Message builders (enforce the engineering template) --------------
    @staticmethod
    def msg_ar(
        etype: str, eid: str, floor: Any, issue: str, actual: str, required: str
    ) -> str:
        return (
            f"{etype} {eid} في الطابق {floor}: {issue} "
            f"— القيمة الفعلية {actual}، الحد المطلوب {required}."
        )

    @staticmethod
    def msg_en(
        etype: str, eid: str, floor: Any, issue: str, actual: str, required: str
    ) -> str:
        return (
            f"{etype} {eid} on floor {floor}: {issue} "
            f"— actual {actual}, required {required}."
        )

    def make(
        self,
        element_id: str,
        element_type: str,
        message_ar: str,
        message_en: str,
        fix_ar: str,
        fix_en: str,
    ) -> Violation:
        return Violation(
            rule_id=self.rule_id,
            severity=self.severity,
            element_id=element_id,
            element_type=element_type,
            message_ar=message_ar,
            message_en=message_en,
            sbc_reference=self.sbc_reference,
            suggested_fix_ar=fix_ar,
            suggested_fix_en=fix_en,
        )


# ============================================================================
# STRUCTURAL RULES (MAVIC) — 8 قواعد إنشائية
# ============================================================================

class OrphanColumnReferenceRule(Rule):
    """Rule 1 - كل جسر يجب أن يتصل بأعمدة موجودة في النموذج."""

    rule_id = 1
    severity = "CRITICAL"
    sbc_reference = "SBC 304-18 §7.2 (load path continuity)"

    def validate(self, model: Model) -> list[Violation]:
        columns = {c["id"]: c for c in model.get("columns", [])}
        out: list[Violation] = []
        for beam in model.get("beams", []):
            refs = (beam.get("start_column"), beam.get("end_column"))
            orphans = [str(r) for r in refs if r not in columns]
            if not orphans:
                continue
            orphan_txt = "، ".join(orphans)
            floor = beam.get("floor", 1)
            loc = _location_of_missing_end(beam, columns)
            if loc:
                fix_ar = (
                    f"أضف عموداً في الموقع (X={loc[0]}, Y={loc[1]}) بالطابق {floor}، "
                    f"أو أعد توصيل العارضة بعمود موجود."
                )
                fix_en = (
                    f"Add a column at (X={loc[0]}, Y={loc[1]}) on floor {floor}, "
                    f"or reconnect the beam to an existing column."
                )
            else:
                fix_ar = (
                    f"أضف الأعمدة المفقودة ({orphan_txt}) بالطابق {floor}، "
                    f"أو أعد توصيل العارضة بأعمدة موجودة."
                )
                fix_en = (
                    f"Add the missing column(s) ({', '.join(orphans)}) on floor {floor}, "
                    f"or reconnect the beam to existing columns."
                )
            out.append(self.make(
                beam["id"], "العارضة",
                self.msg_ar("العارضة", beam["id"], floor,
                            "مرتبطة بعمود غير موجود في النموذج",
                            f"مرجع {orphan_txt}", "مرجع لعمود إنشائي معرَّف"),
                self.msg_en("Beam", beam["id"], floor,
                            "references a column that does not exist in the model",
                            f"reference {', '.join(orphans)}",
                            "reference to a defined structural column"),
                fix_ar, fix_en,
            ))
        return out


class LongSpanWithoutMidSupportRule(Rule):
    """Rule 2 - بحر الجسر > 12م يتطلب دعامة وسطية."""

    rule_id = 2
    severity = "HIGH"
    sbc_reference = "SBC 304-18 §9.4 (span/deflection control)"
    MAX_SPAN_M = 12.0

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for beam in model.get("beams", []):
            span = float(_require(beam, "span_m", "Beam"))
            if span <= self.MAX_SPAN_M or beam.get("mid_support", False):
                continue
            floor = beam.get("floor", 1)
            out.append(self.make(
                beam["id"], "العارضة",
                self.msg_ar("العارضة", beam["id"], floor,
                            "بحر يتجاوز 12 م دون دعامة وسطية",
                            f"{span:.1f} م",
                            f"≤ {self.MAX_SPAN_M:.1f} م أو وجود دعامة وسطية"),
                self.msg_en("Beam", beam["id"], floor,
                            "span exceeds 12 m with no intermediate support",
                            f"{span:.1f} m",
                            f"≤ {self.MAX_SPAN_M:.1f} m or an intermediate support"),
                f"أضف عموداً أو جدار قص كدعامة وسطية عند منتصف العارضة "
                f"(على بعد {span / 2:.2f} م من العمود "
                f"{beam.get('start_column', '-')})، أو قلّص البحر إلى "
                f"{self.MAX_SPAN_M:.0f} م أو أقل.",
                f"Add a column or shear wall as a mid-span support "
                f"({span / 2:.2f} m from column {beam.get('start_column', '-')}), "
                f"or reduce the span to {self.MAX_SPAN_M:.0f} m or less.",
            ))
        return out


class ColumnMinRebarRule(Rule):
    """Rule 3 - نسبة التسليح الدنيا للأعمدة في المناطق الزلزالية."""

    rule_id = 3
    severity = "CRITICAL"
    sbc_reference = "SBC 301-18 §18.3"
    MIN_RATIO = 0.010

    def validate(self, model: Model) -> list[Violation]:
        zone = _seismic_zone(model)
        out: list[Violation] = []
        for col in model.get("columns", []):
            ratio = float(_require(col, "rebar_ratio", "Column"))
            if ratio >= self.MIN_RATIO:
                continue
            floor = col.get("floor", 1)
            out.append(self.make(
                col["id"], "العمود",
                self.msg_ar("العمود", col["id"], floor,
                            f"نسبة تسليح أقل من الحد الأدنى للمنطقة الزلزالية {zone}",
                            f"{ratio:.3f}", f"{self.MIN_RATIO:.3f}"),
                self.msg_en("Column", col["id"], floor,
                            f"rebar ratio below the minimum for seismic zone {zone}",
                            f"{ratio:.3f}", f"{self.MIN_RATIO:.3f}"),
                f"ارفع نسبة التسليح إلى {self.MIN_RATIO:.3f} على الأقل لاستيفاء "
                f"{self.sbc_reference} للمنطقة {zone}.",
                f"Increase the rebar ratio to at least {self.MIN_RATIO:.3f} to satisfy "
                f"{self.sbc_reference} for zone {zone}.",
            ))
        return out


class ColumnAspectRatioRule(Rule):
    """Rule 4 - نسبة البعد الأقصر إلى الأطول في العمود ≥ 0.4."""

    rule_id = 4
    severity = "HIGH"
    sbc_reference = "SBC 304-18 §10.3 (column cross-section ratio)"
    MIN_RATIO = 0.4

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for col in model.get("columns", []):
            w = float(col["width_mm"])
            d = float(col["depth_mm"])
            short, long_ = min(w, d), max(w, d)
            ratio = short / long_
            if ratio >= self.MIN_RATIO:
                continue
            floor = col.get("floor", 1)
            min_short = math.ceil(self.MIN_RATIO * long_ / 10) * 10
            out.append(self.make(
                col["id"], "العمود",
                self.msg_ar("العمود", col["id"], floor,
                            "نسبة العرض إلى العمق أقل من الحد الأدنى",
                            f"{ratio:.3f} ({w:g}×{d:g} مم)",
                            f"{self.MIN_RATIO:.3f}"),
                self.msg_en("Column", col["id"], floor,
                            "width/depth ratio below the minimum",
                            f"{ratio:.3f} ({w:g}x{d:g} mm)",
                            f"{self.MIN_RATIO:.3f}"),
                f"زد البعد الأقصر إلى {min_short} مم على الأقل "
                f"(مع بقاء البعد الأطول {long_:g} مم) لتصبح النسبة "
                f"{self.MIN_RATIO:.2f} أو أكثر.",
                f"Increase the shorter side to at least {min_short} mm "
                f"(longer side {long_:g} mm) so the ratio is "
                f"{self.MIN_RATIO:.2f} or more.",
            ))
        return out


class FoundationBearingRule(Rule):
    """Rule 5 - إجهاد التربة المطبق يجب ألا يتجاوز قدرة التحمل."""

    rule_id = 5
    severity = "CRITICAL"
    sbc_reference = "SBC 303-18 §5.6 (foundation bearing capacity)"

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for f in model.get("foundations", []):
            area = float(_require(f, "area_m2", "Foundation"))
            load = float(_require(f, "load_kN", "Foundation"))
            cap = float(_require(f, "bearing_capacity_kPa", "Foundation"))
            pressure = load / area
            if pressure <= cap:
                continue
            floor = f.get("floor", 0)
            req_area = math.ceil(load / cap * 10) / 10
            out.append(self.make(
                f["id"], "الأساس",
                self.msg_ar("الأساس", f["id"], floor,
                            "إجهاد التربة المطبق يتجاوز قدرة التحمل",
                            f"{pressure:.1f} kPa", f"≤ {cap:.1f} kPa"),
                self.msg_en("Foundation", f["id"], floor,
                            "applied soil pressure exceeds bearing capacity",
                            f"{pressure:.1f} kPa", f"≤ {cap:.1f} kPa"),
                f"زد مساحة القاعدة من {area:.1f} م² إلى {req_area:.1f} م² على الأقل، "
                f"أو اختر نوع أساس أعمق (مثل الخوازيق) لتحمل الحمل {load:.0f} kN.",
                f"Increase the footing area from {area:.1f} m² to at least "
                f"{req_area:.1f} m², or choose a deeper foundation type (e.g. piles) "
                f"to carry the {load:.0f} kN load.",
            ))
        return out


class BeamMinDepthRule(Rule):
    """Rule 6 - عمق الجسر الأدنى h ≥ span / 16."""

    rule_id = 6
    severity = "MEDIUM"
    sbc_reference = "SBC 304-18 §9.3 (minimum beam depth)"
    SPAN_DEPTH_DIVISOR = 16

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for beam in model.get("beams", []):
            span = float(_require(beam, "span_m", "Beam"))
            depth = float(_require(beam, "depth_mm", "Beam"))
            required = math.ceil(round(span * 1000 / self.SPAN_DEPTH_DIVISOR, 6))
            if depth >= required:
                continue
            floor = beam.get("floor", 1)
            out.append(self.make(
                beam["id"], "العارضة",
                self.msg_ar("العارضة", beam["id"], floor,
                            "عمق العارضة أقل من الحد الأدنى (البحر/16)",
                            f"{depth:g} مم", f"{required} مم"),
                self.msg_en("Beam", beam["id"], floor,
                            "beam depth below the minimum (span/16)",
                            f"{depth:g} mm", f"{required} mm"),
                f"زد عمق العارضة إلى {required} مم على الأقل (بحر {span:.1f} م)، "
                f"أو أضف دعامة لتقليص البحر.",
                f"Increase the beam depth to at least {required} mm (span {span:.1f} m), "
                f"or add a support to shorten the span.",
            ))
        return out


class ShearWallCountRule(Rule):
    """Rule 7 - على الأقل جدارا قص في كل اتجاه رئيسي لكل طابق."""

    rule_id = 7
    severity = "HIGH"
    sbc_reference = "SBC 301-18 §12.2 (seismic lateral force-resisting system)"
    MIN_WALLS = 2
    DIRECTIONS = ("X", "Y")

    def validate(self, model: Model) -> list[Violation]:
        zone = _seismic_zone(model)
        floors = sorted({c.get("floor", 1) for c in model.get("columns", [])})
        out: list[Violation] = []
        for floor in floors:
            for direction in self.DIRECTIONS:
                count = sum(
                    1 for w in model.get("walls", [])
                    if w.get("floor") == floor
                    and w.get("type") == "shear"
                    and str(w.get("direction", "")).upper() == direction
                )
                if count >= self.MIN_WALLS:
                    continue
                eid = f"LFRS-F{floor}-{direction}"
                missing = self.MIN_WALLS - count
                out.append(self.make(
                    eid, "نظام مقاومة القوى الجانبية",
                    self.msg_ar("نظام مقاومة القوى الجانبية", eid, floor,
                                f"عدد جدران القص في الاتجاه {direction} أقل من الحد الأدنى "
                                f"للمنطقة الزلزالية {zone}",
                                str(count), str(self.MIN_WALLS)),
                    self.msg_en("Lateral system", eid, floor,
                                f"shear-wall count in direction {direction} below the "
                                f"minimum for seismic zone {zone}",
                                str(count), str(self.MIN_WALLS)),
                    f"أضف {missing} جدار قص على الأقل في الاتجاه {direction} "
                    f"بالطابق {floor}، موزعة على جانبي مركز الكتلة لتقليل الالتواء.",
                    f"Add at least {missing} shear wall(s) in direction {direction} "
                    f"on floor {floor}, placed on both sides of the centre of mass "
                    f"to limit torsion.",
                ))
        return out


class ConcreteCoverRule(Rule):
    """Rule 8 - الغطاء الخرساني الأدنى 40 مم للأعمدة والجسور."""

    rule_id = 8
    severity = "MEDIUM"
    sbc_reference = "SBC 304-18 §20.5 (concrete cover)"
    MIN_COVER_MM = 40

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for key, ar, en in (
            ("columns", "العمود", "Column"),
            ("beams", "العارضة", "Beam"),
        ):
            for el in model.get(key, []):
                cover = float(_require(el, "concrete_cover_mm", en))
                if cover >= self.MIN_COVER_MM:
                    continue
                floor = el.get("floor", 1)
                out.append(self.make(
                    el["id"], ar,
                    self.msg_ar(ar, el["id"], floor,
                                "الغطاء الخرساني أقل من الحد الأدنى",
                                f"{cover:g} مم", f"{self.MIN_COVER_MM} مم"),
                    self.msg_en(en, el["id"], floor,
                                "concrete cover below the minimum",
                                f"{cover:g} mm", f"{self.MIN_COVER_MM} mm"),
                    f"زد الغطاء الخرساني إلى {self.MIN_COVER_MM} مم على الأقل "
                    f"(استخدم فواصل تسليح مناسبة وراجع أبعاد القالب).",
                    f"Increase the concrete cover to at least {self.MIN_COVER_MM} mm "
                    f"(use proper spacers and check the formwork dimensions).",
                ))
        return out


# ============================================================================
# ARCHITECTURAL RULES (MIZAN) — 3 قواعد معمارية
# ============================================================================

class RearSetbackRule(Rule):
    """Rule 9 - الارتداد الخلفي ≥ 3.0 م (SBC 201 §3.2.1)."""

    rule_id = 9
    severity = "HIGH"
    sbc_reference = "SBC 201 §3.2.1 (rear setback)"
    MIN_SETBACK_M = 3.0

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for b in model.get("buildings", []):
            actual = float(b.get("setback_rear_m", 0))
            if actual >= self.MIN_SETBACK_M:
                continue
            floor = b.get("floor", 1)
            out.append(self.make(
                b["id"], "المبنى",
                self.msg_ar("المبنى", b["id"], floor,
                            "الارتداد الخلفي أقل من الحد الأدنى",
                            f"{actual:.2f} م", f"{self.MIN_SETBACK_M:.2f} م"),
                self.msg_en("Building", b["id"], floor,
                            "rear setback below minimum",
                            f"{actual:.2f} m", f"{self.MIN_SETBACK_M:.2f} m"),
                f"أزح الجدار الخلفي للداخل بمقدار "
                f"{self.MIN_SETBACK_M - actual:.2f} م ليصبح الارتداد "
                f"{self.MIN_SETBACK_M:.2f} م على الأقل، أو قدّم طلب استثناء بلدي.",
                f"Move the rear wall inward by {self.MIN_SETBACK_M - actual:.2f} m "
                f"so the setback is at least {self.MIN_SETBACK_M:.2f} m, "
                f"or file a municipal waiver.",
            ))
        return out


class AccessibleParkingRule(Rule):
    """Rule 10 - عرض موقف ذوي الإعاقة ≥ 3.6 م (SBC 201 §8.4.3)."""

    rule_id = 10
    severity = "HIGH"
    sbc_reference = "SBC 201 §8.4.3 (accessible parking)"
    MIN_WIDTH_M = 3.6

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for p in model.get("parking", []):
            if not p.get("is_accessible", False):
                continue
            width = float(p.get("width_m", 0))
            if width >= self.MIN_WIDTH_M:
                continue
            floor = p.get("floor", 0)
            out.append(self.make(
                p["id"], "موقف سيارات",
                self.msg_ar("موقف سيارات", p["id"], floor,
                            "عرض موقف ذوي الإعاقة أقل من الحد الأدنى",
                            f"{width:.2f} م", f"{self.MIN_WIDTH_M:.2f} م"),
                self.msg_en("Parking", p["id"], floor,
                            "accessible parking width below minimum",
                            f"{width:.2f} m", f"{self.MIN_WIDTH_M:.2f} m"),
                f"وسّع الموقف إلى {self.MIN_WIDTH_M:.2f} م على الأقل وأضف "
                f"ممر وصول بعرض 1.2 م مجاور، مع تمييز الموقف بعلامات أرضية "
                f"ولوحات إرشادية.",
                f"Widen the space to at least {self.MIN_WIDTH_M:.2f} m, add an "
                f"adjacent 1.2 m access aisle, and mark the space with floor "
                f"signs and signage.",
            ))
        return out


class EgressDistanceRule(Rule):
    """Rule 11 - مسافة الإخلاء ≤ 20 م (SBC 201 §10.1.5)."""

    rule_id = 11
    severity = "CRITICAL"
    sbc_reference = "SBC 201 §10.1.5 (egress travel distance)"
    MAX_DISTANCE_M = 20.0

    def validate(self, model: Model) -> list[Violation]:
        out: list[Violation] = []
        for e in model.get("egress_paths", []):
            dist = float(e.get("max_distance_m", 0))
            if dist <= self.MAX_DISTANCE_M:
                continue
            floor = e.get("floor", 1)
            out.append(self.make(
                e["id"], "مسار إخلاء",
                self.msg_ar("مسار إخلاء", e["id"], floor,
                            "مسافة الوصول لمخرج الطوارئ تتجاوز الحد المسموح",
                            f"{dist:.1f} م", f"≤ {self.MAX_DISTANCE_M:.1f} م"),
                self.msg_en("Egress path", e["id"], floor,
                            "egress travel distance exceeds maximum",
                            f"{dist:.1f} m", f"≤ {self.MAX_DISTANCE_M:.1f} m"),
                f"أضف مخرج طوارئ ثانوي في الجدار الأقرب لتقليل المسافة إلى "
                f"{self.MAX_DISTANCE_M:.0f} م أو أقل، مع إضاءة طوارئ وعلامات مضيئة.",
                f"Add a secondary emergency exit on the nearest wall to reduce "
                f"the travel distance to {self.MAX_DISTANCE_M:.0f} m or less, "
                f"with emergency lighting and signage.",
            ))
        return out


# ============================================================================
# Engine / المحرك
# ============================================================================
class RulesEngine:
    """محرك يشغّل كل القواعد ويعيد النتائج مرتبة. / Runs rules and sorts results."""

    def __init__(self, rules: list[Rule]) -> None:
        self.rules = list(rules)

    @classmethod
    def default(cls) -> "RulesEngine":
        """المحرك الافتراضي بـ 11 قاعدة. / Default engine with 11 rules."""
        return cls([
            # إنشائي MAVIC — 8 قواعد
            OrphanColumnReferenceRule(),
            LongSpanWithoutMidSupportRule(),
            ColumnMinRebarRule(),
            ColumnAspectRatioRule(),
            FoundationBearingRule(),
            BeamMinDepthRule(),
            ShearWallCountRule(),
            ConcreteCoverRule(),
            # معماري MIZAN — 3 قواعد
            RearSetbackRule(),
            AccessibleParkingRule(),
            EgressDistanceRule(),
        ])

    def run(self, model: Model) -> list[Violation]:
        """تشغيل كل القواعد وإرجاع مخالفات مرتبة."""
        violations: list[Violation] = []
        for rule in self.rules:
            violations.extend(rule.validate(model))
        return sorted(
            violations,
            key=lambda v: (SEVERITY_RANK[v.severity], v.rule_id, v.element_id),
        )


# ============================================================================
# Helpers / مساعدات
# ============================================================================
def load_model(path: str | Path) -> Model:
    """تحميل النموذج من JSON. / Load model from JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """CLI: تشغيل التدقيق وطباعة النتائج. / CLI: run audit and print."""
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else Path(__file__).with_name("sample_model.json")
    violations = RulesEngine.default().run(load_model(path))
    counts = {s: sum(v.severity == s for v in violations) for s in SEVERITY_RANK}
    print(f"Violations: {len(violations)}  "
          + "  ".join(f"{s}={n}" for s, n in counts.items()))
    for v in violations:
        print(f"[{v.severity}] R{v.rule_id} {v.element_id}")
        print(f"  {v.message_ar}")
        print(f"  → {v.suggested_fix_ar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
