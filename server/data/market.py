import akshare as ak
import pandas as pd
from pypinyin import pinyin, Style, lazy_pinyin
import logging
import os
from server.data.mock import generate_mock_data

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_all_stock_codes():
    """
    获取A股全市场股票代码及名称，并生成拼音首字母。
    返回格式: [{"code": "000001", "name": "平安银行", "pinyin": "payh", "full_pinyin": "pinganyinhang"}, ...]
    """
    use_mock_fallback = os.environ.get("USE_MOCK_FALLBACK", "False").lower() == "true"

    try:
        logger.info("Fetching all A-share stock info...")

        if use_mock_fallback:
             # 返回少量模拟数据
             return [
                 {"code": "000001", "name": "平安银行", "pinyin": "payh", "full_pinyin": "pinganyinhang"},
                 {"code": "600519", "name": "贵州茅台", "pinyin": "gzmt", "full_pinyin": "guizhoumaotai"},
                 {"code": "000002", "name": "万科A", "pinyin": "wka", "full_pinyin": "wankea"}
             ]

        # akshare.stock_info_a_code_name() 返回 DataFrame: code, name
        df = ak.stock_info_a_code_name()

        results = []
        for _, row in df.iterrows():
            code = str(row['code'])
            name = str(row['name'])

            # 生成拼音
            # pinyin returns list of lists, e.g. [['zhong'], ['guo']]
            py_full_list = lazy_pinyin(name)
            # full pinyin
            full_pinyin = "".join(py_full_list)

            # 首字母 (取每个词首字母)
            initials = "".join([w[0] for w in py_full_list])

            # 组合字典
            # 客户端 UI 需要: code, name, pinyin, full_pinyin
            results.append({
                "code": code,
                "name": name,
                "pinyin": initials,
                "full_pinyin": full_pinyin
            })

        logger.info(f"Fetched {len(results)} stocks.")
        return results

    except Exception as e:
        logger.error(f"Error fetching stock list: {e}")
        # 如果也是网络问题，可以降级
        return []

if __name__ == "__main__":
    # Test
    # export USE_MOCK_FALLBACK=True to test in sandbox
    os.environ["USE_MOCK_FALLBACK"] = "True"
    stocks = get_all_stock_codes()
    print(f"Total stocks: {len(stocks)}")
    if stocks:
        print(stocks[0])
