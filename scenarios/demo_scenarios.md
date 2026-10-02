# 🎬 سيناريوهات العرض الحي — MIZAN by MAVIC

**استخدام هذا الملف:** دليل عملي لتشغيل 3 سيناريوهات أمام لجنة التحكيم.

---

## 📋 قبل البدء — قائمة التحقق

- [ ] `python main.py` يعمل محلياً
- [ ] `pytest test_rules.py -v` — 18 اختبار ينجح
- [ ] Chrome مفتوح على تبويب فارغ
- [ ] Terminal في مجلد المشروع
- [ ] `frontend/index.html` مفتوح في تبويب آخر

---

## 🅰️ السيناريو A — نجاح (0 مخالفات، 100% امتثال)

### الهدف
إثبات أن المحرك يعمل على نموذج سليم ولا يعطي نتائج وهمية.

### الأمر
```bash
python main.py --model scenarios/sample_model_clean.json --out docs/clean_report.html
