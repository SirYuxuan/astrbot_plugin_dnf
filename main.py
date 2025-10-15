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
from astrbot.api.event import MessageChain

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件，支持金币比例查询和油价查询与计算器。", "v1.2")
class DNF_Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.last_avg_ratio = None
        self.ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_avg_ratio.json')
        self.load_last_avg_ratio()
        self.last_sent_avg_ratio = None
        self.sent_ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_sent_avg_ratio.json')
        self.load_last_sent_avg_ratio()
        asyncio.get_event_loop().create_task(self.scheduled_task())
        # 每日早上8点检查油价变动并发送通知（启动时会先发送一次）
        asyncio.get_event_loop().create_task(self.oil_price_daily_task())

        # 持久化文件，用于保存上次获取的油价数据，避免重启失效
        self.oil_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_oil_data.json')
        self.last_oil_data = {}
        self.load_last_oil_data()
        # 可配置的监控地区列表，当前仅监控河南
        self.MONITOR_AREAS = ["河南"]
        # 推送目标群组（默认与金币通知相同）
        self.oil_notify_group_id = 101344113

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
