# -*- coding: utf-8 -*-
"""
蜻蜓志愿数据查询 - Client OpenClaw Skill

功能：
1. 验证API Key（识别客户、验证权限）
2. 接收用户问题
3. 转发到Server OpenClaw
4. 原封不动返回答案
5. 三必填条件提醒

部署位置：Client OpenClaw的skills目录
"""

import os
import time
import uuid
import requests
from typing import Dict, Optional, List

from config import SERVER_URL, TIMEOUT, RETRIES


# ============ 转发核心 ============
class QingtingQuerySkill:
    """
    蜻蜓志愿数据查询Skill
    
    工作流程：
    1. 接收用户问题
    2. 检查API Key
    3. 检查是否需要三必填条件提醒
    4. 转发到Server OpenClaw
    5. 返回答案
    """
    
    def __init__(self, api_key: str = None, server_url: str = None):
        self.api_key = api_key or os.getenv("QINGTING_API_KEY", "")
        self.server_url = (server_url or SERVER_URL).rstrip('/')
        self.timeout = TIMEOUT
        self.retries = RETRIES
    
    def _make_request(self, user_id: str, session_id: str,
                     question: str, context: List[Dict] = None) -> Dict:
        """发送请求到Server OpenClaw"""
        url = f"{self.server_url}/api/v1/chat"
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "question": question,
            "context": context or []
        }
        
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }
        
        last_error = None
        for attempt in range(self.retries):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    headers=headers
                )
                
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 401:
                    return {
                        "success": False,
                        "answer": "API Key无效或已过期，请检查配置或联系管理员。"
                    }
                elif resp.status_code >= 500:
                    last_error = f"Server错误: {resp.status_code}"
                    continue
                else:
                    return {
                        "success": False,
                        "answer": f"请求失败：{resp.status_code}"
                    }
            
            except requests.exceptions.Timeout:
                last_error = "请求超时"
                continue
            except requests.exceptions.ConnectionError:
                last_error = "无法连接到服务器"
                continue
            except Exception as e:
                last_error = str(e)
                continue
        
        return {
            "success": False,
            "answer": f"连接服务器失败：{last_error}。请稍后再试。"
        }
    
    def _check_conditions(self, question: str) -> Optional[str]:
        """
        检查三必填条件
        
        Returns:
            如果缺少条件，返回追问消息；否则返回None
        """
        q = question.lower()
        
        recommend_keywords = ["志愿", "推荐", "方案", "填报", "生成"]
        has_recommend = any(kw in q for kw in recommend_keywords)
        
        if not has_recommend:
            return None
        
        provinces = ["辽宁", "山东", "四川", "河南", "广东", "江苏", "浙江",
                    "河北", "湖北", "湖南", "安徽", "福建", "江西", "山西",
                    "陕西", "甘肃", "吉林", "黑龙江", "北京", "天津", "上海",
                    "重庆", "贵州", "云南", "广西", "海南", "内蒙古", "宁夏", "青海", "新疆"]
        
        has_province = any(prov in q for prov in provinces)
        
        natures = ["物理", "历史", "理科", "文科"]
        has_nature = any(nat in q for nat in natures)
        
        import re
        has_score = bool(re.search(r"\d{3}分", q))
        has_rank = "位次" in q or "名" in q
        
        missing = []
        if not has_province:
            missing.append("省份")
        if not has_nature:
            missing.append("科类（物理类/历史类）")
        if not has_score and not has_rank:
            missing.append("分数或位次")
        
        if missing:
            lines = ["⚠️ 为了给您提供准确的推荐，请补充以下信息："]
            for i, m in enumerate(missing, 1):
                lines.append(f"  {i}. {m}")
            lines.append("")
            lines.append("请告诉我您的完整信息，例如：辽宁物理类520分能上什么学校？")
            return "\n".join(lines)
        
        return None
    
    def chat(self, user_input: str, user_id: str = None,
             session_id: str = None) -> Dict:
        """
        处理用户消息
        """
        # 检查API Key
        if not self.api_key:
            return {
                "success": False,
                "answer": "⚠️ 请先配置您的API Key才能使用蜻蜓志愿数据查询服务。\n\n如需API Key请联系管理员。"
            }
        
        # 生成ID
        if not user_id:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
        if not session_id:
            session_id = f"sess_{int(time.time())}"
        
        # 检查三必填条件
        condition_warning = self._check_conditions(user_input)
        if condition_warning:
            return {
                "success": True,
                "answer": condition_warning,
                "warning": True
            }
        
        # 转发到Server
        result = self._make_request(user_id, session_id, user_input)
        
        if result.get("success"):
            return {
                "success": True,
                "answer": result.get("answer", ""),
                "intent": result.get("intent"),
                "conditions": result.get("conditions", {})
            }
        else:
            return {
                "success": False,
                "answer": result.get("answer", "处理失败"),
                "error": result.get("error")
            }
    
    def health_check(self) -> bool:
        """检查Server连接"""
        try:
            resp = requests.get(
                f"{self.server_url}/api/v1/health",
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False
    
    def verify_key(self) -> Dict:
        """验证API Key状态"""
        try:
            resp = requests.get(
                f"{self.server_url}/api/v1/key/verify",
                params={"api_key": self.api_key},
                timeout=5
            )
            if resp.status_code == 200:
                return resp.json()
            return {"valid": False, "message": "验证失败"}
        except Exception as e:
            return {"valid": False, "message": str(e)}


# 全局实例
_skill = None

def get_skill(api_key: str = None) -> QingtingQuerySkill:
    """获取Skill实例"""
    global _skill
    if _skill is None:
        _skill = QingtingQuerySkill(api_key=api_key)
    return _skill


def handle_message(user_input: str, user_id: str = None,
                   session_id: str = None, api_key: str = None) -> str:
    """
    Skill主入口函数
    """
    skill = get_skill(api_key=api_key)
    result = skill.chat(user_input, user_id, session_id)
    return result.get("answer", "")


# ============ CLI测试 ============
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="蜻蜓志愿数据查询测试")
    parser.add_argument("--question", "-q", help="测试问题")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--server", help="Server URL")
    args = parser.parse_args()
    
    skill = get_skill(api_key=args.api_key)
    
    if args.server:
        skill.server_url = args.server
    
    if args.question:
        result = skill.chat(args.question)
        print("\n" + "=" * 60)
        print("答案：")
        print("=" * 60)
        print(result.get("answer", ""))
    else:
        # 健康检查
        if skill.health_check():
            print("✅ Server连接正常")
            print(f"Server: {skill.server_url}")
        else:
            print("❌ Server连接失败")
        
        key_result = skill.verify_key()
        print(f"API Key: {key_result}")
