import yaml
import os
from typing import Dict, Any

class RuleEngine:
    """
    负责加载和管理审计规则 (支持从 rules.yaml 加载)
    """
    def __init__(self, config_path: str = "rules.yaml"):
        self.config_path = config_path
        self.rules: Dict[str, Any] = {}
        self.load_rules()

    def load_rules(self):
        """
        从 YAML 文件加载规则
        """
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.rules = yaml.safe_load(f)
        else:
            # 默认规则
            self.rules = {
                "typo_check": {"max_typos_total_warning": 10},
                "citation_check": {"style": "IEEE"}
            }

    def get_rule(self, module_name: str) -> Dict[str, Any]:
        """
        获取指定模块的规则配置
        """
        return self.rules.get(module_name, {})

    def reload(self):
        """
        重新加载规则 (支持热更新)
        """
        self.load_rules()
