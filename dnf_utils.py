import requests
from bs4 import BeautifulSoup
import re

class DnfGoldRatioFetcher:
    @staticmethod
    def fetch_gold_ratio_text():
        url = "https://www.dd373.com/s-rbg22w-091pt7-091pt7-0-0-0-42hcun-0-0-0-0-0-1-0-5-0.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            box = soup.find(class_="good-list-box")
            if not box:
                return "未找到商品列表容器。"
            items = box.find_all(class_="goods-list-item", limit=5)
            if not items:
                return "未找到商品条目。"
            ratios = []
            results = []
            for idx, item in enumerate(items, 1):
                # 比例：width233 p-l30 > font12 colorFF5
                ratio_parent = item.find(class_="width233 p-l30")
                ratio_tag = ratio_parent.find(class_="font12 colorFF5") if ratio_parent else None
                ratio_text = ratio_tag.get_text(strip=True) if ratio_tag else ""
                match = re.search(r"1元=([\d.]+)万金币", ratio_text)
                ratio_val = float(match.group(1)) if match else None
                if ratio_val:
                    ratios.append(ratio_val)
                # 标题
                title_tag = item.find(class_="game-account-flag")
                title_text = title_tag.get_text(strip=True) if title_tag else ""
                title_text = re.sub(r"【.*?】", "", title_text)
                # PC端表格风格
                results.append(f"{idx:<2} {title_text:<18} {ratio_text:<16}")
            avg_ratio = sum(ratios) / len(ratios) if ratios else 0
            results.append("-" * 38)
            results.append(f"均价：1元={avg_ratio:.4f}万金币")
            results.append("数据来源：DD373")
            return "\n".join(results)
        except Exception as e:
            return f"查询金币比例失败：{e}"

