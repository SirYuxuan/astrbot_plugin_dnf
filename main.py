from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher
import asyncio
import re
import os
import json
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
            # 格式2: 油价 92 8.5 7.5 (计算行驶成本: 油号 油价 百公里油耗)
            # 格式3: 油价 95 8.2 8.0 100 (计算行驶成本: 油号 油价 百公里油耗 行驶里程)
            
            # 尝试匹配计算格式
            calc_match = re.search(r'油价\s+(\d+)\s+([\d.]+)\s+([\d.]+)(?:\s+(\d+))?', message)
            if calc_match:
                # 油价计算模式
                oil_type = calc_match.group(1)  # 油号
                oil_price = float(calc_match.group(2))  # 油价
                consumption = float(calc_match.group(3))  # 百公里油耗
                distance = int(calc_match.group(4)) if calc_match.group(4) else 100  # 行驶里程，默认100公里
                
                result = self.calculate_oil_cost(oil_type, oil_price, consumption, distance)
                yield event.plain_result(result)
                return
            
            # 尝试匹配地区查询格式
            area_match = re.search(r'油价\s+(.+)', message)
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
                    oil_info += "💡 使用提示：\n"
                    oil_info += "• 油价 河南 - 查询地区油价\n"
                    oil_info += "• 油价 92 8.5 7.5 - 计算92号汽油8.5元/升，百公里油耗7.5升的行驶成本\n"
                    oil_info += "• 油价 95 8.2 8.0 100 - 计算95号汽油8.2元/升，百公里油耗8.0升，行驶100公里的成本"
                    
                    yield event.plain_result(oil_info)
                else:
                    yield event.plain_result(f"查询失败：{data.get('message', '未知错误')}")
            else:
                # 显示使用说明
                help_text = "🚗 油价查询与计算器\n\n"
                help_text += "📋 使用方法：\n\n"
                help_text += "1️⃣ 查询地区油价：\n"
                help_text += "   油价 河南\n"
                help_text += "   油价 山东\n"
                help_text += "   油价 北京\n\n"
                help_text += "2️⃣ 计算行驶成本：\n"
                help_text += "   油价 92 8.5 7.5\n"
                help_text += "   (92号汽油，8.5元/升，百公里油耗7.5升)\n\n"
                help_text += "3️⃣ 计算指定里程成本：\n"
                help_text += "   油价 95 8.2 8.0 100\n"
                help_text += "   (95号汽油，8.2元/升，百公里油耗8.0升，行驶100公里)\n\n"
                help_text += "💡 油耗参考：\n"
                help_text += "• 小型车：5-8升/百公里\n"
                help_text += "• 中型车：7-10升/百公里\n"
                help_text += "• 大型车：10-15升/百公里\n"
                help_text += "• SUV：8-12升/百公里"
                
                yield event.plain_result(help_text)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"油价查询请求失败: {e}")
            yield event.plain_result("油价查询请求失败，请稍后重试")
        except json.JSONDecodeError as e:
            logger.error(f"油价数据解析失败: {e}")
            yield event.plain_result("油价数据解析失败，请稍后重试")
        except Exception as e:
            logger.error(f"油价查询异常: {e}")
            yield event.plain_result("油价查询出现异常，请稍后重试")

    def calculate_oil_cost(self, oil_type, oil_price, consumption, distance):
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
