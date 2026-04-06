import os
import re
from flask import Blueprint, render_template, redirect, url_for, session, request, flash
from werkzeug.utils import secure_filename
from app.models import User, Direction, ElectiveCourse, Settings, StudentElectiveCourse, db
import pdfplumber
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

manage_courses_bp = Blueprint('manage_courses_bp', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}

# Маппинг колонок таблицы PDF на номера семестров.
SEMESTER_COLS = {9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 6, 15: 7, 16: 8}


def extract_year_from_filename(filename):
    match = re.search(r'(\d{4})', filename)
    return int(match.group(1)) if match else None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def normalize_cell(value):
    if value is None:
        return ''
    return str(value).strip()


def is_positive_number(value):
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


def get_semesters_for_row(row):
    semesters = []
    for col_index, sem_number in SEMESTER_COLS.items():
        if col_index < len(row):
            val = normalize_cell(row[col_index])
            if val and val not in ('nan', '0', '') and is_positive_number(val):
                semesters.append(sem_number)
    return semesters


def extract_all_rows_from_pdf(filepath):
    lines = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            page_lines = text.split('\n')
            for line in page_lines:
                clean_line = line.strip()
                if clean_line:
                    lines.append(clean_line)
    return lines


def find_direction_info(all_lines):
    pattern = re.compile(r'(\d{2}\.\d{2}\.\d{2})\s*-\s*(.+)')
    for line in all_lines:
        match = pattern.search(line)
        if match:
            return match.group(1), match.group(2).strip()
    return None, None


def detect_plan_type(all_lines):
    text = " ".join(all_lines).lower()
    return "magistr" if "магистра" in text else "bachelor"


def find_electives_magistr(all_lines):
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
            if name and len(name) >= 5 and not name.isupper():
                electives.append({"name": name, "semesters": [current_semester]})
        i += 1
    return electives


def find_elective_disciplines_from_rows(all_lines, start_phrase):
    elective_disciplines = []
    STOP_PHRASES = ["Б1.В.ФК", "Физическая культура (элек.)"]
    start_index = None
    for i, line in enumerate(all_lines):
        if start_phrase in line:
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


def extract_semester_from_line(line):
    clean = re.split(r'ОПК|ПК|УК|ИИ-', line)[0]
    numbers = re.findall(r'\b\d+\b', clean)
    if not numbers:
        return None
    semester = int(numbers[-1])
    return semester if 1 <= semester <= 8 else None


def is_valid_discipline_name(name):
    if not name or len(name) < 5 or name.isupper():
        return False
    garbage_patterns = [r'ОПК', r'ПК', r'УК', r'ИИ-', r'Форма', r'семестр', r'аттестации', r'час', r'зач', r'экз', r'№', r'^\d+$']
    for pattern in garbage_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return False
    return True


def process_pdf_file(filepath, filename):
    try:
        file_year = extract_year_from_filename(filename)
        if not file_year:
            return None, "Не удалось определить год из названия файла"

        all_rows = extract_all_rows_from_pdf(filepath)
        if not all_rows:
            return None, "Не удалось извлечь данные из PDF-файла"

        direction_code, direction_name = find_direction_info(all_rows)
        degree_type = detect_plan_type(all_rows)

        if not direction_code:
            return None, "Не найдена информация о направлении (формат: XX.XX.XX - Название)"

        plan_type = detect_plan_type(all_rows)
        if plan_type == "magistr":
            elective_disciplines = find_electives_magistr(all_rows)
        else:
            elective_disciplines = find_elective_disciplines_from_rows(all_rows, "Дисциплины по выбору")

        courses = [{"name": d["name"], "semester": sem} for d in elective_disciplines for sem in d["semesters"]]

        # Удаление дубликатов
        seen = set()
        unique_courses = []
        for course in courses:
            key = (course['name'], course['semester'])
            if key not in seen:
                seen.add(key)
                unique_courses.append(course)

        return {
            'direction': {
                'code': direction_code,
                'name': direction_name,
                'year': file_year,
                'degree': degree_type
            },
            'elective_courses': unique_courses
        }, None
    except Exception as e:
        return None, f"Ошибка обработки файла: {str(e)}"


# -------------------------------------------------------------------
# Вспомогательные функции для парсинга учебных планов с сайта
# -------------------------------------------------------------------
URL = "https://umk:ytrewq@math-it.petrsu.ru/umk/UMK_MF/UP_RUP.html"

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--single-process")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager(driver_version="146.0.7680.80").install()),
        options=options
    )


def is_study_plan(text):
    if not text:
        return False
    if "ФГОС" in text.upper():
        return False
    return bool(re.search(r"\b\d{6}-", text))


def extract_links():
    driver = get_driver()
    driver.get(URL)
    time.sleep(3)
    links = driver.find_elements(By.TAG_NAME, "a")
    result = []
    for link in links:
        text = link.text.strip()
        href = link.get_attribute("href")
        if not text or not href or not is_study_plan(text):
            continue
        code_match = re.search(r'\b(\d{2})[.\-]?\d{2}[.\-]?\d{2}', text)
        if code_match and code_match.group(1) == "44":
            continue
        result.append({"name": text, "url": href})
    driver.quit()
    return result


def download_pdf(url, filename):
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return filepath
    except Exception as e:
        print(f"Ошибка скачивания {url}: {e}")
    return None


# -------------------------------------------------------------------
# Маршруты (с добавленной ролью администратора)
# -------------------------------------------------------------------
@manage_courses_bp.route('/manage-courses', methods=['GET', 'POST'])
def manage_courses():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    # Разрешаем и специалисту дирекции, и администратору
    if not (user.has_role('Специалист дирекции') or user.has_role('Администратор')):
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
    if not (user.has_role('Специалист дирекции') or user.has_role('Администратор')):
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


@manage_courses_bp.route('/update-plans', methods=['POST'])
def update_plans():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    if not (user.has_role('Специалист дирекции') or user.has_role('Администратор')):
        return redirect(url_for('dashboard'))

    try:
        links = extract_links()
        if not links:
            flash("Не удалось найти учебные планы", "error")
            return redirect(url_for('manage_courses_bp.manage_courses'))

        total_loaded = 0
        for item in links:
            url = item["url"]
            filename = secure_filename(url.split("/")[-1])
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
                    year=direction_data['year'],
                    degree=direction_data.get('degree')
                )
                db.session.add(direction)
                db.session.commit()

            # Удаляем старые дисциплины направления
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

        flash(f"✅ Обновлено учебных планов: {total_loaded}", "success")
    except Exception as e:
        flash(f"❌ Ошибка: {str(e)}", "error")
    return redirect(url_for('manage_courses_bp.manage_courses'))