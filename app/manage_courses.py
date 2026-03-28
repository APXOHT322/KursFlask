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
# Структура таблицы в PDF аналогична Excel:
# col_index 9 = 1-й сем, col_index 10 = 2-й сем, ..., col_index 16 = 8-й сем
SEMESTER_COLS = {9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 6, 15: 7, 16: 8}


def extract_year_from_filename(filename):
    """Извлекает год из названия файла (например: UP_ISIT_2023.pdf -> 2023)"""
    match = re.search(r'(\d{4})', filename)
    if match:
        return int(match.group(1))
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def normalize_cell(value):
    """Приводит значение ячейки таблицы к строке, убирает пробелы."""
    if value is None:
        return ''
    return str(value).strip()


def is_positive_number(value):
    """Проверяет, является ли значение положительным числом (для определения семестра)."""
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


def get_semesters_for_row(row):
    """
    Возвращает список номеров семестров для строки таблицы PDF
    по значениям в колонках с индексами 9–16.
    """
    semesters = []
    for col_index, sem_number in SEMESTER_COLS.items():
        if col_index < len(row):
            val = normalize_cell(row[col_index])
            if val and val not in ('nan', '0', '') and is_positive_number(val):
                semesters.append(sem_number)
    return semesters


def extract_all_rows_from_pdf(filepath):
    """
    Извлекает текст из PDF и разбивает его на логические строки.
    """
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


def find_elective_disciplines_from_rows(all_lines, start_phrase):
    elective_disciplines = []

    STOP_PHRASES = [
        "Б1.В.ФК",
        "Физическая культура (элек.)"
    ]

    start_index = None

    # ищем начало блока
    for i, line in enumerate(all_lines):
        if start_phrase in line:
            start_index = i
            break

    if start_index is None:
        return []

    i = start_index + 1

    while i < len(all_lines):
        line = all_lines[i]

        # стоп-блок
        if any(stop in line for stop in STOP_PHRASES):
            break

        # пропускаем заголовки
        if "Дисциплины по выбору" in line:
            i += 1
            continue

        # --- ДИСЦИПЛИНА ---
        if re.match(r'^\*?\s*[А-ЯA-Za-z]', line):

            # убираем *
            name = re.sub(r'^\*\s*', '', line)

            # извлекаем семестр
            semester = extract_semester_from_line(name)

            # чистим название
            name = re.split(r'\s+\d+', name)[0]
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0]
            name = name.strip()

            if name and semester and is_valid_discipline_name(name):
                elective_disciplines.append({
                    "name": name,
                    "semesters": [semester]
                })

        i += 1

    return elective_disciplines
    elective_disciplines = []

    STOP_PHRASES = [
        "Б1.В.ФК",
        "Физическая культура (элек.)"
    ]

    start_index = None

    for i, line in enumerate(all_lines):
        if start_phrase in line:
            start_index = i
            break

    if start_index is None:
        return []

    i = start_index
    current_semesters = []

    while i < len(all_lines):
        line = all_lines[i]

        # 🔴 СТОП-БЛОК
        if any(stop in line for stop in STOP_PHRASES):
            break

        # --- Заголовок группы ---
        if "Дисциплины по выбору" in line:
            current_semesters = []

            numbers = re.findall(r'\b[1-8]\b', line)
            current_semesters = list(map(int, numbers))

            i += 1
            continue

        # --- Дисциплина ---
        if re.match(r'^\*?\s*[А-ЯA-Za-z]', line):
            name = re.sub(r'^\*\s*', '', line)

            name = re.split(r'\s+\d+', name)[0]
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0]
            name = name.strip()

            if name and current_semesters and is_valid_discipline_name(name):
                for sem in current_semesters:
                    elective_disciplines.append({
                        "name": name,
                        "semesters": [sem]
                    })

        i += 1

    return elective_disciplines
    elective_disciplines = []

    start_index = None

    # 1. Ищем начало блока
    for i, line in enumerate(all_lines):
        if start_phrase in line:
            start_index = i
            break

    if start_index is None:
        print("Не найден блок дисциплин по выбору")
        return []

    i = start_index

    current_semesters = []

    while i < len(all_lines):
        line = all_lines[i]

        # --- Заголовок группы ---
        if "Дисциплины по выбору" in line:
            current_semesters = []

            # ищем числа (семестры) в строке
            numbers = re.findall(r'\b[1-8]\b', line)
            current_semesters = list(map(int, numbers))

            i += 1
            continue

        # --- Дисциплина ---
        if re.match(r'^\*?\s*[А-ЯA-Za-z]', line):
            name = re.sub(r'^\*\s*', '', line)

            # отсекаем хвост с цифрами
            # убираем всё после чисел (нагрузка, часы и т.д.)
            name = re.split(r'\s+\d+', name)[0]

            # убираем хвосты с компетенциями
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0]

            name = name.strip()

            if name and current_semesters and is_valid_discipline_name(name):
                for sem in current_semesters:
                    elective_disciplines.append({
                        "name": name,
                        "semesters": [sem]
                    })

        i += 1

    return elective_disciplines
    """
    Ищет дисциплины по выбору в строках, извлечённых из PDF.

    Логика полностью повторяет оригинальную логику для Excel:
    - Ищет строку с фразой 'Дисциплины по выбору'
    - После неё ищет заголовки групп (тоже содержащие 'Дисциплины по выбору')
    - Из заголовка группы читает семестры (колонки 9–16)
    - Следующие 2 строки считаются дисциплинами этой группы
    """
    elective_disciplines = []
    start_row_index = None

    # Ищем строку с фразой-маркером
    for i, row in enumerate(all_rows):
        for cell in row:
            if isinstance(cell, str) and elective_disciplines_start_phrase in cell:
                start_row_index = i
                break
        if start_row_index is not None:
            break

    if start_row_index is None:
        print(f"Не найдена фраза '{elective_disciplines_start_phrase}' в PDF-файле.")
        return []

    current_row_index = start_row_index + 1
    total_rows = len(all_rows)

    while current_row_index < total_rows:
        row = all_rows[current_row_index]

        # Берём название дисциплины из второй колонки (индекс 1), как в Excel
        discipline_name = normalize_cell(row[1]) if len(row) > 1 else ''

        if not discipline_name:
            break

        # Заголовок группы: содержит "Дисциплины по выбору"
        if "Дисциплины по выбору" in discipline_name:
            semesters = get_semesters_for_row(row)

            # Следующие 2 строки — сами дисциплины
            for offset in range(1, 3):
                next_index = current_row_index + offset
                if next_index >= total_rows:
                    break
                next_row = all_rows[next_index]
                next_name = normalize_cell(next_row[1]) if len(next_row) > 1 else ''
                if next_name:
                    elective_disciplines.append({
                        "name": next_name,
                        "semesters": semesters
                    })

            current_row_index += 3  # заголовок + 2 дисциплины
            continue

        current_row_index += 1

    return elective_disciplines

def extract_semester_from_line(line):
    """
    Извлекает семестр из строки дисциплины.
    Берём ПОСЛЕДНЕЕ число перед компетенциями (ПК, ОПК и т.д.)
    """

    # убираем компетенции
    clean = re.split(r'ОПК|ПК|УК|ИИ-', line)[0]

    # ищем все числа
    numbers = re.findall(r'\b\d+\b', clean)

    if not numbers:
        return None

    # берём последнее число
    semester = int(numbers[-1])

    # фильтр: семестр только 1–8
    if 1 <= semester <= 8:
        return semester

    return None


def process_pdf_file(filepath, filename):
    """
    Основная функция обработки PDF-файла.
    Возвращает (result_dict, error_string).
    Структура result_dict идентична оригинальной для Excel.
    """
    try:
        file_year = extract_year_from_filename(filename)
        if not file_year:
            return None, "Не удалось определить год из названия файла"

        all_rows = extract_all_rows_from_pdf(filepath)

        if not all_rows:
            return None, "Не удалось извлечь данные из PDF-файла. Проверьте, что файл содержит таблицы."

        # Ищем код и название направления
        direction_code, direction_name = find_direction_info(all_rows)
        degree_type = detect_plan_type(all_rows)

        if not direction_code:
            return None, "Не найдена информация о направлении (формат: XX.XX.XX - Название)"

        # Ищем дисциплины по выбору
        # --- 🔴 ОПРЕДЕЛЯЕМ ТИП ПЛАНА ---
        plan_type = detect_plan_type(all_rows)

        # --- 🔴 ВЫБИРАЕМ НУЖНЫЙ ПАРСЕР ---
        if plan_type == "magistr":
            elective_disciplines = find_electives_magistr(all_rows)

        else:
            # 👉 твоя старая логика (бакалавры НЕ ТРОГАЕМ)
            elective_disciplines = find_elective_disciplines_from_rows(
                all_rows, "Дисциплины по выбору"
            )

        # Разворачиваем: одна дисциплина может быть в нескольких семестрах
        courses = [
    {"name": d["name"], "semester": sem}
    for d in elective_disciplines
    for sem in d["semesters"]
]

        # Убираем дубликаты
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
                'degree': degree_type   # 🔴 ВОТ ЭТО ДОБАВЛЯЕМ
            },
            'elective_courses': unique_courses
        }, None

    except Exception as e:
        return None, f"Ошибка обработки файла: {str(e)}"


def is_valid_discipline_name(name):
    """
    Отсекает мусор:
    - компетенции (ИИ-ОПК-1, ПК-2 и т.д.)
    - служебные строки
    - короткие/битые строки
    """

    if not name:
        return False

    # ❌ мусорные паттерны
    garbage_patterns = [
        r'ОПК', r'ПК', r'УК', r'ИИ-',
        r'Форма', r'семестр', r'аттестации',
        r'час', r'зач', r'экз', r'№',
        r'^\d+$'
    ]

    for pattern in garbage_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return False

    # ❌ слишком короткое
    if len(name) < 5:
        return False

    # ❌ если почти всё — заглавные (часто мусор)
    if name.isupper():
        return False

    return True

# ---------------------------------------------------------------------------
# Маршруты Flask — логика полностью сохранена, изменены только:
#   1. Проверка расширения (теперь только .pdf)
#   2. Вызов process_pdf_file вместо process_excel_file
# ---------------------------------------------------------------------------

URL = "https://umk:ytrewq@math-it.petrsu.ru/umk/UMK_MF/UP_RUP.html"


from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

def get_driver():
    options = Options()
    options.add_argument("--headless")  # браузер без окна
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def is_study_plan(text):
    if not text:
        return False

    if "ФГОС" in text.upper():
        return False

    if re.search(r"\b\d{6}-", text):
        return True

    return False


def extract_links():
    driver = get_driver()
    driver.get(URL)
    time.sleep(3)

    links = driver.find_elements(By.TAG_NAME, "a")

    result = []

    for link in links:
        text = link.text.strip()
        href = link.get_attribute("href")

        if not text or not href:
            continue

        if is_study_plan(text):

            # 🔴 извлекаем код направления (например 44.03.05 или 440305)
            code_match = re.search(r'\b(\d{2})[.\-]?\d{2}[.\-]?\d{2}', text)

            if code_match:
                code_prefix = code_match.group(1)

                # ❌ игнорируем педагогику (44.xx.xx)
                if code_prefix == "44":
                    continue

            result.append({
                "name": text,
                "url": href
            })

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
def detect_plan_type(all_lines):
    text = " ".join(all_lines).lower()

    if "магистра" in text:
        return "magistr"

    return "bachelor"

def find_electives_magistr(all_lines):
    electives = []

    start_index = None

    # --- 1. Ищем начало вариативной части ---
    for i, line in enumerate(all_lines):
        if "Б1.В" in line and "Вариативная часть" in line:
            start_index = i
            break

    if start_index is None:
        print("Не найдена вариативная часть (магистратура)")
        return []

    i = start_index + 1
    current_semester = None

    while i < len(all_lines):
        line = all_lines[i]

        # --- 🔴 СТОП: выходим из блока ---
        if re.search(r'\bБ2\b|\bБ3\b', line):
            break

        # --- 2. Заголовок группы ---
        if "Дисциплины по выбору" in line:

            # ищем все числа в строке
            numbers = re.findall(r'\b\d+\b', line)

            current_semester = None

            if numbers:
                sem = int(numbers[-1])  # последнее число = семестр
                if 1 <= sem <= 4:
                    current_semester = sem

            i += 1
            continue

        # --- 3. Дисциплина ---
        if current_semester and re.match(r'^\*?\s*[А-ЯA-Za-z]', line):

            # убираем *
            name = re.sub(r'^\*\s*', '', line)

            # убираем компетенции
            name = re.split(r'ОПК|ПК|УК|ИИ-', name)[0]

            # убираем цифры (часы и т.д.)
            name = re.sub(r'\d+', '', name)

            name = name.strip()

            if is_valid_discipline_name(name):
                electives.append({
                    "name": name,
                    "semesters": [current_semester]
                })

        i += 1

    return electives


@manage_courses_bp.route('/update-plans', methods=['POST'])
def update_plans():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
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

            # --- ищем или создаем направление ---
            direction = Direction.query.filter_by(
                code=direction_data['code'],
                year=direction_data['year']
            ).first()

            if not direction:
                direction = Direction(
                    code=direction_data['code'],
                    name=direction_data['name'],
                    year=direction_data['year'],
                    degree=direction_data.get('degree')  # 🔴 ДОБАВИЛИ
                )
                db.session.add(direction)
                db.session.commit()

            # --- удаляем старые дисциплины ---
            old_courses = ElectiveCourse.query.filter_by(direction_id=direction.id).all()

            if old_courses:
                old_ids = [c.id for c in old_courses]

                StudentElectiveCourse.query.filter(
                    StudentElectiveCourse.elective_course_id.in_(old_ids)
                ).delete(synchronize_session=False)

                ElectiveCourse.query.filter(
                    ElectiveCourse.id.in_(old_ids)
                ).delete(synchronize_session=False)

            # --- добавляем новые ---
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
