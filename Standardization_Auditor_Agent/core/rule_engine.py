import yaml
import os
import asyncio
from typing import Dict, Any
from sqlalchemy import select
from .database import db_manager, ExpertComment
from utils.logger import get_logger

logger = get_logger(__name__)

class RuleEngine:
    """
    负责加载和管理审计规则 (支持从 DB 和 rules.yaml 加载)
    """
    def __init__(self, config_path: str = "rules.yaml"):
        self.config_path = config_path
        self.rules: Dict[str, Any] = {}
        # Initial load from YAML as fallback/default
        self.load_rules_from_yaml()

    def load_rules_from_yaml(self):
        """
        从 YAML 文件加载规则 (同步)
        """
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.rules = yaml.safe_load(f) or {}
                logger.info(f"Loaded {len(self.rules)} rules from YAML")
            except Exception as e:
                logger.error(f"Failed to load rules from YAML: {e}")
                self.rules = {}
        else:
            logger.warning(f"Rules file not found: {self.config_path}")
            self.rules = {}

    async def load_rules_from_db(self):
        """
        从数据库加载规则 (异步)
        覆盖 YAML 中的同名规则
        """
        try:
            async for session in db_manager.get_session():
                stmt = select(ExpertComment)
                result = await session.execute(stmt)
                comments = result.scalars().all()
                
                for comment in comments:
                    # Parse rule_content (assuming it's stored as JSON string or YAML string)
                    # For simplicity, we assume it's a JSON string or direct value if simple
                    # Here we might need to parse it if it's complex structure
                    # But for now, let's assume rule_id maps to a config key
                    # and rule_content is the value (or part of it)
                    
                    # Example: rule_id="typo_check", rule_content='{"max_typos": 10}'
                    try:
                        # Try parsing as JSON/YAML
                        content = yaml.safe_load(comment.rule_content)
                        self.rules[comment.rule_id] = content
                    except:
                        self.rules[comment.rule_id] = comment.rule_content
                
                logger.info(f"Loaded {len(comments)} rules from DB, total rules: {len(self.rules)}")
                break # Close session
        except Exception as e:
            logger.error(f"Failed to load rules from DB: {e}")
            # Fallback to YAML is already done in __init__

    def get_rule(self, module_name: str) -> Dict[str, Any]:
        """
        获取指定模块的规则配置
        """
        return self.rules.get(module_name, {})

    async def reload(self):
        """
        重新加载规则 (支持热更新)
        """
        self.load_rules_from_yaml()
        await self.load_rules_from_db()
