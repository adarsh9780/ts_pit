"""
Configuration loader for the application.
Loads settings from config.yaml in the project root.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class Config:
    """Application configuration loaded from config.yaml."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to config file. Defaults to config.yaml in project root.
        """
        if config_path is None:
            # Default: config.yaml in project root (parent of backend/)
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config.yaml"

        self._config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load and parse the YAML configuration file."""
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self._config_path}\n"
                f"Please create a config.yaml file in the project root."
            )

        with open(self._config_path, "r") as f:
            self._config = yaml.safe_load(f)

        self._validate_config()

    def _validate_config(self) -> None:
        """Validate that required configuration sections exist."""
        required_sections = ["database", "tables"]
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required config section: {section}")

        # Validate required tables
        required_tables = ["alerts", "articles", "prices"]
        for table in required_tables:
            if table not in self._config["tables"]:
                raise ValueError(f"Missing required table config: {table}")

        # Validate required columns for alerts
        alerts_columns = self._config["tables"]["alerts"].get("columns", {})
        required_alert_cols = ["id", "ticker", "status"]
        for col in required_alert_cols:
            if col not in alerts_columns or not alerts_columns[col]:
                raise ValueError(f"Missing required alerts column mapping: {col}")

    def get_database_path(self) -> str:
        """Get the database file path, resolved relative to project root if needed."""
        db_path = self._config["database"]["path"]

        # If relative path, resolve from project root
        if not os.path.isabs(db_path):
            project_root = Path(__file__).parent.parent
            db_path = str(project_root / db_path)

        return db_path

    def get_table_name(self, table_key: str) -> str:
        """
        Get the actual database table name for a logical table.

        Args:
            table_key: Logical table name (alerts, articles, prices)

        Returns:
            Actual table name in the database
        """
        return self._config["tables"][table_key]["name"]

    def get_column(self, table_key: str, column_key: str) -> str:
        """
        Get the actual database column name for a logical column.

        Args:
            table_key: Logical table name (alerts, articles, prices)
            column_key: Logical column name (id, ticker, etc.)

        Returns:
            Actual column name in the database
        """
        return self._config["tables"][table_key]["columns"][column_key]

    def get_columns(self, table_key: str) -> Dict[str, str]:
        """Get all column mappings for a table."""
        return self._config["tables"][table_key]["columns"]

    def has_column(self, table_key: str, column_key: str) -> bool:
        """Check if a column is configured and has a non-empty value."""
        columns = self._config["tables"][table_key].get("columns", {})
        return column_key in columns and bool(columns[column_key])

    def get_display_columns(self) -> List[str]:
        """Get list of columns to display in the alerts table."""
        return self._config.get("display", {}).get(
            "table_columns",
            ["id", "ticker", "instrument_name", "trade_type", "alert_date", "status"],
        )

    def get_column_label(self, column_key: str) -> str:
        """Get the display label for a column."""
        labels = self._config.get("display", {}).get("column_labels", {})
        if column_key in labels:
            return labels[column_key]
        # Default: capitalize and replace underscores with spaces
        return column_key.replace("_", " ").title()

    def get_valid_statuses(self) -> List[str]:
        """Get list of valid status values."""
        return self._config.get(
            "valid_statuses", ["NEEDS_REVIEW", "ESCALATE_L2", "DISMISS"]
        )

    def get_status_aliases(self) -> Dict[str, str]:
        """
        Get optional status aliases.
        Used to normalize legacy status values from external systems.
        """
        return self._config.get("status_aliases", {})

    def normalize_status(self, status: str) -> str:
        """Normalize status using aliases; returns original value if no alias exists."""
        if status is None:
            return status
        aliases = self.get_status_aliases()
        return aliases.get(status, status)

    def is_status_enforced(self) -> bool:
        """Whether status values should be strictly validated."""
        validation = self._config.get("status_validation", {})
        return bool(validation.get("enforce", True))

    def is_valid_status(self, status: str) -> bool:
        """Check if a status is valid after normalization."""
        normalized = self.normalize_status(status)
        return normalized in self.get_valid_statuses()

    def get_materiality_color(self, code: str) -> str:
        """Get the color for a materiality code."""
        colors = self._config.get("materiality_colors", {})
        return colors.get(code, colors.get("DEFAULT", "#808080"))

    def get_materiality_colors(self) -> Dict[str, str]:
        """Get all materiality colors."""
        return self._config.get("materiality_colors", {"DEFAULT": "#808080"})

    def get_sector_etf_mapping(self) -> Dict[str, str]:
        """Get sector to ETF ticker mapping."""
        return self._config.get(
            "sector_etf_mapping",
            {
                "Technology": "XLK",
                "Financial Services": "XLF",
                "Healthcare": "XLV",
                "Consumer Cyclical": "XLY",
                "Industrials": "XLI",
                "Communication Services": "XLC",
                "Energy": "XLE",
                "Consumer Defensive": "XLP",
                "Utilities": "XLU",
                "Real Estate": "XLRE",
                "Basic Materials": "XLB",
            },
        )

    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration."""
        return self._config.get("llm", {})

    def get_proxy_config(self) -> Dict[str, str]:
        """Get proxy configuration."""
        return self._config.get("proxy", {})

    def get_logging_config(self) -> Dict[str, Any]:
        """Get logging configuration with sensible defaults."""
        defaults: Dict[str, Any] = {
            "dir": "~/.ts_pit/logs",
            "file_pattern": "app_{time:YYYYMMDD}.jsonl",
            "level": "INFO",
            "rotation": "10 MB",
            "retention": "14 days",
            "compression": "zip",
        }
        cfg = self._config.get("logging", {})
        if not isinstance(cfg, dict):
            return defaults
        merged = dict(defaults)
        merged.update(cfg)
        return merged

    def get_agent_mode(self) -> str:
        """Get configured agent runtime mode."""
        agent_cfg = self._config.get("agent", {})
        mode = str(agent_cfg.get("mode", "v1")).strip().lower()
        if mode not in {"v1", "v2"}:
            raise ValueError("Invalid agent.mode in config.yaml. Expected one of: v1, v2")
        return mode

    def get_agent_v2_python_exec_config(self) -> Dict[str, Any]:
        """Get execute_python policy config for agent v2."""
        default_interpreter_candidates = (
            ["py", "python", "python3"]
            if os.name == "nt"
            else ["python3", "python", "py"]
        )
        default_venv_path = (
            "~/ds/.virtualenvs/safe_py_runner/.venv"
            if os.name == "nt"
            else "~/.ts_pit/safe_py_runner/.venv"
        )
        defaults: Dict[str, Any] = {
            "enabled": False,
            "timeout_seconds": 5,
            "memory_limit_mb": 256,
            "cpu_time_seconds": 5,
            "max_output_kb": 128,
            "venv_path": default_venv_path,
            "venv_manager": "python_venv",
            "python_executable": "",
            "base_python_executable": "",
            "interpreter_candidates": default_interpreter_candidates,
            "auto_create_venv": False,
            "packages": [],
            "required_imports": ["RestrictedPython"],
            "allowed_imports": ["math", "statistics", "json"],
            "allowed_builtins": [
                "abs",
                "all",
                "any",
                "bool",
                "dict",
                "enumerate",
                "float",
                "int",
                "len",
                "list",
                "max",
                "min",
                "print",
                "range",
                "round",
                "set",
                "sorted",
                "str",
                "sum",
                "tuple",
                "zip",
            ],
        }
        cfg = self._config.get("agent_v2", {}).get("python_exec", {})
        if not isinstance(cfg, dict):
            return defaults
        merged = dict(defaults)
        merged.update(cfg)
        return merged

    def get_agent_v2_filesystem_config(self) -> Dict[str, Any]:
        """Get filesystem access policy for agent v2 generic file tools."""
        defaults: Dict[str, Any] = {
            "allowed_dirs": ["artifacts"],
            "max_depth": 1,
            "read_extensions": [
                ".md",
                ".txt",
                ".csv",
                ".json",
                ".yaml",
                ".yml",
                ".log",
                ".sql",
                ".py",
            ],
            "write_extensions": [".md"],
            "max_read_bytes": 1024 * 1024,
        }
        cfg = self._config.get("agent_v2", {}).get("filesystem", {})
        if not isinstance(cfg, dict):
            return defaults
        merged = dict(defaults)
        merged.update(cfg)
        return merged

    def get_impact_label_aliases(self) -> Dict[str, str]:
        """
        Get optional impact-label aliases.
        Used to normalize legacy impact labels from older scoring runs.
        """
        return self._config.get("impact_label_aliases", {})

    def normalize_impact_label(self, label: str) -> str:
        """Normalize impact label using aliases; returns original value if no alias exists."""
        if label is None:
            return label
        aliases = self.get_impact_label_aliases()
        key = str(label).strip()
        return aliases.get(key, aliases.get(key.upper(), key))

    def get_mappings_for_api(self) -> Dict[str, Any]:
        """
        Get configuration in a format compatible with the /config API endpoint.
        This provides all the info the frontend needs.
        """
        # Build column mappings for each table (UI key -> DB column)
        alerts_mapping = {}
        for ui_key, db_col in self.get_columns("alerts").items():
            if db_col:  # Only include non-empty mappings
                alerts_mapping[ui_key] = db_col

        articles_mapping = {}
        for ui_key, db_col in self.get_columns("articles").items():
            if db_col:
                articles_mapping[ui_key] = db_col

        prices_mapping = {}
        for ui_key, db_col in self.get_columns("prices").items():
            if db_col:
                prices_mapping[ui_key] = db_col

        has_materiality_configured = all(
            [
                self.has_column("articles", "created_date"),
                self.has_column("articles", "theme"),
                self.has_column("article_themes", "art_id"),
                self.has_column("article_themes", "p1_prominence"),
            ]
        )

        return {
            "alerts": alerts_mapping,
            "articles": articles_mapping,
            "prices": prices_mapping,
            "materiality_colors": self.get_materiality_colors(),
            "display_columns": self.get_display_columns(),
            "column_labels": self._config.get("display", {}).get("column_labels", {}),
            "valid_statuses": self.get_valid_statuses(),
            "has_materiality": has_materiality_configured,
        }


# Singleton instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


# Convenience function
config = get_config()
