"""
Скрипт для исправления структуры таблицы direction
"""

import pymysql

def fix_direction_table():
    print("=" * 60)
    print("ИСПРАВЛЕНИЕ СТРУКТУРЫ ТАБЛИЦЫ DIRECTION")
    print("=" * 60)
    
    try:
        # Подключение к базе данных
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='OoRa2Oob',
            database='Kurs',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 1. Проверяем существующие индексы
            print("1. Проверяем индексы таблицы 'direction'...")
            cursor.execute("SHOW INDEX FROM direction")
            indexes = cursor.fetchall()
            
            for index in indexes:
                print(f"   - {index['Key_name']}: {index['Column_name']}")
            
            # 2. Удаляем старый уникальный индекс на code, если он существует
            print("\n2. Удаляем старый уникальный индекс 'code'...")
            try:
                cursor.execute("DROP INDEX code ON direction")
                print("   ✓ Индекс 'code' удален")
            except Exception as e:
                if "check that column/key exists" in str(e).lower() or "can't drop" in str(e).lower():
                    print("   ⚠ Индекс 'code' не существует или не может быть удален")
                else:
                    print(f"   ⚠ Ошибка: {e}")
            
            # 3. Проверяем существование составного уникального ключа
            print("\n3. Проверяем составной уникальный ключ 'unique_direction_year'...")
            cursor.execute("SHOW INDEX FROM direction WHERE Key_name = 'unique_direction_year'")
            composite_index = cursor.fetchone()
            
            if composite_index:
                print("   ✓ Составной ключ 'unique_direction_year' уже существует")
            else:
                # 4. Добавляем составной уникальный ключ (code, year)
                print("4. Добавляем составной уникальный ключ (code, year)...")
                try:
                    cursor.execute("""
                    ALTER TABLE direction 
                    ADD CONSTRAINT unique_direction_year 
                    UNIQUE (code, year)
                    """)
                    print("   ✓ Составной ключ 'unique_direction_year' добавлен")
                except Exception as e:
                    print(f"   ⚠ Ошибка: {e}")
            
            # 5. Проверяем данные на дубликаты
            print("\n5. Проверяем данные на дубликаты...")
            cursor.execute("""
            SELECT code, year, COUNT(*) as count 
            FROM direction 
            GROUP BY code, year 
            HAVING COUNT(*) > 1
            """)
            duplicates = cursor.fetchall()
            
            if duplicates:
                print("   ⚠ Найдены дубликаты:")
                for dup in duplicates:
                    print(f"     - {dup['code']} ({dup['year']}): {dup['count']} записей")
                print("   ⚠ Удалите дубликаты вручную через базу данных")
            else:
                print("   ✓ Дубликатов не найдено")
            
            connection.commit()
            
            print("\n" + "=" * 60)
            print("ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
            print("=" * 60)
            
    except pymysql.Error as e:
        print(f"\n❌ ОШИБКА ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ: {e}")
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        try:
            connection.rollback()
        except:
            pass
    finally:
        try:
            connection.close()
        except:
            pass

if __name__ == '__main__':
    fix_direction_table()