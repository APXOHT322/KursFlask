"""
Фикстуры для тестирования
"""
import pytest
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.app import create_app
from app.models import db, User, Direction, ElectiveCourse


@pytest.fixture(scope='session')
def app():
    """Создание тестового приложения"""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'test_secret_key'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.test'

    # Сохраняем db в app для доступа в тестах
    app.db = db

    return app


@pytest.fixture(scope='session')
def _db(app):
    """База данных для тестов"""
    with app.app_context():
        db.create_all()
        yield db
        db.drop_all()


@pytest.fixture(scope='function')
def db_session(_db):
    """Сессия базы данных для каждого теста"""
    yield _db.session
    _db.session.rollback()
    _db.session.expunge_all()


@pytest.fixture
def client(app):
    """Тестовый клиент"""
    return app.test_client()


@pytest.fixture
def test_direction(db_session):
    """Создание тестового направления"""
    direction = Direction(
        code="01.03.01",
        name="Математика",
        year=2022
    )
    db_session.add(direction)
    db_session.commit()
    return direction


@pytest.fixture
def test_user(db_session, test_direction):
    """Создание тестового студента"""
    user = User(
        fio="Тестовый Студент",
        login="test_student",
        password="test_hash",
        role="Студент",
        group_number="2201",
        admission_year=2022,
        direction_id=test_direction.id
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_admin(db_session):
    """Создание тестового администратора"""
    admin = User(
        fio="Администратор",
        login="admin",
        password="admin_hash",
        role="Администратор",
        group_number=None,
        admission_year=None
    )
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def test_director(db_session):
    """Создание тестового специалиста дирекции"""
    director = User(
        fio="Специалист Дирекции",
        login="director",
        password="director_hash",
        role="Специалист дирекции",
        group_number=None,
        admission_year=None
    )
    db_session.add(director)
    db_session.commit()
    return director


@pytest.fixture
def test_elective_course(db_session, test_direction):
    """Создание тестовой дисциплины"""
    course = ElectiveCourse(
        name="Машинное обучение",
        code="ML101",
        direction_id=test_direction.id,
        year=2022,
        max_students=30,
        semester=3,
        teacher_fio="Преподаватель Петров"
    )
    db_session.add(course)
    db_session.commit()
    return course


@pytest.fixture
def authenticated_client(client, test_user):
    """Клиент с авторизованным пользователем"""
    with client.session_transaction() as session:
        session['user_id'] = test_user.id
    return client


@pytest.fixture
def authenticated_admin(client, test_admin):
    """Клиент с авторизованным администратором"""
    with client.session_transaction() as session:
        session['user_id'] = test_admin.id
    return client


@pytest.fixture
def authenticated_director(client, test_director):
    """Клиент с авторизованным специалистом дирекции"""
    with client.session_transaction() as session:
        session['user_id'] = test_director.id
    return client


@pytest.fixture
def mock_ldap(monkeypatch):
    """Мок для LDAP аутентификации"""

    def mock_authenticate(uid, password):
        return uid == "test_user" and password == "test_pass"

    def mock_get_user_info(uid):
        return {
            "uid": uid,
            "fio": "Тестовый Пользователь",
            "role": "Студент",
            "group": "2201",
            "is_student": True
        }

    monkeypatch.setattr('app.ldap_auth.ldap_authenticate', mock_authenticate)
    monkeypatch.setattr('app.ldap_auth.ldap_get_user_info', mock_get_user_info)