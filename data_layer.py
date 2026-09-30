"""
data_layer.py - طبقة تحميل بيانات النموذج الإنشائي والمعماري
==============================================================

Data access layer for the MIZAN by MAVIC structural + architectural model.

توفر:
    * ``StructuralModel``      : غلاف للوصول إلى مكونات النموذج.
    * ``load_model_from_json`` : تحميل النموذج من ملف JSON.
    * ``load_model_from_dict`` : بناء النموذج من قاموس Python مباشرة.
    * ``load_model_from_revit``: واجهة مستقبلية (غير مُنفَّذة).

Model schema / مخطط البيانات
------------------------------
project       : {name_ar, name_en, city, seismic_zone, stories, ...}

إنشائي / Structural:
columns[]     : id, floor, x, y, width_mm, depth_mm, rebar_ratio, concrete_cover_mm
beams[]       : id, floor, direction, start_column, end_column, span_m,
                width_mm, depth_mm, mid_support, concrete_cover_mm
walls[]       : id, floor, type("shear"|"partition"), direction, length_m, thickness_mm
foundations[] : id, column_id, floor, type, area_m2, load_kN, bearing_capacity_kPa

معماري / Architectural (MIZAN):
buildings[]   : id, floor, setback_rear_m
parking[]     : id, floor, is_accessible, width_m
egress_paths[]: id, floor, max_distance_m
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StructuralModel:
    """
    غلاف حول قاموس النموذج الإنشائي والمعماري.
    Thin wrapper around the model dictionary.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        # ---- Project metadata ----
        self.project: dict[str, Any] = data.get("project", {}) or {}

        # ---- Structural elements (MAVIC) ----
        self.columns: list[dict[str, Any]] = data.get("columns", []) or []
        self.beams: list[dict[str, Any]] = data.get("beams", []) or []
        self.walls: list[dict[str, Any]] = data.get("walls", []) or []
        self.foundations: list[dict[str, Any]] = data.get("foundations", []) or []

        # ---- Architectural elements (MIZAN) ----
        self.buildings: list[dict[str, Any]] = data.get("buildings", []) or []
        self.parking: list[dict[str, Any]] = data.get("parking", []) or []
        self.egress_paths: list[dict[str, Any]] = data.get("egress_paths", []) or []

        self._raw = data

    # ---- Convenience accessors / واجهات وصول سريعة ------------------------
    @property
    def seismic_zone(self) -> int:
        """المنطقة الزلزالية للمشروع. / Project seismic zone."""
        return int(self.project.get("seismic_zone", 1))

    @property
    def floors_count(self) -> int:
        """عدد الطوابق. / Number of stories."""
        return int(self.project.get("stories", 1))

    def element_count(self) -> int:
        """إجمالي عدد العناصر المفحوصة. / Total element count."""
        return (
            len(self.columns)
            + len(self.beams)
            + len(self.walls)
            + len(self.foundations)
            + len(self.buildings)
            + len(self.parking)
            + len(self.egress_paths)
        )

    def to_dict(self) -> dict[str, Any]:
        """إرجاع القاموس الأصلي. / Return the underlying dictionary."""
        return self._raw

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"StructuralModel(city={self.project.get('city', '—')!r}, "
            f"zone={self.seismic_zone}, "
            f"columns={len(self.columns)}, beams={len(self.beams)}, "
            f"walls={len(self.walls)}, foundations={len(self.foundations)}, "
            f"arch_elements={len(self.buildings) + len(self.parking) + len(self.egress_paths)})"
        )


# ---------------------------------------------------------------------------
# Public loaders / دوال التحميل العامة
# ---------------------------------------------------------------------------
def load_model_from_json(json_path: str | Path) -> StructuralModel:
    """
    تحميل النموذج من ملف JSON.
    Load the model from a JSON file.

    Raises:
        FileNotFoundError: إذا لم يكن الملف موجوداً.
        json.JSONDecodeError: إذا كان الملف غير صالح.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return StructuralModel(data)


def load_model_from_dict(data: dict[str, Any]) -> StructuralModel:
    """
    بناء النموذج من قاموس Python مباشرة (مفيد للاختبارات).
    Build the model from a Python dict (useful for tests).
    """
    return StructuralModel(data)


def load_model_from_revit() -> StructuralModel:
    """
    واجهة مستقبلية لتحميل النموذج من Autodesk Revit.
    Placeholder for Revit integration (not implemented in hackathon demo).
    """
    raise NotImplementedError(
        "Revit data loading is only available inside the Revit add-in. "
        "Use load_model_from_json() or load_model_from_dict() instead."
    )


# ---------------------------------------------------------------------------
# CLI helper / مساعد CLI اختياري
# ---------------------------------------------------------------------------
def _main() -> int:  # pragma: no cover
    """عرض سريع للنموذج. / Quick model inspection."""
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_model.json")
    model = load_model_from_json(path)
    print(model)
    print(f"  Seismic zone  : {model.seismic_zone}")
    print(f"  Stories       : {model.floors_count}")
    print(f"  Total elements: {model.element_count()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
