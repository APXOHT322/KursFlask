from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'  # корректное имя таблицы

    id = db.Column(db.Integer, primary_key=True)
    fio = db.Column(db.String(255), nullable=False)
    # direction_id и group_number могут быть NULL, т.к. не все пользователи — студенты
    direction_id = db.Column(db.Integer, db.ForeignKey('direction.id'), nullable=True)
    group_number = db.Column(db.String(50), nullable=True)
    login = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    # role — строка с ролями через запятую (например: "Студент,Преподаватель")
    role = db.Column(db.String(255), nullable=True)
    # Год поступления студента (для студентов)
    admission_year = db.Column(db.Integer, nullable=True)

    direction = db.relationship('Direction', backref=db.backref('users', lazy=True))

    def __repr__(self):
        return f"<User {self.login}>"

    # --- Работа с ролями ---

    def get_roles_list(self):
        """
        Возвращает список ролей пользователя в нормализованном виде.
        Пример: "Студент,Преподаватель" -> ['Студент', 'Преподаватель']
        """
        if not self.role:
            return []
        # Убираем пробелы вокруг и игнорируем пустые
        return [r.strip() for r in self.role.split(',') if r and r.strip()]

    def has_role(self, role_name):
        """
        Проверка наличия роли (регистронезависимо).
        """
        if not role_name or not self.role:
            return False
        role_name = role_name.strip().lower()
        # Разбиваем строку ролей и проверяем каждую
        roles = self.role.split(',')
        for role in roles:
            if role.strip().lower() == role_name:
                return True
        return False

    def add_role(self, role_name):
        """
        Добавляет роль (если ещё нет). Сохраняет нормализованную строку.
        """
        if not role_name or not role_name.strip():
            return
        roles = self.get_roles_list()
        normalized = role_name.strip()
        if all(r.strip().lower() != normalized.lower() for r in roles):
            roles.append(normalized)
            self.role = ','.join(roles)

    def remove_role(self, role_name):
        """
        Убирает роль (если есть).
        """
        if not self.role:
            return
        role_name = role_name.strip().lower()
        roles = [r for r in self.get_roles_list() if r.strip().lower() != role_name]
        self.role = ','.join(roles) if roles else None

    def set_roles_from_list(self, roles_list):
        """
        Присваивает роли из списка (нормализует).
        """
        if not roles_list:
            self.role = None
        else:
            normalized = [r.strip() for r in roles_list if r and r.strip()]
            self.role = ','.join(normalized) if normalized else None

class Direction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)  # Убрано unique=True
    name = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=True)  # Год учебного плана
    elective_courses = db.relationship('ElectiveCourse', backref='direction', lazy=True)
    
    # Составной уникальный ключ (code + year)
    __table_args__ = (
        db.UniqueConstraint('code', 'year', name='unique_direction_year'),
    )

    def __repr__(self):
        return f"<Direction {self.code} ({self.year})>"

class ElectiveCourse(db.Model):
    __tablename__ = 'elective_course'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.Integer)
    direction_id = db.Column(db.Integer, db.ForeignKey('direction.id'), nullable=False)

class StudentElectiveCourse(db.Model):
    __tablename__ = 'student_elective_courses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    elective_course_id = db.Column(db.Integer, db.ForeignKey('elective_course.id'), nullable=False)

    user = db.relationship('User', backref=db.backref('elective_courses', lazy=True))
    elective_course = db.relationship('ElectiveCourse', backref=db.backref('students', lazy=True, cascade='all, delete'))

    def __repr__(self):
        return f"<StudentElectiveCourse user_id={self.user_id}, elective_course_id={self.elective_course_id}>"

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_enrollment_open = db.Column(db.Boolean, default=True)