import requests
import time
import logging

# Configure Logging
logger = logging.getLogger(__name__)

def fetch_stock_list_sina():
    """
    Fetches the full list of A-share stock codes from Sina Finance API.
    Returns a list of dicts (e.g., [{"code": "000001", "name": "平安银行"}, ...]).

    This method is more reliable than TDX for getting the complete list
    because TDX servers often return partial data or fail for specific markets (SH).
    """
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    all_stocks = {} # Use dict to dedup by code
    page = 1
    batch_size = 80
    max_retries = 3

    logger.info("Fetching full stock list from Sina Finance...")

    consecutive_failures = 0

    while True:
        params = {
            'page': page,
            'num': batch_size,
            'sort': 'symbol',
            'asc': 1,
            'node': 'hs_a', # Shanghai & Shenzhen A-shares
            'symbol': ''
        }

        success = False
        for attempt in range(max_retries):
            try:
                r = requests.get(url, params=params, timeout=15)
                if r.status_code != 200:
                    logger.warning(f"Sina API returned status {r.status_code} on page {page} (Attempt {attempt+1})")
                    time.sleep(1)
                    continue

                data = r.json()
                if not data:
                    # End of list reached (or empty page)
                    # To be safe, check if page > 1. If page 1 empty, maybe error.
                    if page == 1:
                        logger.warning("Sina returned empty list on page 1.")
                        return []
                    success = True
                    consecutive_failures = 0
                    # Break the retry loop and also the main loop (end of data)
                    return list(all_stocks.values()) # Done!

                # Extract codes
                count = 0
                for item in data:
                    code = item.get('code')
                    name = item.get('name')
                    if not code: continue

                    # Filter A-shares
                    # SH: 60xxxx, 688xxx (STAR)
                    # SZ: 00xxxx, 30xxxx (ChiNext)
                    # Exclude Beijing (8xx, 4xx, 9xx) & B-shares (900/200)
                    if code.startswith(('60', '68', '00', '30')):
                        all_stocks[code] = {"code": code, "name": name}
                        count += 1

                if page % 10 == 0:
                    logger.info(f"Fetched page {page}, total stocks so far: {len(all_stocks)}")

                success = True
                consecutive_failures = 0
                break # Success, break retry loop

            except Exception as e:
                logger.warning(f"Error fetching page {page} (Attempt {attempt+1}): {e}")
                time.sleep(2)

        if not success:
            logger.error(f"Failed to fetch page {page} after {max_retries} attempts.")
            consecutive_failures += 1
            if consecutive_failures > 5:
                logger.error("Too many consecutive failures. Stopping fetch.")
                break
            # Continue to next page anyway? Missing 80 stocks is better than missing 4000.
            # But usually if one page fails, next might too if blocked.
            # However, logic dictates we try.
            pass

        page += 1
        time.sleep(0.1)

    # Return list
    result = list(all_stocks.values())

    logger.info(f"Successfully fetched {len(result)} A-share stocks from Sina.")
    return result

def fetch_stock_list():
    """
    Unified interface.
    """
    return fetch_stock_list_sina()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    codes = fetch_stock_list()
    print(f"Total: {len(codes)}")
    if len(codes) > 0:
        print(f"Sample: {codes[:5]}")
