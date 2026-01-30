import os
import re
from flask import Blueprint, render_template, redirect, url_for, session, request, flash
from werkzeug.utils import secure_filename
from app.models import User, Direction, ElectiveCourse, Settings, StudentElectiveCourse, db
import pandas as pd

manage_courses_bp = Blueprint('manage_courses_bp', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'xls', 'xlsx'}

def extract_year_from_filename(filename):
    """Извлекает год из названия файла (например: UP_ISIT_2023.xls -> 2023)"""
    # Ищем 4 цифры подряд (год)
    match = re.search(r'(\d{4})', filename)
    if match:
        return int(match.group(1))
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def find_elective_disciplines(excel_file, sheet_name, elective_disciplines_start_phrase):
    """
    Ищет дисциплины по выбору в Excel файле, начиная с указанной фразы,
    и извлекает информацию о семестрах.
    """
    try:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
    except FileNotFoundError:
        print(f"Ошибка: Файл '{excel_file}' не найден.")
        return []
    except Exception as e:
        print(f"Ошибка при чтении Excel файла: {e}")
        return []

    elective_disciplines = []
    start_row = None

    # Находим строку, содержащую фразу "Дисциплины по выбору"
    for index, row in df.iterrows():
        for cell in row:
            if isinstance(cell, str) and elective_disciplines_start_phrase in cell:
                start_row = index
                break
        if start_row is not None:
            break

    if start_row is None:
        print(f"Не найдена фраза '{elective_disciplines_start_phrase}' в файле.")
        return []

    current_row = start_row + 1
    while current_row < len(df):
        discipline_name = df.iloc[current_row, 0]  # Название в первом столбце

        if not isinstance(discipline_name, str) or not discipline_name.strip():
            break

        semesters = []
        for semester_column in range(3, 11):  # Столбцы 4-11
            semester_value = df.iloc[current_row, semester_column]
            if pd.notna(semester_value):
                semesters.append(semester_column - 2)

        elective_disciplines.append({"name": discipline_name, "semesters": semesters})
        current_row += 1

    return elective_disciplines



def process_excel_file(filepath, filename):
    try:
        # Извлекаем год из названия файла
        file_year = extract_year_from_filename(filename)
        if not file_year:
            return None, "Не удалось определить год из названия файла"

        xls = pd.ExcelFile(filepath)

        sheet_name = None
        for name in xls.sheet_names:
            if 'уп' in name.lower():
                sheet_name = name
                break

        if not sheet_name:
            return None, "Не найден лист с учебным планом"

        # Попытка определить направление из файла
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
                        if len(parts) > 1:
                            direction_name = parts[-1].strip()
                        else:
                            direction_name = ""
                        break
            if direction_code:
                break

        if not direction_code:
            return None, "Не найдена информация о направлении"

        # Извлекаем дисциплины по выбору
        elective_disciplines = find_elective_disciplines(filepath, sheet_name, "Дисциплины по выбору")

        # Обработка блоков и дисциплин
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
                courses.append({
                    "name": name,
                    "semester": semester
                })

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
                'year': file_year
            },
            'elective_courses': unique_courses
        }, None

    except Exception as e:
        return None, f"Ошибка обработки файла: {str(e)}"


@manage_courses_bp.route('/manage-courses', methods=['GET', 'POST'])
def manage_courses():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = User.query.get(user_id)
    if not user.has_role('Специалист дирекции'):
        return redirect(url_for('dashboard'))
    
    # Получаем все направления сгруппированные по годам
    directions = Direction.query.order_by(Direction.code, Direction.year).all()
    
    # Получаем выбранное направление из параметра запроса
    direction_filter = request.args.get('direction_filter', None)
    
    # Если фильтр выбран, показываем дисциплины только для этого направления
    if direction_filter:
        elective_courses = ElectiveCourse.query.filter_by(direction_id=direction_filter).all()
    else:
        elective_courses = ElectiveCourse.query.all()
    
    # Получаем настройки
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

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_path = os.path.join(UPLOAD_FOLDER, filename)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(upload_path)

        # Передаем filename для извлечения года
        result, error = process_excel_file(upload_path, filename)
        if error:
            flash(f'Ошибка обработки файла: {error}', 'error')
            return redirect(url_for('manage_courses_bp.manage_courses'))

        direction_data = result['direction']
        
        # Ищем направление с указанным кодом и годом
        direction = Direction.query.filter_by(
            code=direction_data['code'],
            year=direction_data['year']
        ).first()
        
        if not direction:
            # Проверяем, есть ли направление с таким кодом
            existing_direction = Direction.query.filter_by(code=direction_data['code']).first()
            if existing_direction:
                # Создаем новую запись для другого года
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
            else:
                # Создаем новое направление
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

        to_add = []
        to_delete = []
        no_changes = []  # Список дисциплин, которые не изменились

        for course in new_courses:
            exists = next((c for c in old_courses if c.name == course['name'] and c.semester == course['semester']), None)
            if not exists:
                to_add.append(course)  # Добавляем новый курс
            else:
                no_changes.append(course)  # Курс без изменений

        for course in old_courses:
            exists = any(c['name'] == course.name and c['semester'] == course.semester for c in new_courses)
            if not exists:
                to_delete.append({
                    'id': course.id,
                    'name': course.name,
                    'semester': course.semester
                })

        session['pending_upload'] = {
            'direction': direction_data,
            'to_add': to_add,
            'to_delete': to_delete,
            'no_changes': no_changes
        }

        return render_template(
            'confirm_course_changes.html',
            to_add=to_add,
            to_delete=to_delete,
            no_changes=no_changes,
            direction=direction
        )
    else:
        flash('Недопустимый формат файла. Разрешены только .xls и .xlsx', 'error')
        return redirect(url_for('manage_courses_bp.manage_courses'))


@manage_courses_bp.route('/confirm-upload', methods=['POST'])
def confirm_upload():
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

    # Удаление дисциплин
    if to_delete:
        old_course_ids = [course['id'] for course in to_delete]
        if old_course_ids:
            StudentElectiveCourse.query.filter(
                StudentElectiveCourse.elective_course_id.in_(old_course_ids)
            ).delete(synchronize_session=False)

            ElectiveCourse.query.filter(
                ElectiveCourse.id.in_(old_course_ids)
            ).delete(synchronize_session=False)

    # Получение отредактированных дисциплин из формы
    updated_courses = []
    count = int(request.form.get('to_add_count', 0))
    for i in range(count):
        if request.form.get(f'course_add_{i}') == '1':
            name = request.form.get(f'course_name_{i}', '').strip()
            semester = request.form.get(f'course_semester_{i}')
            if name and semester:
                updated_courses.append({
                    'name': name,
                    'semester': int(semester)
                })

    # Проверка на дубликаты
    old_courses = ElectiveCourse.query.filter_by(direction_id=direction.id).all()
    old_courses_set = set((c.name, c.semester) for c in old_courses)
    new_courses_set = set((c['name'], c['semester']) for c in updated_courses)

    if old_courses_set == new_courses_set:
        flash('Списки дисциплин совпадают, изменений не требуется', 'info')
        session.pop('pending_upload', None)
        return redirect(url_for('manage_courses_bp.manage_courses'))

    # Добавление новых дисциплин
    for course in updated_courses:
        db.session.add(ElectiveCourse(
            name=course['name'],
            semester=course['semester'],
            direction_id=direction.id
        ))

    db.session.commit()
    session.pop('pending_upload', None)
    flash('Данные успешно обновлены', 'success')
    return redirect(url_for('manage_courses_bp.manage_courses'))

@manage_courses_bp.route('/delete-all-courses', methods=['POST'])
def delete_all_courses():
    if request.method == 'POST':
        try:
            # Удаляем все записи в таблице StudentElectiveCourse, связанные с дисциплинами
            StudentElectiveCourse.query.delete()

            # Удаляем все дисциплины из таблицы ElectiveCourse
            ElectiveCourse.query.delete()

            # Фиксируем изменения в базе данных
            db.session.commit()

            flash('Все дисциплины и связанные записи успешно удалены', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Произошла ошибка при удалении дисциплин: {e}', 'error')

        return redirect(url_for('manage_courses_bp.manage_courses'))
