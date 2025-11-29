import requests
import re


class DnfGoldRatioFetcher:
    @staticmethod
    def fetch_gold_ratio_text():
        """
        使用 DD373 的内部接口获取商品列表（前 5 条），并返回与原爬虫相同的文本格式，
        使调用方无需修改：

        例：
        1  商店编号...        1元=70.1234万金币
        ...
        ----------------------
        均价：1元=xx.xxxx万金币
        数据来源：DD373
        """
        url = "https://goods.dd373.com/Api/Goods/UserCenter/ApiGetShopList?gameid=7100fe84-ef8a-4f0a-8547-a8682a78e555&GameOtherId=56dd5e29-5119-4c0d-a94e-a532f550fa7d_2ab7245b-048f-4d5e-abd2-90d3700290ed&GameShopTypeId=739b5eb8-3d96-4b09-9a06-5a8983a6adf4"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # 校验返回结构
            result_list = None
            if isinstance(data, dict):
                sd = data.get("StatusData")
                if isinstance(sd, dict):
                    rd = sd.get("ResultData")
                    if isinstance(rd, list):
                        result_list = rd

            if not result_list:
                return "未能从接口获取商品数据。"

            # 取前 5 条
            items = result_list[:5]
            ratios = []
            results = []
            for idx, it in enumerate(items, 1):
                # 使用 trade + amount（带单位）作为标题，不使用 shopno
                trade = (it.get("trade") or "").strip()
                amount_field = it.get("amount") or it.get("number") or ""
                # 格式化 amount：若能解析为数字且为整数则不显示小数点
                try:
                    af = float(amount_field)
                    if af.is_integer():
                        amount_str = str(int(af))
                    else:
                        # 去掉不必要的尾随 0
                        amount_str = ("%f" % af).rstrip('0').rstrip('.')
                except Exception:
                    amount_str = str(amount_field)
                unit = it.get("unit") or ""
                # 如果 trade 为 '担保'，则不显示该词，只显示数量和单位
                if trade == "担保":
                    title_text = f"{amount_str}{unit}".strip()
                elif trade:
                    title_text = f"{trade} {amount_str}{unit}".strip()
                else:
                    title_text = f"{amount_str}{unit}".strip()

                # singleprice 是 元 / 单位（示例中为 元/万金币）
                singleprice_raw = it.get("singleprice")
                try:
                    singleprice = float(singleprice_raw)
                except Exception:
                    singleprice = None

                ratio_val = None
                if singleprice and singleprice > 0:
                    # 1 元 = (1 / singleprice) 单位（例如 万金币）
                    ratio_val = 1.0 / singleprice
                    ratios.append(ratio_val)

                ratio_text = f"1元={ratio_val:.4f}万金币" if ratio_val else "1元= - 万金币"
                results.append(f"{idx:<2} {title_text:<18} {ratio_text:<16}")

            avg_ratio = sum(ratios) / len(ratios) if ratios else 0
            results.append("-" * 38)
            results.append(f"均价：1元={avg_ratio:.4f}万金币")
            results.append("数据来源：DD373")
            return "\n".join(results)
        except Exception as e:
            return f"查询金币比例失败：{e}"
