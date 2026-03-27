import os
import re
import time

from flask import Blueprint, render_template, redirect, url_for, session, request, flash
from werkzeug.utils import secure_filename
from app.models import User, Direction, ElectiveCourse, Settings, StudentElectiveCourse, db
import pandas as pd

# PDF-парсинг (новый модуль)
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Selenium (новый модуль — автозагрузка с платформы)
try:
    import requests as http_requests
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

manage_courses_bp = Blueprint('manage_courses_bp', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xls', 'xlsx', 'pdf'}

# URL закрытой платформы с учебными планами
PLATFORM_URL = "https://umk:ytrewq@math-it.petrsu.ru/umk/UMK_MF/UP_RUP.html"

# Маппинг колонок PDF на семестры
SEMESTER_COLS = {9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 6, 15: 7, 16: 8}


# ── Общие утилиты ─────────────────────────────────────────────────────────────

def extract_year_from_filename(filename):
    """Извлекает год из названия файла (например: UP_ISIT_2023.pdf -> 2023)"""
    match = re.search(r'(\d{4})', filename)
    return int(match.group(1)) if match else None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Обработка Excel (оригинальная логика) ─────────────────────────────────────

def find_elective_disciplines_excel(excel_file, sheet_name, start_phrase):
    """Ищет дисциплины по выбору в Excel файле."""
    try:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
    except Exception as e:
        print(f"Ошибка при чтении Excel: {e}")
        return []

    elective_disciplines = []
    start_row = None

    for index, row in df.iterrows():
        for cell in row:
            if isinstance(cell, str) and start_phrase in cell:
                start_row = index
                break
        if start_row is not None:
            break

    if start_row is None:
        return []

    current_row = start_row + 1
    while current_row < len(df):
        discipline_name = df.iloc[current_row, 0]
        if not isinstance(discipline_name, str) or not discipline_name.strip():
            break

        semesters = []
        for semester_column in range(3, 11):
            semester_value = df.iloc[current_row, semester_column]
            if pd.notna(semester_value):
                semesters.append(semester_column - 2)

        elective_disciplines.append({"name": discipline_name, "semesters": semesters})
        current_row += 1

    return elective_disciplines


def process_excel_file(filepath, filename):
    """Обрабатывает XLS/XLSX файл учебного плана."""
    try:
        file_year = extract_year_from_filename(filename)
        if not file_year:
            return None, "Не удалось определить год из названия файла"

        xls = pd.ExcelFile(filepath)
        sheet_name = next((n for n in xls.sheet_names if 'уп' in n.lower()), None)
        if not sheet_name:
            return None, "Не найден лист с учебным планом"

        df = pd.read_excel(filepath, sheet_name=sheet_name)
        direction_code = None
        direction_name = None
        pattern = re.compile(r'\b\d{2}\.\d{2}\.\d{2}\b')

        for i, row in df.iterrows():
            for cell in row:
                if isinstance(cell, str):
                    match = pattern.search(cell)
                    if match:
                        direction_code = match.group()
                        parts = cell.split('-')
                        direction_name = parts[-1].strip() if len(parts) > 1 else ""
                        break
            if direction_code:
                break

        if not direction_code:
            return None, "Не найдена информация о направлении"

        elective_disciplines = find_elective_disciplines_excel(
            filepath, sheet_name, "Дисциплины по выбору"
        )

        courses = []
        current_semesters = []
        for discipline in elective_disciplines:
            name = discipline["name"]
            semesters = discipline["semesters"]
            if "Дисциплины по выбору" in name and semesters:
                current_semesters = semesters
                continue
            elif "Дисциплины по выбору" in name and not semesters:
                current_semesters = []
                continue
            for semester in current_semesters:
                courses.append({"name": name, "semester": semester})

        seen = set()
        unique_courses = []
        for course in courses:
            key = (course['name'], course['semester'])
            if key not in seen:
                seen.add(key)
                unique_courses.append(course)

        return {
            'direction': {'code': direction_code, 'name': direction_name, 'year': file_year},
            'elective_courses': unique_courses
        }, None

    except Exception as e:
        return None, f"Ошибка обработки файла: {str(e)}"


# ── Обработка PDF (новая логика) ──────────────────────────────────────────────

def normalize_cell(value):
    return '' if value is None else str(value).strip()


def is_positive_number(value):
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


def is_valid_discipline_name(name):
    """Отсекает мусорные строки: компетенции, служебные строки, короткие названия."""
    if not name or len(name) < 5 or name.isupper():
        return False
    garbage_patterns = [
        r'ОПК', r'ПК', r'УК', r'ИИ-',
        r'Форма', r'семестр', r'аттестации',
        r'час', r'зач', r'экз', r'№', r'^\d+$'
    ]
    for pattern in garbage_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return False
    return True


def extract_semester_from_line(line):
    """Извлекает номер семестра из строки дисциплины."""
    clean = re.split(r'ОПК|ПК|УК|ИИ-', line)[0]
    numbers = re.findall(r'\b\d+\b', clean)
    if not numbers:
        return None
    semester = int(numbers[-1])
    return semester if 1 <= semester <= 8 else None


def extract_all_lines_from_pdf(filepath):
    """Извлекает все строки текста из PDF."""
    lines = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split('\n'):
                    clean = line.strip()
                    if clean:
                        lines.append(clean)
    return lines


def find_direction_info(all_lines):
    """Ищет код и название направления в строках PDF."""
    pattern = re.compile(r'(\d{2}\.\d{2}\.\d{2})\s*-\s*(.+)')
    for line in all_lines:
        match = pattern.search(line)
        if match:
            return match.group(1), match.group(2).strip()
    return None, None


def detect_plan_type(all_lines):
    """Определяет тип учебного плана: магистратура или бакалавриат."""
    text = " ".join(all_lines).lower()
    return "magistr" if "магистра" in text else "bachelor"


def find_electives_bachelor(all_lines):
    """Парсит дисциплины по выбору для бакалавриата."""
    elective_disciplines = []
    STOP_PHRASES = ["Б1.В.ФК", "Физическая культура (элек.)"]
    start_index = None

    for i, line in enumerate(all_lines):
        if "Дисциплины по выбору" in line:
            start_index = i
            break

    if start_index is None:
        return []

    i = start_index + 1
    while i < len(all_lines):
        line = all_lines[i]

        if any(stop in line for stop in STOP_PHRASES):
            break

        if "Дисциплины по выбору" in line:
            i += 1
            continue

        if re.match(r'^\*?\s*[А-ЯA-Za-z]', line):
            name = re.sub(r'^\*\s*', '', line)
            semester = extract_semester_from_line(name)
            name = re.split(r'\s+\d+', name)[0]
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0].strip()

            if name and semester and is_valid_discipline_name(name):
                elective_disciplines.append({"name": name, "semesters": [semester]})

        i += 1

    return elective_disciplines


def find_electives_magistr(all_lines):
    """Парсит дисциплины по выбору для магистратуры."""
    electives = []
    start_index = None

    for i, line in enumerate(all_lines):
        if "Б1.В" in line and "Вариативная часть" in line:
            start_index = i
            break

    if start_index is None:
        return []

    i = start_index + 1
    current_semester = None

    while i < len(all_lines):
        line = all_lines[i]

        if re.search(r'\bБ2\b|\bБ3\b', line):
            break

        if "Дисциплины по выбору" in line:
            numbers = re.findall(r'\b\d+\b', line)
            current_semester = None
            if numbers:
                sem = int(numbers[-1])
                if 1 <= sem <= 4:
                    current_semester = sem
            i += 1
            continue

        if current_semester and re.match(r'^\*?\s*[А-ЯA-Za-z]', line):
            name = re.sub(r'^\*\s*', '', line)
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0]
            name = re.sub(r'\d+', '', name).strip()

            if is_valid_discipline_name(name):
                electives.append({"name": name, "semesters": [current_semester]})

        i += 1

    return electives


def process_pdf_file(filepath, filename):
    """Обрабатывает PDF файл учебного плана."""
    if not PDF_AVAILABLE:
        return None, "pdfplumber не установлен. Выполните: pip install pdfplumber"
    try:
        file_year = extract_year_from_filename(filename)
        if not file_year:
            return None, "Не удалось определить год из названия файла"

        all_lines = extract_all_lines_from_pdf(filepath)
        if not all_lines:
            return None, "Не удалось извлечь текст из PDF"

        direction_code, direction_name = find_direction_info(all_lines)
        if not direction_code:
            return None, "Не найдена информация о направлении (формат: XX.XX.XX - Название)"

        plan_type = detect_plan_type(all_lines)

        if plan_type == "magistr":
            elective_disciplines = find_electives_magistr(all_lines)
        else:
            elective_disciplines = find_electives_bachelor(all_lines)

        courses = [
            {"name": d["name"], "semester": sem}
            for d in elective_disciplines
            for sem in d["semesters"]
        ]

        seen = set()
        unique_courses = []
        for course in courses:
            key = (course['name'], course['semester'])
            if key not in seen:
                seen.add(key)
                unique_courses.append(course)

        return {
            'direction': {'code': direction_code, 'name': direction_name, 'year': file_year},
            'elective_courses': unique_courses
        }, None

    except Exception as e:
        return None, f"Ошибка обработки PDF: {str(e)}"


# ── Selenium: автозагрузка с платформы ───────────────────────────────────────

def get_driver():
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("selenium или webdriver_manager не установлены")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def is_study_plan(text):
    if not text or "ФГОС" in text.upper():
        return False
    return bool(re.search(r"\b\d{6}-", text))


def extract_links():
    """Извлекает ссылки на учебные планы с платформы через Selenium."""
    driver = get_driver()
    driver.get(PLATFORM_URL)
    time.sleep(3)

    result = []
    for link in driver.find_elements(By.TAG_NAME, "a"):
        text = link.text.strip()
        href = link.get_attribute("href")
        if not text or not href:
            continue
        if is_study_plan(text):
            code_match = re.search(r'\b(\d{2})[.\-]?\d{2}[.\-]?\d{2}', text)
            if code_match and code_match.group(1) == "44":
                continue  # игнорируем педагогику
            result.append({"name": text, "url": href})

    driver.quit()
    return result


def download_pdf(url, filename):
    """Скачивает PDF по URL."""
    try:
        response = http_requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return filepath
    except Exception as e:
        print(f"Ошибка скачивания {url}: {e}")
    return None


def _save_direction_and_courses(direction_data, elective_courses):
    """Вспомогательная функция: сохраняет направление и дисциплины в БД."""
    direction = Direction.query.filter_by(
        code=direction_data['code'],
        year=direction_data['year']
    ).first()

    if not direction:
        existing = Direction.query.filter_by(code=direction_data['code']).first()
        direction = Direction(
            code=direction_data['code'],
            name=direction_data['name'],
            year=direction_data['year']
        )
        db.session.add(direction)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

    return direction


# ── Маршруты Flask ────────────────────────────────────────────────────────────

@manage_courses_bp.route('/manage-courses', methods=['GET', 'POST'])
def manage_courses():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
        return redirect(url_for('dashboard'))

    directions = Direction.query.order_by(Direction.code, Direction.year).all()
    direction_filter = request.args.get('direction_filter', None)

    if direction_filter:
        elective_courses = ElectiveCourse.query.filter_by(direction_id=direction_filter).all()
    else:
        elective_courses = ElectiveCourse.query.all()

    settings = Settings.query.first()

    return render_template('manage_courses.html',
                           user=user,
                           directions=directions,
                           elective_courses=elective_courses,
                           settings=settings,
                           selected_direction_id=direction_filter)


@manage_courses_bp.route('/toggle-enrollment', methods=['POST'])
def toggle_enrollment():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
        return redirect(url_for('dashboard'))

    settings = Settings.query.first()
    if not settings:
        settings = Settings(is_enrollment_open=True)
        db.session.add(settings)
    else:
        settings.is_enrollment_open = not settings.is_enrollment_open

    db.session.commit()
    flash(f"Запись на дисциплины {'открыта' if settings.is_enrollment_open else 'закрыта'}", "success")
    return redirect(url_for('manage_courses_bp.manage_courses'))


@manage_courses_bp.route('/upload-plan', methods=['POST'])
def upload_plan():
    """Ручная загрузка учебного плана (XLS, XLSX или PDF)."""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
        return redirect(url_for('dashboard'))

    if 'plan_file' not in request.files:
        flash('Файл не был загружен', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    file = request.files['plan_file']
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    if not allowed_file(file.filename):
        flash('Недопустимый формат файла. Разрешены: .xls, .xlsx, .pdf', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    filename = secure_filename(file.filename)
    upload_path = os.path.join(UPLOAD_FOLDER, filename)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file.save(upload_path)

    ext = filename.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        result, error = process_pdf_file(upload_path, filename)
    else:
        result, error = process_excel_file(upload_path, filename)

    if error:
        flash(f'Ошибка обработки файла: {error}', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    direction_data = result['direction']

    direction = Direction.query.filter_by(
        code=direction_data['code'],
        year=direction_data['year']
    ).first()

    if not direction:
        direction = Direction(
            code=direction_data['code'],
            name=direction_data['name'],
            year=direction_data['year']
        )
        db.session.add(direction)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при добавлении направления: {str(e)}', 'error')
            return redirect(url_for('manage_courses_bp.manage_courses'))

    new_courses = result['elective_courses']
    old_courses = ElectiveCourse.query.filter_by(direction_id=direction.id).all()

    to_add = [c for c in new_courses
              if not any(oc.name == c['name'] and oc.semester == c['semester'] for oc in old_courses)]
    to_delete = [{'id': oc.id, 'name': oc.name, 'semester': oc.semester} for oc in old_courses
                 if not any(c['name'] == oc.name and c['semester'] == oc.semester for c in new_courses)]
    no_changes = [c for c in new_courses
                  if any(oc.name == c['name'] and oc.semester == c['semester'] for oc in old_courses)]

    session['pending_upload'] = {
        'direction': direction_data,
        'to_add': to_add,
        'to_delete': to_delete,
        'no_changes': no_changes
    }

    return render_template('confirm_course_changes.html',
                           to_add=to_add,
                           to_delete=to_delete,
                           no_changes=no_changes,
                           direction=direction)


@manage_courses_bp.route('/confirm-upload', methods=['POST'])
def confirm_upload():
    """Подтверждение изменений после ручной загрузки."""
    data = session.get('pending_upload')
    if not data:
        flash('Нет данных для подтверждения', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    direction_data = data['direction']
    to_delete = data['to_delete']

    direction = Direction.query.filter_by(
        code=direction_data['code'],
        year=direction_data['year']
    ).first()

    if not direction:
        direction = Direction(
            code=direction_data['code'],
            name=direction_data['name'],
            year=direction_data['year']
        )
        db.session.add(direction)
        db.session.commit()

    if to_delete:
        old_ids = [c['id'] for c in to_delete]
        StudentElectiveCourse.query.filter(
            StudentElectiveCourse.elective_course_id.in_(old_ids)
        ).delete(synchronize_session=False)
        ElectiveCourse.query.filter(
            ElectiveCourse.id.in_(old_ids)
        ).delete(synchronize_session=False)

    count = int(request.form.get('to_add_count', 0))
    for i in range(count):
        if request.form.get(f'course_add_{i}') == '1':
            name = request.form.get(f'course_name_{i}', '').strip()
            semester = request.form.get(f'course_semester_{i}')
            if name and semester:
                db.session.add(ElectiveCourse(
                    name=name,
                    semester=int(semester),
                    direction_id=direction.id
                ))

    db.session.commit()
    session.pop('pending_upload', None)
    flash('Данные успешно обновлены', 'success')
    return redirect(url_for('manage_courses_bp.manage_courses'))


@manage_courses_bp.route('/update-plans', methods=['POST'])
def update_plans():
    """Автоматическая загрузка учебных планов с закрытой платформы через Selenium."""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
        return redirect(url_for('dashboard'))

    if not SELENIUM_AVAILABLE:
        flash('Selenium не установлен. Выполните: pip install selenium webdriver-manager requests', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    if not PDF_AVAILABLE:
        flash('pdfplumber не установлен. Выполните: pip install pdfplumber', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))

    try:
        links = extract_links()
        if not links:
            flash("Не удалось найти учебные планы на платформе", "error")
            return redirect(url_for('manage_courses_bp.manage_courses'))

        total_loaded = 0

        for item in links:
            url = item["url"]
            filename = secure_filename(url.split("/")[-1])
            if not filename.endswith('.pdf'):
                filename += '.pdf'

            filepath = download_pdf(url, filename)
            if not filepath:
                continue

            result, error = process_pdf_file(filepath, filename)
            if error:
                print(f"Ошибка {filename}: {error}")
                continue

            direction_data = result['direction']

            direction = Direction.query.filter_by(
                code=direction_data['code'],
                year=direction_data['year']
            ).first()

            if not direction:
                direction = Direction(
                    code=direction_data['code'],
                    name=direction_data['name'],
                    year=direction_data['year']
                )
                db.session.add(direction)
                db.session.commit()

            # Удаляем старые дисциплины
            old_courses = ElectiveCourse.query.filter_by(direction_id=direction.id).all()
            if old_courses:
                old_ids = [c.id for c in old_courses]
                StudentElectiveCourse.query.filter(
                    StudentElectiveCourse.elective_course_id.in_(old_ids)
                ).delete(synchronize_session=False)
                ElectiveCourse.query.filter(
                    ElectiveCourse.id.in_(old_ids)
                ).delete(synchronize_session=False)

            # Добавляем новые
            for course in result['elective_courses']:
                db.session.add(ElectiveCourse(
                    name=course['name'],
                    semester=course['semester'],
                    direction_id=direction.id
                ))

            db.session.commit()
            total_loaded += 1

        flash(f"Обновлено учебных планов: {total_loaded}", "success")

    except Exception as e:
        flash(f"Ошибка: {str(e)}", "error")

    return redirect(url_for('manage_courses_bp.manage_courses'))


@manage_courses_bp.route('/delete-all-courses', methods=['POST'])
def delete_all_courses():
    """Удаление всех дисциплин (для отладки)."""
    try:
        StudentElectiveCourse.query.delete()
        ElectiveCourse.query.delete()
        db.session.commit()
        flash('Все дисциплины удалены', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении: {e}', 'error')
    return redirect(url_for('manage_courses_bp.manage_courses'))
