from __future__ import annotations
import argparse
import os
import time

from pathlib import Path
import psycopg


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = os.getenv("DATABASE_URL", "postgresql://dzmobile:dzmobile@localhost:5432/dzmobile")
TABLES = ["subscribers", "offers", "recharges", "subscriptions", "daily_usage"]


def copy_csv( cur: psycopg.Cursor, table: str, csv_path: Path)-> None:
    with csv_path.open("r", encoding="utf-8") as f:
        header = f.readline().strip()           
        columns = ", ".join(header.split(","))
        with cur.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
            while chunk := f.read(1 << 20):      
                copy.write(chunk)



def main():
    parser = argparse.ArgumentParser(description="Load DzMobile CSVs into PostgreSQL")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    missing = [t for t in TABLES if not (args.raw / f"{t}.csv").exists()]
    if missing:
        raise SystemExit(f"Missing CSVs in {args.raw}: {missing}. Run data/generate.py first.")

    with psycopg.connect(args.db) as conn:
        with conn.cursor() as cur:
            print("Creating schema...")
            cur.execute((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))

            for table in TABLES:
                start = time.time()
                copy_csv(cur, table, args.raw / f"{table}.csv")
                print(f"  loaded {table:<14} in {time.time() - start:5.1f}s")

            cur.execute("ANALYZE")

            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"{table:<14} {cur.fetchone()[0]:>10,} ")
        conn.commit()

    print("\nDone")


if __name__ == "__main__":
    main()

