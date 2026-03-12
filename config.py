"""
Project Lazarus Configuration Manager
Centralized configuration with type validation and environment fallbacks
"""
import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class FirebaseConfig:
    """Firebase configuration with validation"""
    project_id: str
    service_account_path: Path
    database_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.service_account_path.exists():
            raise FileNotFoundError(
                f"Firebase service account file not found: {self.service_account_path}"
            )
        
@dataclass
class Web3Config:
    """Web3/Ethereum configuration"""
    provider_url: str
    flashbots_endpoint: str = "https://relay.flashbots.net"
    chain_id: int = 1  # Mainnet
    
    def __post_init__(self):
        if not self.provider_url.startswith(("http", "ws")):
            raise ValueError(f"Invalid Web3 provider URL: {self.provider_url}")

@dataclass
class ResourceConfig:
    """Resource allocation limits"""
    max_cpu_percent: float = 30.0
    max_memory_mb: int = 512
    max_bandwidth_mbps: float = 10.0
    idle_threshold_seconds: int = 300  # 5 minutes idle
    
@dataclass
class BackupConfig:
    """Ghost Protocol backup configuration"""
    cloudflare_r2_bucket: Optional[str] = None
    github_token: Optional[str] = None
    github_gist_id: Optional[str] = None
    backup_interval_seconds: int = 300  # 5 minutes
    
    @property
    def has_multicloud(self) -> bool:
        """Check if multi-cloud backup is configured"""
        return bool(self.cloudflare_r2_bucket and self.github_token)

class ConfigManager:
    """Singleton configuration manager with environment variable support"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize configuration from environment variables"""
        # Firebase
        service_account_path = Path(
            os.getenv("FIREBASE_SERVICE_ACCOUNT", "firebase-service-key.json")
        )
        
        self.firebase = FirebaseConfig(
            project_id=os.getenv("FIREBASE_PROJECT_ID", "project-lazarus"),
            service_account_path=service_account_path,
            database_url=os.getenv("FIREBASE_DATABASE_URL")
        )
        
        # Web3
        self.web3 = Web3Config(
            provider_url=os.getenv("WEB3_PROVIDER_URL", "https://mainnet.infura.io/v3/"),
            flashbots_endpoint=os.getenv("FLASHBOTS_ENDPOINT", "https://relay.flashbots.net")
        )
        
        # Resources
        self.resources = ResourceConfig(
            max_cpu_percent=float(os.getenv("MAX_CPU_PERCENT", "30.0")),
            max_memory_mb=int(os.getenv("MAX_MEMORY_MB", "512")),
            max_bandwidth_mbps=float(os.getenv("MAX_BANDWIDTH_MBPS", "10.0"))
        )
        
        # Backup
        self.backup = BackupConfig(
            cloudflare_r2_bucket=os.getenv("CLOUDFLARE_R2_BUCKET"),
            github_token=os.getenv("GITHUB_TOKEN"),
            github_gist_id=os.getenv("GITHUB_GIST_ID"),
            backup_interval_seconds=int(os.getenv("BACKUP_INTERVAL", "300"))
        )
        
        # Secrets (loaded at runtime)
        self.private_key = os.getenv("PRIVATE_KEY")  # In-memory only
        
        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
    def validate(self) -> bool:
        """Validate all required configuration is present"""
        errors = []
        
        # Check Firebase
        if not self.firebase.project_id:
            errors.append("FIREBASE_PROJECT_ID is required")
        
        # Check private key (must be loaded at runtime)
        if not self.private_key:
            errors.append("PRIVATE_KEY environment variable is required")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
        
        return True

# Global configuration instance
config = ConfigManager()