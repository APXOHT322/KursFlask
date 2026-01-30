from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from app.models import db, User, ElectiveCourse, StudentElectiveCourse, Settings, Direction
from datetime import datetime
student_courses_bp = Blueprint('student_courses', __name__, template_folder='templates')

@student_courses_bp.route('/student_courses', methods=['GET', 'POST'])
def student_courses():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Студент'):
        return redirect(url_for('dashboard'))
    
    # Определяем год поступления студента из номера группы
    admission_year = user.admission_year
    if not admission_year and user.group_number:
        try:
            # Первые две цифры группы - год поступления
            year_short = int(user.group_number[:2])
            admission_year = 2000 + year_short
            # Сохраняем в БД
            user.admission_year = admission_year
            db.session.commit()
        except:
            admission_year = datetime.now().year
    
    # Получаем направление студента с учетом года поступления
    direction = None
    if user.direction_id:
        # Сначала получаем направление студента
        student_direction = Direction.query.get(user.direction_id)
        if student_direction:
            # Ищем направление с таким же кодом, но нужного года
            direction = Direction.query.filter_by(
                code=student_direction.code,
                year=admission_year
            ).first()
            
            # Если не нашли, используем текущее направление
            if not direction:
                direction = student_direction
    
    if not direction:
        flash('Для вашего направления и года поступления не найден учебный план', 'error')
        return redirect(url_for('dashboard'))
    
    # Определяем семестр
    group_number = user.group_number
    try:
        # Берем 3-ю цифру из номера группы как курс (2301 -> курс 0?)
        if len(group_number) >= 3:
            course_year = int(group_number[2])
        else:
            # По умолчанию 1 курс
            course_year = 1
    except (IndexError, ValueError):
        course_year = 1
    
    # Определение текущего семестра
    current_month = datetime.now().month
    is_spring = 2 <= current_month <= 7  # Весенний семестр
    semester = course_year * 2 if is_spring else course_year * 2 - 1

    # Фильтрация по направлению (с нужным годом) и семестру
    elective_courses = ElectiveCourse.query.filter(
        ElectiveCourse.direction_id == direction.id,
        ElectiveCourse.semester == semester
    ).all()

    course_pairs = [elective_courses[i:i+2] for i in range(0, len(elective_courses), 2)]

    chosen_courses = ElectiveCourse.query.join(StudentElectiveCourse).filter(
        StudentElectiveCourse.user_id == user.id
    ).all()
    chosen_course_ids = {course.id for course in chosen_courses}

    has_chosen_courses = bool(chosen_courses)

    if request.method == 'POST':
        selected_ids = []
        for i, pair in enumerate(course_pairs):
            selected_id = request.form.get(f'pair_{i}')
            if not selected_id:
                flash(f"Пожалуйста, выберите дисциплину в паре {i + 1}.", "error")
                return redirect(url_for('student_courses.student_courses'))

            selected_ids.append(int(selected_id))

        StudentElectiveCourse.query.filter_by(user_id=user.id).delete()

        for selected_id in selected_ids:
            student_course = StudentElectiveCourse(user_id=user.id, elective_course_id=selected_id)
            db.session.add(student_course)

        db.session.commit()
        flash("Ваш выбор сохранён.")
        return redirect(url_for('student_courses.student_courses'))

    settings = Settings.query.first()
    is_enrollment_open = settings.is_enrollment_open if settings else False

    return render_template('choose_courses.html',
                           user=user,
                           course_pairs=list(enumerate(course_pairs)),
                           chosen_courses=chosen_courses,
                           chosen_course_ids=chosen_course_ids,
                           is_enrollment_open=is_enrollment_open,
                           has_chosen_courses=has_chosen_courses,
                           admission_year=admission_year)



@student_courses_bp.route('/cancel_enrollment', methods=['POST'])
def cancel_enrollment():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    if not user.has_role('Студент'):
        return redirect(url_for('dashboard'))

    # Проверка, открыта ли запись
    settings = Settings.query.first()
    if not settings or not settings.is_enrollment_open:
        flash('Запись на дисциплины закрыта, отменить выбор невозможно.', 'error')
        return redirect(url_for('student_courses.student_courses'))

    # Удаляем все выбранные дисциплины
    StudentElectiveCourse.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    flash('Все выбранные дисциплины были отменены. Вы можете выбрать новые дисциплины.', 'success')
    return redirect(url_for('student_courses.student_courses'))