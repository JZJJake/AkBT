import sqlite3
import pandas as pd
import os
import logging
from typing import Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path="market_data.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """初始化数据库表结构"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 创建单大表 stock_daily_qfq
        # 字段: code, date, open, close, high, low, volume
        # 联合唯一索引: (code, date)
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS stock_daily_qfq (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,
            PRIMARY KEY (code, date)
        );
        """
        cursor.execute(create_table_sql)

        conn.commit()
        conn.close()

    def save_stock_data(self, code: str, df: pd.DataFrame):
        """
        保存股票数据（支持增量更新）。
        使用 INSERT OR REPLACE 覆盖相同日期的记录。
        """
        if df.empty:
            logger.warning(f"Empty DataFrame provided for {code}, skipping save.")
            return

        conn = self.get_connection()
        try:
            with conn: # 自动提交事务
                cursor = conn.cursor()

                # df 索引是 Date (datetime)，我们需要将其转换为字符串 (YYYY-MM-DD)
                records = []
                for date_idx, row in df.iterrows():
                    # date_idx is Timestamp
                    date_str = date_idx.strftime('%Y-%m-%d')
                    records.append((
                        code,
                        date_str,
                        float(row['Open']),
                        float(row['Close']),
                        float(row['High']),
                        float(row['Low']),
                        float(row['Volume'])
                    ))

                logger.info(f"Upserting {len(records)} records for {code}...")
                # 使用 REPLACE INTO 来处理重复键 (code, date)
                upsert_sql = """
                INSERT OR REPLACE INTO stock_daily_qfq (code, date, open, close, high, low, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                cursor.executemany(upsert_sql, records)

            logger.info(f"Successfully saved data for {code}.")

        except Exception as e:
            logger.error(f"Error saving data for {code}: {e}")
            raise e
        finally:
            conn.close()

    def get_stock_data(self, code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        查询股票数据。
        """
        conn = self.get_connection()
        try:
            query = "SELECT date, open, close, high, low, volume FROM stock_daily_qfq WHERE code = ?"
            params = [code]

            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)

            query += " ORDER BY date ASC"

            df = pd.read_sql_query(query, conn, params=params)

            if not df.empty:
                # 确保 date 为 datetime 类型
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.index.name = 'Date'

                # 重命名列以匹配系统标准 (首字母大写)
                df.rename(columns={
                    "open": "Open",
                    "close": "Close",
                    "high": "High",
                    "low": "Low",
                    "volume": "Volume"
                }, inplace=True)

            return df

        except Exception as e:
            logger.error(f"Error retrieving data for {code}: {e}")
            return pd.DataFrame()
        finally:
            conn.close()

    def get_latest_date(self, code: str) -> Optional[str]:
        """
        获取该股票在数据库中的最新日期 (YYYY-MM-DD)。
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM stock_daily_qfq WHERE code = ?", (code,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error checking latest date for {code}: {e}")
            return None
        finally:
            conn.close()
