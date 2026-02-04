from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher
import asyncio
import re
import os
import json
import datetime
import requests
import time
from astrbot.api.event import MessageChain

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件，支持金币比例查询和油价查询与计算器。", "v1.2")
class DNF_Plugin(Star):
    # 防止同一进程内重复创建定时任务（多次实例化时仍只启动一次）
    _tasks_started = False
    def __init__(self, context: Context):
        super().__init__(context)
        self.last_avg_ratio = None
        self.ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_avg_ratio.json')
        self.load_last_avg_ratio()
        self.last_sent_avg_ratio = None
        self.sent_ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_sent_avg_ratio.json')
        self.load_last_sent_avg_ratio()
        # 仅在首次实例化时创建后台定时任务，避免重复创建导致重复发送
        if not DNF_Plugin._tasks_started:
            DNF_Plugin._tasks_started = True
            asyncio.get_event_loop().create_task(self.scheduled_task())
            # 每日早上8点检查油价变动并发送通知（启动时会先发送一次）
            asyncio.get_event_loop().create_task(self.oil_price_daily_task())
            # 每隔1小时检查平舆蛋价，且每天仅发送一次（发送给指定QQ好友）
            asyncio.get_event_loop().create_task(self.egg_price_hourly_task())

        # 持久化文件，用于保存上次获取的油价数据，避免重启失效
        self.oil_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_oil_data.json')
        self.last_oil_data = {}
        self.load_last_oil_data()
        # 蛋价推送持久化（记录最后发送日期，格式 YYYY-MM-DD）
        self.egg_sent_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_egg_sent_date.json')
        self.last_egg_sent_date = None
        self.load_last_egg_sent_date()
        # 可配置的监控地区列表，当前仅监控河南
        self.MONITOR_AREAS = ["河南"]
        # 推送目标群组（默认与金币通知相同）
        self.oil_notify_group_id = 101344113
        # 蛋价推送目标群ID（改为群推送）
        self.egg_notify_group_id = 527189909

    def load_last_avg_ratio(self):
        if os.path.exists(self.ratio_file):
            try:
                with open(self.ratio_file, 'r') as f:
                    data = json.load(f)
                    self.last_avg_ratio = data.get('last_avg_ratio')
            except Exception as e:
                logger.error(f"读取上次均价失败: {e}")

    def save_last_avg_ratio(self):
        try:
            with open(self.ratio_file, 'w') as f:
                json.dump({'last_avg_ratio': self.last_avg_ratio}, f)
        except Exception as e:
            logger.error(f"保存上次均价失败: {e}")

    def load_last_sent_avg_ratio(self):
        if os.path.exists(self.sent_ratio_file):
            try:
                with open(self.sent_ratio_file, 'r') as f:
                    data = json.load(f)
                    val = data.get('last_sent_avg_ratio')
                    if val is not None:
                        self.last_sent_avg_ratio = float(val)
            except Exception as e:
                logger.error(f"读取上次发送均价失败: {e}")

    def save_last_sent_avg_ratio(self):
        try:
            with open(self.sent_ratio_file, 'w') as f:
                json.dump({'last_sent_avg_ratio': self.last_sent_avg_ratio}, f)
        except Exception as e:
            logger.error(f"保存上次发送均价失败: {e}")

    def parse_avg_ratio(self, ratio_text):
        match = re.search(r'均价：1元=([\d.]+)万金币', ratio_text)
        if match:
            return float(match.group(1))
        return None

    def load_last_oil_data(self):
        if os.path.exists(self.oil_data_file):
            try:
                with open(self.oil_data_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.last_oil_data = data
            except Exception as e:
                logger.error(f"读取上次油价数据失败: {e}")

    def save_last_oil_data(self):
        try:
            with open(self.oil_data_file, 'w') as f:
                json.dump(self.last_oil_data, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存上次油价数据失败: {e}")

    def load_last_egg_sent_date(self):
        if os.path.exists(self.egg_sent_file):
            try:
                with open(self.egg_sent_file, 'r') as f:
                    data = json.load(f)
                    val = data.get('last_egg_sent_date')
                    if val:
                        self.last_egg_sent_date = str(val)
            except Exception as e:
                logger.error(f"读取上次蛋价发送日期失败: {e}")

    def save_last_egg_sent_date(self):
        try:
            with open(self.egg_sent_file, 'w') as f:
                json.dump({'last_egg_sent_date': self.last_egg_sent_date}, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存上次蛋价发送日期失败: {e}")

    def format_oil_info(self, oil_data):
        # 接受 API 返回的单个地区的 data 字典，格式化为文本
        try:
            s = f"📊 {oil_data.get('name','未知地区')} 油价信息\n"
            s += f"📅 更新时间：{oil_data.get('date','未知')}\n"
            s += f"⛽ 92号汽油：{oil_data.get('p92','-')}元/升\n"
            s += f"⛽ 95号汽油：{oil_data.get('p95','-')}元/升\n"
            s += f"⛽ 98号汽油：{oil_data.get('p98','-')}元/升\n"
            s += f"⛽ 0号柴油：{oil_data.get('p0','-')}元/升\n"
            if oil_data.get('p10') and oil_data['p10'] != "-":
                s += f"⛽ 10号柴油：{oil_data['p10']}元/升\n"
            if oil_data.get('p20') and oil_data['p20'] != "-":
                s += f"⛽ 20号柴油：{oil_data['p20']}元/升\n"
            if oil_data.get('p35') and oil_data['p35'] != "-":
                s += f"⛽ 35号柴油：{oil_data['p35']}元/升\n"
            return s
        except Exception as e:
            logger.error(f"格式化油价信息失败: {e}")
            return ""

    async def fetch_oil_data_for_area(self, area):
        # 返回 API 的 data 字典或 None
        try:
            api_url = "https://www.iamwawa.cn/oilprice/api"
            params = {"area": area}
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == 1 and "data" in data:
                return data["data"]
            else:
                logger.warning(f"获取{area}地区油价失败：{data.get('message','未知错误')}")
                return None
        except Exception as e:
            logger.error(f"获取{area}地区油价异常: {e}")
            return None

    async def oil_price_daily_task(self):
        """每天早上8点查询监控地区油价，启动时会立即发送一次，若与上次数据有变动则发送通知并保存最新数据"""
        # 等待框架就绪（短暂等待），再执行首次发送
        await asyncio.sleep(2)
        try:
            # 尝试获取 aiocqhttp 客户端
            platform = None
            for p in self.context.platform_manager.get_insts():
                if p.meta().name == "aiocqhttp":
                    platform = p
                    break
            client = platform.get_client() if platform else None

            # 启动时发送一次全部监控地区油价（不做变动比较）
            all_infos = []
            for area in self.MONITOR_AREAS:
                oil = await self.fetch_oil_data_for_area(area)
                if oil:
                    all_infos.append(self.format_oil_info(oil))
                    # 更新缓存
                    self.last_oil_data[area] = oil
            if all_infos and client:
                msg = "油价更新通知：\n\n" + "\n".join(all_infos)
                try:
                    await client.send_group_msg(group_id=self.oil_notify_group_id, message=msg)
                except Exception as e:
                    logger.error(f"发送启动时油价通知失败: {e}")
            # 保存首次获取的数据
            self.save_last_oil_data()

            # 主循环：每天在 08:00 触发检查
            while True:
                now = datetime.datetime.now()
                # 计算下一个 08:00 的时间点
                target = now.replace(hour=8, minute=0, second=0, microsecond=0)
                if now >= target:
                    target = target + datetime.timedelta(days=1)
                wait_seconds = (target - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                # 到达 08:00，检查每个监控地区是否有变化
                changed = False
                changed_infos = []
                for area in self.MONITOR_AREAS:
                    oil = await self.fetch_oil_data_for_area(area)
                    if not oil:
                        continue
                    prev = self.last_oil_data.get(area)
                    # 比较关键字段
                    keys = ['p92','p95','p98','p0','p10','p20','p35']
                    diff_found = False
                    if prev is None:
                        diff_found = True
                    else:
                        for k in keys:
                            if str(prev.get(k)) != str(oil.get(k)):
                                diff_found = True
                                break
                    if diff_found:
                        changed = True
                        changed_infos.append(self.format_oil_info(oil))
                        # 更新缓存
                        self.last_oil_data[area] = oil

                if changed and client and changed_infos:
                    msg = "油价更新通知：\n\n" + "\n".join(changed_infos)
                    try:
                        await client.send_group_msg(group_id=self.oil_notify_group_id, message=msg)
                    except Exception as e:
                        logger.error(f"发送油价更新通知失败: {e}")
                    # 保存变动后的数据
                    self.save_last_oil_data()

        except Exception as e:
            logger.error(f"油价每日任务异常: {e}")

    def fetch_egg_prices(self, area_name: str, date_str: str):
        """同步查询指定地区和日期的蛋价列表，返回和之前 handler 相同格式的 items 列表。"""
        base = "http://www.quotn.cn/e/search"
        params = {
            "k": area_name or "",
            "areaName": area_name or "",
            "pDate": date_str,
            "_": str(int(time.time() * 1000)),
        }
        try:
            resp = requests.get(base, params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"fetch_egg_prices 请求失败: {e}")
            return []

        results = []
        try:
            j = resp.json()
        except Exception:
            j = None

        def collect(obj):
            if isinstance(obj, dict):
                for k in ("price", "priceText", "金额"):
                    if k in obj:
                        title = obj.get("title") or obj.get("name") or obj.get("标题") or ""
                        raw = obj.get(k)
                        try:
                            price = float(str(raw))
                        except Exception:
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw or ""))
                            price = float(m.group(1)) if m else None
                        utime_raw = None
                        for tkey in ("uTime", "utime", "u_time", "time", "date", "pubTime", "pubtime", "报价时间"):
                            if tkey in obj and obj.get(tkey):
                                utime_raw = obj.get(tkey)
                                break
                        utime_fmt = None
                        if utime_raw is not None:
                            try:
                                if isinstance(utime_raw, (int, float)) or (isinstance(utime_raw, str) and utime_raw.isdigit()):
                                    n = int(utime_raw)
                                    if n > 10**12:
                                        n = n // 1000
                                    utime_fmt = datetime.datetime.fromtimestamp(n).strftime('%Y-%m-%d %H:%M')
                                else:
                                    utime_fmt = str(utime_raw)[:19]
                            except Exception:
                                utime_fmt = str(utime_raw)
                        results.append({"title": title.strip(), "price": price, "utime": utime_fmt})
                        return True
                for v in obj.values():
                    collect(v)
            elif isinstance(obj, list):
                for it in obj:
                    collect(it)

        parsed_from_list = False
        if isinstance(j, dict):
            body = j.get('body') if isinstance(j.get('body'), dict) else None
            data_list = None
            if body and isinstance(body.get('dataList'), list):
                data_list = body.get('dataList')
            elif isinstance(j.get('dataList'), list):
                data_list = j.get('dataList')

            if isinstance(data_list, list) and data_list:
                for item in data_list:
                    if not isinstance(item, dict):
                        continue
                    cName = item.get('cName') or ''
                    aName = item.get('aName') or ''
                    title = f"{cName}{aName}" if (cName or aName) else (item.get('aName') or item.get('name') or '')
                    price = None
                    if 'tPrice' in item and item.get('tPrice') not in (None, ''):
                        try:
                            price = float(str(item.get('tPrice')))
                        except Exception:
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get('tPrice') or ""))
                            price = float(m.group(1)) if m else None
                    else:
                        for pk in ("price", "priceText", "金额", "yPrice"):
                            if pk in item and item.get(pk) not in (None, ""):
                                try:
                                    price = float(str(item.get(pk)))
                                except Exception:
                                    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get(pk) or ""))
                                    price = float(m.group(1)) if m else None
                                break
                    up_time = item.get('upTime') or None
                    yprice = None
                    if 'yPrice' in item and item.get('yPrice') not in (None, ''):
                        try:
                            yprice = float(str(item.get('yPrice')))
                        except Exception:
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get('yPrice') or ""))
                            yprice = float(m.group(1)) if m else None
                    results.append({"title": title.strip(), "price": price, "upTime": up_time, "cName": cName, "aName": aName, "yPrice": yprice})
                parsed_from_list = True
        if not parsed_from_list:
            collect(j)

        if not results:
            text = resp.text
            pattern = re.compile(r"([\u4e00-\u9fff\w\-\s\/（）()]{2,60}?)\s*[：:\-\s]{0,3}\s*([0-9]+(?:\.[0-9]+)?)\s*(?:元|元/斤|元/公斤)")
            found = pattern.findall(text)
            for title, price_s in found:
                try:
                    price = float(price_s)
                except Exception:
                    price = None
                results.append({"title": title.strip(), "price": price})

        return results

    async def egg_price_hourly_task(self):
        """每隔1小时检查平舆蛋价，且每天仅发送一次到指定好友。"""
        await asyncio.sleep(2)
        try:
            while True:
                try:
                    today = datetime.date.today().strftime('%Y-%m-%d')
                    # 若今日已发送则跳过
                    if self.last_egg_sent_date == today:
                        await asyncio.sleep(3600)
                        continue

                    # 查询今日蛋价
                    area = '平舆'
                    date_str = datetime.date.today().strftime('%Y%m%d')
                    items = self.fetch_egg_prices(area, date_str)
                    if not items:
                        await asyncio.sleep(3600)
                        continue

                    # 构建推送内容，最多10条
                    lines = []
                    lines.append(f"返回查询结果（{today}前10条）：")
                    cnt = 0
                    seen = set()
                    for it in items:
                        c = it.get('cName') or ''
                        a = it.get('aName') or ''
                        if c and a:
                            title = f"{c}-{a}" if c != a else c
                        elif c or a:
                            title = c or a
                        else:
                            title = it.get('title') or '-'
                        price = it.get('price')
                        up_time = it.get('upTime')
                        y_price = it.get('yPrice')
                        # 计算简短涨跌
                        change_mark_short = '平'
                        try:
                            if isinstance(price, (int, float)) and isinstance(y_price, (int, float)) and y_price != 0:
                                diff_pct = (price - y_price) / y_price * 100
                                pct = round(abs(diff_pct))
                                if diff_pct > 0:
                                    change_mark_short = f"涨{pct}%"
                                elif diff_pct < 0:
                                    change_mark_short = f"跌{pct}%"
                                else:
                                    change_mark_short = '平'
                        except Exception:
                            change_mark_short = '平'

                        key = (title, float(price) if isinstance(price, (int, float)) else price, up_time)
                        if key in seen:
                            continue
                        seen.add(key)
                        cnt += 1
                        if cnt > 10:
                            break
                        price_text = f"{price:.2f}元" if isinstance(price, (int, float)) else (str(price) if price is not None else "-")
                        if up_time:
                            lines.append(f"{cnt} .{title} {up_time} {price_text}({change_mark_short})")
                        else:
                            lines.append(f"{cnt} .{title} {price_text}({change_mark_short})")

                    msg = "\n".join(lines)

                    # 获取 aiocqhttp 客户端并发送私信
                    platform = None
                    for p in self.context.platform_manager.get_insts():
                        if p.meta().name == "aiocqhttp":
                            platform = p
                            break
                    client = platform.get_client() if platform else None
                    if client:
                        try:
                            await client.send_group_msg(group_id=self.egg_notify_group_id, message=msg)
                            self.last_egg_sent_date = today
                            self.save_last_egg_sent_date()
                        except Exception as e:
                            logger.error(f"发送蛋价群消息失败: {e}")

                except Exception as e:
                    logger.error(f"egg_price_hourly_task 内部异常: {e}")

                # 每隔1小时检查一次
                await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"蛋价每小时任务异常: {e}")

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    async def scheduled_task(self):
        logger.info("定时任务已启动，每分钟检测金币比例波动")
        while True:
            try:
                platform = None
                for p in self.context.platform_manager.get_insts():
                    if p.meta().name == "aiocqhttp":
                        platform = p
                        break
                if platform:
                    client = platform.get_client()
                    ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
                    avg_ratio = self.parse_avg_ratio(ratio_text)
                    if avg_ratio is not None:
                        avg_ratio_fmt = f"{avg_ratio:.2f}"
                        send_msg = False
                        msg = None
                        if self.last_sent_avg_ratio is not None:
                            diff = avg_ratio - self.last_sent_avg_ratio
                            diff_fmt = f"{diff:+.2f}"
                            if abs(diff) >= 2:
                                msg = f"金币比例波动：上次发送均价 {self.last_sent_avg_ratio:.2f}，本次均价 {avg_ratio_fmt}，变动 {diff_fmt}万金币"
                                send_msg = True
                            # 否则不发消息
                        else:
                            msg = f"首次监控，当前金币均价：{avg_ratio_fmt}万金币"
                            send_msg = True
                        if send_msg:
                            await client.send_group_msg(
                                group_id=101344113,
                                message=msg
                            )
                            self.last_sent_avg_ratio = avg_ratio
                            self.save_last_sent_avg_ratio()
                        self.last_avg_ratio = avg_ratio
                        self.save_last_avg_ratio()
                    else:
                        logger.info("未能获取到金币均价数据")
                logger.info("定时检测完成")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"定时任务执行失败: {e}")
                await asyncio.sleep(30)

    @filter.command("金币比例")
    async def dnf_gold_ratio(self, event):
        """查询 DNF 金币比例""" 
        user_name = event.get_sender_name()
        ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
        yield event.plain_result(ratio_text)

    # 已移除独立的 DNF 帮助指令（不再注册 'dnf帮助'）

    @filter.command("油价")
    async def oil_price(self, event):
        """查询油价信息或计算行驶成本"""
        try:
            # 获取消息内容
            message = ""
            if hasattr(event, 'message_str'):
                message = event.message_str
                logger.info(f"通过event.message_str获取到消息: {message}")
            elif hasattr(event, 'get_message_str'):
                message = event.get_message_str()
                logger.info(f"通过event.get_message_str()获取到消息: {message}")
            elif hasattr(event, 'message_obj'):
                message = str(event.message_obj)
                logger.info(f"通过event.message_obj获取到消息: {message}")
            else:
                message = str(event)
                logger.info(f"通过str(event)获取到消息: {message}")
            
            # 智能解析消息内容
            # 格式1: 油价 河南 (查询地区油价)
            # 格式2: 油价 河南 92 7.5 (计算行驶成本: 地区 油号 百公里油耗)
            # 格式3: 油价 河南 95 8.0 100 (计算行驶成本: 地区 油号 百公里油耗 行驶里程)
            
            # 尝试匹配计算格式
            calc_match = re.search(r'油价\s+([^\s]+)\s+(\d+)\s+([\d.]+)(?:\s+(\d+))?', message)
            if calc_match:
                # 油价计算模式
                area = calc_match.group(1)  # 地区
                oil_type = calc_match.group(2)  # 油号
                consumption = float(calc_match.group(3))  # 百公里油耗
                distance = int(calc_match.group(4)) if calc_match.group(4) else 100  # 行驶里程，默认100公里
                
                # 先获取该地区的油价信息
                oil_price = await self.get_oil_price_by_type(area, oil_type)
                if oil_price is None:
                    yield event.plain_result(f"❌ 无法获取{area}地区{oil_type}号油的价格信息")
                    return
                
                result = self.calculate_oil_cost(oil_type, oil_price, consumption, distance, area)
                yield event.plain_result(result)
                return
            
            # 尝试匹配地区查询格式（只匹配纯地区名，不包含数字）
            area_match = re.search(r'油价\s+([^\s\d]+)$', message)
            if area_match:
                # 地区油价查询模式
                area = area_match.group(1).strip()
                
                # 构建API请求URL
                api_url = "https://www.iamwawa.cn/oilprice/api"
                params = {"area": area}
                
                # 发送HTTP请求
                response = requests.get(api_url, params=params, timeout=10)
                response.raise_for_status()
                
                # 解析返回的JSON数据
                data = response.json()
                
                if data.get("status") == 1 and "data" in data:
                    oil_data = data["data"]
                    
                    # 构建油价信息文本
                    oil_info = f"📊 {oil_data['name']}油价信息\n"
                    oil_info += f"📅 更新时间：{oil_data['date']}\n"
                    oil_info += f"⛽ 92号汽油：{oil_data['p92']}元/升\n"
                    oil_info += f"⛽ 95号汽油：{oil_data['p95']}元/升\n"
                    oil_info += f"⛽ 98号汽油：{oil_data['p98']}元/升\n"
                    oil_info += f"⛽ 0号柴油：{oil_data['p0']}元/升\n"
                    
                    # 添加其他油品信息（如果存在且不为"-"）
                    if oil_data.get('p10') and oil_data['p10'] != "-":
                        oil_info += f"⛽ 10号柴油：{oil_data['p10']}元/升\n"
                    if oil_data.get('p20') and oil_data['p20'] != "-":
                        oil_info += f"⛽ 20号柴油：{oil_data['p20']}元/升\n"
                    if oil_data.get('p35') and oil_data['p35'] != "-":
                        oil_info += f"⛽ 35号柴油：{oil_data['p35']}元/升\n"
                    
                    oil_info += f"🔄 下次更新时间：{oil_data['next_update_time']}\n\n"
                    # 不在查询结果中附带使用示例，使用单独指令 '油价帮助' 查看详细说明
                    
                    yield event.plain_result(oil_info)
                else:
                    yield event.plain_result(f"查询失败：{data.get('message', '未知错误')}")
            else:
                # 参数不正确，提示正确的使用方法
                error_text = "❌ 参数格式不正确\n\n"
                error_text += "📋 正确格式：\n"
                error_text += "• 油价 地区名 - 查询地区油价\n"
                error_text += "• 油价 地区名 油号 油耗 - 计算行驶成本\n"
                error_text += "• 油价 地区名 油号 油耗 里程 - 计算指定里程成本\n"
                
                yield event.plain_result(error_text)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"油价查询请求失败: {e}")
            yield event.plain_result("油价查询请求失败，请稍后重试")
        except json.JSONDecodeError as e:
            logger.error(f"油价数据解析失败: {e}")
            yield event.plain_result("油价数据解析失败，请稍后重试")
        except Exception as e:
            logger.error(f"油价查询异常: {e}")
            yield event.plain_result("油价查询出现异常，请稍后重试")

    @filter.command("蛋价")
    async def egg_price(self, event):
        """查询蛋价，示例：
        • 蛋价 河南        -> 查询河南地区（默认关键词：鸡蛋）
        • 蛋价 河南 20260129 -> 指定日期查询
        """
        try:
            # 获取消息内容（与油价处理方式一致）
            message = ""
            if hasattr(event, 'message_str'):
                message = event.message_str
            elif hasattr(event, 'get_message_str'):
                message = event.get_message_str()
            elif hasattr(event, 'message_obj'):
                message = str(event.message_obj)
            else:
                message = str(event)

            # 解析参数：蛋价 [地区] [可选日期 YYYYMMDD]
            # 支持：
            #  - 蛋价 驻马店
            #  - 蛋价 驻马店 20260129
            #  - 蛋价 20260129
            args = ""
            if '蛋价' in message:
                args = message.split('蛋价', 1)[1].strip()
            else:
                args = message.strip()

            if not args:
                area = ""
                pDate = None
            else:
                parts = args.split()
                # 若最后一项是 8 位数字视作日期
                if parts and parts[-1].isdigit() and len(parts[-1]) == 8:
                    pDate = parts[-1]
                    area = " ".join(parts[:-1]).strip()
                else:
                    pDate = None
                    area = " ".join(parts).strip()

            # 清理地区：优先提取首个中文连续块，去掉后缀
            if area:
                m_cn = re.search(r"[\u4e00-\u9fff]+", area)
                area = m_cn.group(0) if m_cn else area

            base = "http://www.quotn.cn/e/search"
            # 查询并比较今日/昨日价格
            def query_egg_prices(area_name: str, date_str: str):
                """返回列表，每项 {'title':..., 'price': float or None}。"""
                params = {
                    "k": area_name or "",
                    "areaName": area_name or "",
                    "pDate": date_str,
                    "_": str(int(time.time() * 1000)),
                }
                resp = requests.get(base, params=params, timeout=10)
                resp.raise_for_status()
                results = []
                try:
                    j = resp.json()
                except Exception:
                    j = None

                def collect(obj):
                    if isinstance(obj, dict):
                        for k in ("price", "priceText", "金额"):
                            if k in obj:
                                title = obj.get("title") or obj.get("name") or obj.get("标题") or ""
                                raw = obj.get(k)
                                try:
                                    price = float(str(raw))
                                except Exception:
                                    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw or ""))
                                    price = float(m.group(1)) if m else None
                                # 尝试提取时间字段（可能的字段名）
                                utime_raw = None
                                for tkey in ("uTime", "utime", "u_time", "time", "date", "pubTime", "pubtime", "报价时间"):
                                    if tkey in obj and obj.get(tkey):
                                        utime_raw = obj.get(tkey)
                                        break
                                utime_fmt = None
                                if utime_raw is not None:
                                    try:
                                        # 若为纯数字字符串或数字，尝试解析为时间戳（秒或毫秒）
                                        if isinstance(utime_raw, (int, float)) or (isinstance(utime_raw, str) and utime_raw.isdigit()):
                                            n = int(utime_raw)
                                            # 若为毫秒级时间戳（> 1e12），则转换为秒
                                            if n > 10**12:
                                                n = n // 1000
                                            utime_fmt = datetime.datetime.fromtimestamp(n).strftime('%Y-%m-%d %H:%M')
                                        else:
                                            # 否则直接使用字符串形式（裁剪过长）
                                            utime_fmt = str(utime_raw)[:19]
                                    except Exception:
                                        utime_fmt = str(utime_raw)
                                results.append({"title": title.strip(), "price": price, "utime": utime_fmt})
                                return True
                        for v in obj.values():
                            collect(v)
                    elif isinstance(obj, list):
                        for it in obj:
                            collect(it)

                # 优先解析常见的 'body.dataList' 或顶级 'dataList' 列表结构
                parsed_from_list = False
                if isinstance(j, dict):
                    body = j.get('body') if isinstance(j.get('body'), dict) else None
                    data_list = None
                    if body and isinstance(body.get('dataList'), list):
                        data_list = body.get('dataList')
                    elif isinstance(j.get('dataList'), list):
                        data_list = j.get('dataList')

                    if isinstance(data_list, list) and data_list:
                        for item in data_list:
                            if not isinstance(item, dict):
                                continue
                            # 地址使用 cName + aName
                            cName = item.get('cName') or ''
                            aName = item.get('aName') or ''
                            title = f"{cName}{aName}" if (cName or aName) else (item.get('aName') or item.get('name') or '')
                            # 尝试获取价格字段（使用 tPrice）
                            price = None
                            if 'tPrice' in item and item.get('tPrice') not in (None, ''):
                                try:
                                    price = float(str(item.get('tPrice')))
                                except Exception:
                                    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get('tPrice') or ""))
                                    price = float(m.group(1)) if m else None
                            else:
                                for pk in ("price", "priceText", "金额", "yPrice"):
                                    if pk in item and item.get(pk) not in (None, ""):
                                        try:
                                            price = float(str(item.get(pk)))
                                        except Exception:
                                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get(pk) or ""))
                                            price = float(m.group(1)) if m else None
                                        break
                            # upTime 字段直接使用（不加标签）
                            up_time = item.get('upTime') or None
                            # yPrice 可作为昨日价格参考
                            yprice = None
                            if 'yPrice' in item and item.get('yPrice') not in (None, ''):
                                try:
                                    yprice = float(str(item.get('yPrice')))
                                except Exception:
                                    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(item.get('yPrice') or ""))
                                    yprice = float(m.group(1)) if m else None
                            results.append({"title": title.strip(), "price": price, "upTime": up_time, "cName": cName, "aName": aName, "yPrice": yprice})
                        parsed_from_list = True
                if not parsed_from_list:
                    collect(j)

                if not results:
                    text = resp.text
                    pattern = re.compile(r"([\u4e00-\u9fff\w\-\s\/（）()]{2,60}?)\s*[：:\-\s]{0,3}\s*([0-9]+(?:\.[0-9]+)?)\s*(?:元|元/斤|元/公斤)")
                    found = pattern.findall(text)
                    for title, price_s in found:
                        try:
                            price = float(price_s)
                        except Exception:
                            price = None
                        results.append({"title": title.strip(), "price": price})

                return results

            # 计算日期字符串
            today_str = pDate or datetime.date.today().strftime("%Y%m%d")
            try:
                dt = datetime.datetime.strptime(today_str, "%Y%m%d").date()
            except Exception:
                dt = datetime.date.today()
            yesterday = dt - datetime.timedelta(days=1)
            yesterday_str = yesterday.strftime("%Y%m%d")

            today_items = query_egg_prices(area, today_str)
            yesterday_items = query_egg_prices(area, yesterday_str)

            def average_price(items):
                vals = [it.get("price") for it in items if isinstance(it.get("price"), (int, float))]
                if not vals:
                    return None
                return sum(vals) / len(vals)

            avg_today = average_price(today_items)
            avg_yesterday = average_price(yesterday_items)

            lines = []
            # 不显示均价比较，直接返回查询结果标题（含日期）
            lines.append(f"返回查询结果（{dt.strftime('%Y-%m-%d')}前10条）：")

            # 列出今日条目（最多10条），并根据昨日价格计算涨跌标记
            if today_items:
                lines.append("\n查询结果（今日前10条）：")
                # 构建昨日价格索引
                y_map = {}
                for y in yesterday_items:
                    key = (y.get('cName') or '', y.get('aName') or '',)
                    if y.get('price') is not None:
                        y_map[key] = y.get('price')
                    elif y.get('yPrice') is not None:
                        y_map[key] = y.get('yPrice')

                seen = set()
                cnt = 0
                for it in today_items:
                    c = it.get('cName') or ''
                    a = it.get('aName') or ''
                    # 地址格式：城市-区县（若相同则只显示一个）
                    if c and a:
                        title = f"{c}-{a}" if c != a else c
                    elif c or a:
                        title = c or a
                    else:
                        title = it.get('title') or '-'
                    price = it.get('price')
                    up_time = it.get('upTime')
                    # 获取昨日价格优先使用今日项中的 yPrice 字段，否则尝试匹配索引
                    y_price = None
                    if it.get('yPrice') is not None:
                        y_price = it.get('yPrice')
                    else:
                        key = (c, a)
                        y_price = y_map.get(key)

                    # 计算涨跌标记（简洁形式，用于括号内显示）
                    change_mark_short = '平'
                    try:
                        if isinstance(price, (int, float)) and isinstance(y_price, (int, float)) and y_price != 0:
                            diff_pct = (price - y_price) / y_price * 100
                            pct = round(abs(diff_pct))
                            if diff_pct > 0:
                                change_mark_short = f"涨{pct}%"
                            elif diff_pct < 0:
                                change_mark_short = f"跌{pct}%"
                            else:
                                change_mark_short = '平'
                    except Exception:
                        change_mark_short = '平'

                    key = (title, float(price) if isinstance(price, (int, float)) else price, up_time)
                    if key in seen:
                        continue
                    seen.add(key)
                    cnt += 1
                    if cnt > 10:
                        break
                    price_text = f"{price:.2f}元" if isinstance(price, (int, float)) else (str(price) if price is not None else "-")
                    # 输出格式示例：1 .驻马店-平舆 11:37 4.00元(平)
                    if up_time:
                        lines.append(f"{cnt} .{title} {up_time} {price_text}({change_mark_short})")
                    else:
                        lines.append(f"{cnt} .{title} {price_text}({change_mark_short})")
            yield event.plain_result("\n".join(lines))

        except requests.exceptions.RequestException as e:
            logger.error(f"蛋价查询请求失败: {e}")
            yield event.plain_result("蛋价查询请求失败，请稍后重试")
        except Exception as e:
            logger.error(f"蛋价查询异常: {e}")
            yield event.plain_result("蛋价查询出现异常，请稍后重试")

    # 已移除 '油价帮助' 指令，应答中不再引用独立帮助命令

    async def get_oil_price_by_type(self, area, oil_type):
        """根据地区和油号获取油价"""
        try:
            # 构建API请求URL
            api_url = "https://www.iamwawa.cn/oilprice/api"
            params = {"area": area}
            
            # 发送HTTP请求
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            
            # 解析返回的JSON数据
            data = response.json()
            
            if data.get("status") == 1 and "data" in data:
                oil_data = data["data"]
                
                # 根据油号获取对应价格
                price_key = f"p{oil_type}"
                if price_key in oil_data and oil_data[price_key] != "-":
                    return float(oil_data[price_key])
                else:
                    logger.warning(f"地区{area}的{oil_type}号油价格不存在或为-")
                    return None
            else:
                logger.error(f"获取{area}地区油价失败：{data.get('message', '未知错误')}")
                return None
                
        except Exception as e:
            logger.error(f"获取{area}地区{oil_type}号油价异常: {e}")
            return None

    def calculate_oil_cost(self, oil_type, oil_price, consumption, distance, area=""):
        """计算油价成本"""
        try:
            # 计算每公里油耗
            consumption_per_km = consumption / 100
            
            # 计算总油耗
            total_consumption = consumption_per_km * distance
            
            # 计算总成本
            total_cost = total_consumption * oil_price
            
            # 计算每公里成本
            cost_per_km = total_cost / distance
            
            # 构建结果文本
            result = f"🛢️ 油价成本计算器\n\n"
            if area:
                result += f"📍 地区：{area}\n"
            result += f"📊 计算参数：\n"
            result += f"• 油品类型：{oil_type}号\n"
            result += f"• 油价：{oil_price}元/升\n"
            result += f"• 百公里油耗：{consumption}升\n"
            result += f"• 行驶里程：{distance}公里\n\n"
            result += f"💰 计算结果：\n"
            result += f"• 每公里油耗：{consumption_per_km:.3f}升\n"
            result += f"• 总油耗：{total_consumption:.2f}升\n"
            result += f"• 每公里成本：{cost_per_km:.2f}元\n"
            result += f"• 总成本：{total_cost:.2f}元\n\n"
            
            # 添加一些实用的参考信息
            if distance == 100:
                result += f"💡 百公里成本：{total_cost:.2f}元\n"
            
            # 根据油耗给出建议
            if consumption <= 6:
                result += "✅ 油耗表现优秀！"
            elif consumption <= 8:
                result += "👍 油耗表现良好"
            elif consumption <= 10:
                result += "⚠️ 油耗表现一般"
            else:
                result += "🔴 油耗偏高，建议检查车况"
            
            return result
            
        except Exception as e:
            logger.error(f"油价计算异常: {e}")
            return f"计算失败：{e}"

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
