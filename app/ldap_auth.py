"""
LDAP-авторизация для Flask-приложения.

Сервер:  ldap.cs.prv  (SSL, порт 636)
Base DN: ou=people,dc=cs,dc=karelia,dc=ru

Логика определения роли из DN пользователя:
  - DN содержит "ou=students" → роль "Студент", группа извлекается из DN
  - Иначе                     → роль "Преподаватель"
  - Роль "Специалист дирекции" назначается вручную администратором в БД

JIT-provisioning (при первом входе):
  - Ищем пользователя в БД по login (= uid из LDAP)
  - Если не нашли — создаём запись автоматически
  - Если нашли     — обновляем fio из LDAP (sn / cn)
"""

import re
import logging

from ldap3 import Server, Connection, ALL, SUBTREE, Tls
import ssl

log = logging.getLogger(__name__)

# ── Константы ────────────────────────────────────────────────────────────────

LDAP_HOST        = "ldap.cs.prv"
LDAP_PORT        = 636          # LDAPS; смените на 389 и уберите use_ssl, если plain LDAP
LDAP_USE_SSL     = True
LDAP_BASE_DN     = "ou=people,dc=cs,dc=karelia,dc=ru"

# Регулярка для извлечения номера группы из DN
# Пример DN: uid=ivanov,ou=2241,ou=students,ou=people,dc=cs,dc=karelia,dc=ru
_GROUP_RE = re.compile(r"ou=(22[\d\-А-Яа-яzZА-Яа-яzZ]{3,6})", re.IGNORECASE)


# ── Вспомогательные функции ──────────────────────────────────────────────────

def _make_connection(bind_dn: str = None, password: str = None) -> Connection:
    """Создаёт LDAP-соединение. Без аргументов — анонимное (для поиска)."""
    tls = Tls(validate=ssl.CERT_NONE)          # В проде замените на CERT_REQUIRED
    server = Server(LDAP_HOST, port=LDAP_PORT,
                    use_ssl=LDAP_USE_SSL, tls=tls,
                    get_info=ALL, connect_timeout=5)
    if bind_dn and password:
        conn = Connection(server, user=bind_dn, password=password,
                          auto_bind=True, raise_exceptions=False)
    else:
        conn = Connection(server, auto_bind=True, raise_exceptions=False)
    return conn


def _find_user_dn(uid: str) -> str | None:
    """
    Ищет DN пользователя по uid.
    Возвращает строку DN или None, если пользователь не найден.
    """
    try:
        conn = _make_connection()
        conn.search(
            search_base=LDAP_BASE_DN,
            search_filter=f"(uid={uid})",
            search_scope=SUBTREE,
            attributes=["uid", "sn", "cn", "initials", "givenName"],
        )
        if conn.entries:
            return conn.entries[0].entry_dn, conn.entries[0]
        return None, None
    except Exception as e:
        log.error("LDAP search error: %s", e)
        return None, None
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def _extract_group(dn: str) -> str | None:
    """Извлекает номер группы из DN студента."""
    m = _GROUP_RE.search(dn)
    return m.group(1) if m else None


def _is_student(dn: str) -> bool:
    return "ou=students" in dn.lower()


# ── Публичный интерфейс ──────────────────────────────────────────────────────

def ldap_authenticate(uid: str, password: str) -> bool:
    """
    Проверяет логин/пароль через LDAP bind.
    Возвращает True при успехе, False — при неверных данных или ошибке.
    """
    dn, _ = _find_user_dn(uid)
    if not dn:
        log.info("LDAP: user '%s' not found", uid)
        return False
    try:
        conn = _make_connection(bind_dn=dn, password=password)
        result = conn.bound
        log.info("LDAP bind for '%s': %s", uid, result)
        return bool(result)
    except Exception as e:
        log.error("LDAP bind error for '%s': %s", uid, e)
        return False
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def ldap_get_user_info(uid: str) -> dict | None:
    """
    Возвращает словарь с атрибутами пользователя из LDAP:
      {
        "uid":         str,
        "fio":         str,   # sn + initials или cn
        "dn":          str,
        "is_student":  bool,
        "group":       str | None,
        "role":        str,   # "Студент" или "Преподаватель"
      }
    Возвращает None, если пользователь не найден.
    """
    dn, entry = _find_user_dn(uid)
    if not dn:
        return None

    # Собираем ФИО: предпочитаем sn + initials, иначе cn
    try:
        sn       = str(entry["sn"].value)       if entry["sn"]       else ""
        initials = str(entry["initials"].value) if entry["initials"] else ""
        cn       = str(entry["cn"].value)       if entry["cn"]       else uid
        fio = f"{sn} {initials}".strip() if sn else cn
    except Exception:
        fio = uid

    student   = _is_student(dn)
    group     = _extract_group(dn) if student else None
    role      = "Студент" if student else "Преподаватель"

    return {
        "uid":        uid,
        "fio":        fio,
        "dn":         dn,
        "is_student": student,
        "group":      group,
        "role":       role,
    }
