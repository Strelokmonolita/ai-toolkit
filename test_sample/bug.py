import sqlite3


def average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)


def find_user(db_path, name):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return cur.fetchall()


def read_first_line(path):
    f = open(path)
    return f.readline()


print(average([]))
