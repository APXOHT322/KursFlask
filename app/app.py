from flask import Flask, render_template, request, redirect, url_for, session, abort
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from app.models import db, User, ElectiveCourse, StudentElectiveCourse, Settings, Direction
from app.manage_courses import manage_courses_bp
from app.student_courses import student_courses_bp
from app.reports import reports_bp
from sqlalchemy import text
from functools import wraps
from datetime import datetime

def create_app():
    app = Flask(__name__)

    # Конфигурация — замените при необходимости
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:OoRa2Oob@localhost/Kurs'
    app.config['SECRET_KEY'] = 'your_secret_key'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    bcrypt = Bcrypt(app)
    jwt = JWTManager(app)

    # Регистрируем блюпринты С ПРЕФИКСОМ
    try:
        app.register_blueprint(manage_courses_bp, url_prefix='/')
    except Exception:
        pass
    try:
        app.register_blueprint(student_courses_bp, url_prefix='/')
    except Exception:
        pass
    try:
        app.register_blueprint(reports_bp, url_prefix='/')
    except Exception:
        pass

    # Список доступных ролей
    AVAILABLE_ROLES = ['Студент', 'Преподаватель', 'Специалист дирекции']

    # --- декоратор для проверки ролей ---
    def roles_required(*role_names):
        def decorator(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                user_id = session.get('user_id')
                if not user_id:
                    return redirect(url_for('login'))
                user = User.query.get(user_id)
                if not user:
                    return redirect(url_for('login'))
                if not any(user.has_role(r) for r in role_names):
                    abort(403)
                return f(*args, **kwargs)
            return wrapper
        return decorator

    @app.route('/')
    def index():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))

        user = User.query.get(user_id)
        if not user:
            session.pop('user_id', None)
            return redirect(url_for('login'))

        return redirect(url_for('dashboard'))

    @app.route('/dashboard')
    def dashboard():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        if not user:
            return redirect(url_for('login'))
        return render_template('dashboard.html', user=user)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            login_input = request.form.get('login')
            password_input = request.form.get('password')

            user = User.query.filter_by(login=login_input).first()

            if not user or not bcrypt.check_password_hash(user.password, password_input):
                return render_template('login.html', error="Неверный логин или пароль")

            session['user_id'] = user.id
            return redirect(url_for('dashboard'))

        return render_template('login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        directions = Direction.query.order_by(Direction.code, Direction.year).all()
        
        if request.method == 'POST':
            fio = request.form.get('fio', '').strip()
            login = request.form.get('login', '').strip()
            password = request.form.get('password', '')
            selected_roles = request.form.getlist('roles')

            if not selected_roles:
                return render_template(
                    'register.html',
                    error='Выберите хотя бы одну роль',
                    directions=directions,
                    roles=AVAILABLE_ROLES,
                    form=request.form,
                    selected_roles=[],
                    current_year=datetime.now().year
                )

            is_student = any(r.strip().lower() == 'студент' for r in selected_roles)
            admission_year = None
            
            if is_student:
                direction_id = request.form.get('direction')
                group_number = request.form.get('group_number', '').strip()
                admission_year_input = request.form.get('admission_year', '').strip()
                
                # Проверяем обязательные поля для студентов
                if not direction_id or not group_number or not admission_year_input:
                    return render_template(
                        'register.html',
                        error='Для роли "Студент" все поля обязательны',
                        directions=directions,
                        roles=AVAILABLE_ROLES,
                        form=request.form,
                        selected_roles=selected_roles,
                        current_year=datetime.now().year
                    )
                
                # Проверяем и преобразуем год поступления
                try:
                    admission_year = int(admission_year_input)
                    # Проверяем корректность года
                    current_year = datetime.now().year
                    if admission_year < 2000 or admission_year > current_year + 1:
                        return render_template(
                            'register.html',
                            error=f'Некорректный год поступления. Должен быть между 2000 и {current_year + 1}',
                            directions=directions,
                            roles=AVAILABLE_ROLES,
                            form=request.form,
                            selected_roles=selected_roles,
                            direction_id=direction_id,
                            group_number=group_number,
                            current_year=current_year
                        )
                except ValueError:
                    return render_template(
                        'register.html',
                        error='Год поступления должен быть числом',
                        directions=directions,
                        roles=AVAILABLE_ROLES,
                        form=request.form,
                        selected_roles=selected_roles,
                        direction_id=direction_id,
                        group_number=group_number,
                        current_year=datetime.now().year
                    )
                
                # Проверяем, что у выбранного направления есть учебный план нужного года
                selected_direction = Direction.query.get(direction_id)
                if selected_direction:
                    # Ищем направление с нужным годом
                    correct_direction = Direction.query.filter_by(
                        code=selected_direction.code,
                        year=admission_year
                    ).first()
                    
                    if correct_direction:
                        direction_id = correct_direction.id
                    else:
                        # Если нет направления с нужным годом, показываем ошибку
                        return render_template(
                            'register.html',
                            error=f'Для направления "{selected_direction.name}" нет учебного плана {admission_year} года',
                            directions=directions,
                            roles=AVAILABLE_ROLES,
                            form=request.form,
                            selected_roles=selected_roles,
                            direction_id=direction_id,
                            group_number=group_number,
                            current_year=datetime.now().year
                        )
            else:
                direction_id = None
                group_number = None
                admission_year = None

            # Проверка существующего логина
            if User.query.filter_by(login=login).first():
                return render_template(
                    'register.html',
                    error='Пользователь с таким логином уже существует',
                    directions=directions,
                    roles=AVAILABLE_ROLES,
                    form=request.form,
                    selected_roles=selected_roles,
                    direction_id=direction_id,
                    group_number=group_number,
                    current_year=datetime.now().year
                )

            # Создание нового пользователя
            normalized_roles = ','.join([r.strip() for r in selected_roles if r and r.strip()])
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            
            new_user = User(
                fio=fio,
                login=login,
                password=hashed_password,
                direction_id=direction_id,
                group_number=group_number,
                role=normalized_roles,
                admission_year=admission_year
            )
            
            try:
                db.session.add(new_user)
                db.session.commit()
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                return render_template(
                    'register.html',
                    error=f'Ошибка при сохранении пользователя: {str(e)}',
                    directions=directions,
                    roles=AVAILABLE_ROLES,
                    form=request.form,
                    selected_roles=selected_roles,
                    current_year=datetime.now().year
                )

        # GET — передаём пустую форму
        return render_template(
            'register.html',
            directions=directions,
            roles=AVAILABLE_ROLES,
            form={},
            selected_roles=[],
            current_year=datetime.now().year
        )

    @app.route('/logout')
    def logout():
        session.pop('user_id', None)
        return redirect(url_for('login'))

    @app.route('/manage_students_courses', methods=['GET', 'POST'])
    @roles_required('Специалист дирекции')
    def manage_students_courses():
        if request.method == 'POST':
            student_id = request.form.get('student')
            course_id = request.form.get('course')
            action = request.form.get('action')

            if student_id and course_id:
                if action == 'assign':
                    insert_query = text("""
                        INSERT INTO student_elective_courses (user_id, elective_course_id)
                        VALUES (:student_id, :course_id)
                    """)
                    db.session.execute(insert_query, {'student_id': student_id, 'course_id': course_id})
                elif action == 'remove':
                    delete_query = text("""
                        DELETE FROM student_elective_courses
                        WHERE user_id = :student_id AND elective_course_id = :course_id
                    """)
                    db.session.execute(delete_query, {'student_id': student_id, 'course_id': course_id})

                db.session.commit()

        # Используем SQL для фильтрации студентов
        student_query = text("""
            SELECT id, fio FROM users 
            WHERE role LIKE '%Студент%' OR role LIKE '%студент%'
            ORDER BY fio
        """)
        students = db.session.execute(student_query).fetchall()

        # Курсы
        course_query = text("SELECT id, name FROM elective_course")
        courses = db.session.execute(course_query).fetchall()

        # Назначенные курсы
        assigned_query = text("""
            SELECT users.fio, elective_course.name AS course_name
            FROM student_elective_courses
            JOIN users ON student_elective_courses.user_id = users.id
            JOIN elective_course ON student_elective_courses.elective_course_id = elective_course.id
            ORDER BY users.fio;
        """)
        assigned = db.session.execute(assigned_query).fetchall()

        return render_template(
            'manage_students_courses.html',
            students=students,
            courses=courses,
            assigned=assigned
        )

    @app.route('/director_dashboard')
    @roles_required('Специалист дирекции')
    def director_dashboard():
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('login'))
        user = User.query.get(user_id)
        return render_template('director_dashboard.html', user=user)

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('403.html'), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)