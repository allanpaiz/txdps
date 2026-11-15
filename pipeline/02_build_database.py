import time

import duckdb

import config as C


def main() -> None:
    params = {"{THP_CSV_GLOB}": C.THP_CSV_GLOB.as_posix(), "{TARGET_MONTH}": C.TARGET_MONTH}
    with duckdb.connect(str(C.DB_PATH)) as con:
        for sql_file in sorted(C.SQL_DIR.glob("*.sql")):
            sql = sql_file.read_text()
            for key, value in params.items():
                sql = sql.replace(key, value)
            t0 = time.time()
            con.execute(sql)
            print(f"  {sql_file.name:<28} {time.time() - t0:5.1f}s")

        print(con.sql("""
            SELECT month, count(*) AS stops, sum(n_tickets) AS tickets, sum(n_violation_records) AS violation_records
            FROM stops GROUP BY month ORDER BY month""").df().to_string(index=False))


if __name__ == "__main__":
    main()
