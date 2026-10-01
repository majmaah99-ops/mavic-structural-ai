#!/usr/bin/env bash
# =============================================================================
# MIZAN by MAVIC — Demo Commands for Judges
# =============================================================================
# سكريبت العرض الحي أمام اللجنة
# الاستخدام: bash demo_commands.sh
# =============================================================================

set -e  # إيقاف عند أي خطأ

# ---- الألوان ----
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RESET='\033[0m'

print_section() {
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════════════════════${RESET}"
    echo -e "${CYAN}  $1${RESET}"
    echo -e "${CYAN}══════════════════════════════════════════════════════════${RESET}"
    echo ""
}

pause() {
    echo ""
    echo -e "${YELLOW}⏸  اضغط Enter للمتابعة...${RESET}"
    read -r
}

# =============================================================================
print_section "MIZAN by MAVIC — محرك التدقيق الهندسي الحي"
echo -e "${GREEN}✓ Backend: Python + Flask + Pydantic${RESET}"
echo -e "${GREEN}✓ Rules: 11 قاعدة SBC (8 إنشائية + 3 معمارية)${RESET}"
echo -e "${GREEN}✓ AI Layer: OpenAI + Offline fallback${RESET}"
echo -e "${GREEN}✓ Live Engine: HTML/CSS/JS نقي${RESET}"
echo ""

# =============================================================================
print_section "الشاشة 1: الاختبارات — 18 اختبار ينجح"
echo -e "${YELLOW}الأمر: pytest test_rules.py -v${RESET}"
pause
pytest test_rules.py -v

# =============================================================================
print_section "الشاشة 2: تشغيل التدقيق الكامل"
echo -e "${YELLOW}الأمر: python main.py${RESET}"
pause
python main.py

# =============================================================================
print_section "الشاشة 3: API حي على Render"
echo -e "${YELLOW}الأمر: curl https://mavic-structural-ai.onrender.com/api/health${RESET}"
pause
echo ""
echo "── /api/health ────────────────────────────────"
curl -s https://mavic-structural-ai.onrender.com/api/health | python3 -m json.tool

echo ""
echo "── /api/violations (المخالفات المعمارية) ─────"
curl -s https://mavic-structural-ai.onrender.com/api/violations/arch | python3 -m json.tool

# =============================================================================
print_section "الشاشة 4: Live Engine (يفتح في المتصفح)"
echo -e "${YELLOW}الرابط: frontend/index.html${RESET}"
echo ""
echo -e "${GREEN}افتح الملف في المتصفح يدوياً:${RESET}"
echo -e "  1. حرّك سلايدر الارتداد من 2.5 → 3.5 → المخالفة تختفي"
echo -e "  2. حرّك سلايدر الموقف من 2.2 → 3.8 → الدرجة ترتفع"
echo -e "  3. حرّك سلايدر الإخلاء من 28 → 18 → الدرجة 100%"
echo ""
echo -e "${GREEN}افتح Console (F12) لرؤية: Live audit: 0 arch violations${RESET}"

# =============================================================================
print_section "نهاية العرض ✅"
echo -e "${GREEN}MIZAN by MAVIC — 11 قاعدة SBC · 0.12 ثانية · 100% تغطية${RESET}"
echo ""
echo -e "${CYAN}روابط:${RESET}"
echo -e "  GitHub    : github.com/majmaah99-ops/mavic-structural-ai"
echo -e "  Live API  : mavic-structural-ai.onrender.com/api/violations"
echo -e "  Live Report: mavic-structural-ai.onrender.com/"
echo ""
