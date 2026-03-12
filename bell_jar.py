"""
The Bell Jar - Secure Core Runtime
Manages resource monitoring, IdleCredit minting, and cryptographic operations
"""
import asyncio
import hashlib
import json
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import psutil
import structlog
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization

from config import config

logger = structlog.get_logger()

class ResourceMonitor:
    """Monitor system resources and quantify idle capacity"""
    
    def __init__(self):
        self.cpu_samples = []
        self.network_samples = []
        self.last_measurement = None
        
    async def measure_idle_resources(self) -> Dict[str, float]:
        """
        Measure current idle resources with smoothing over time
        Returns: Dict with cpu_idle_pct, memory_idle_mb, bandwidth_idle_mbps
        """
        # CPU idle percentage (1 second interval)
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_idle = max(0, 100 - cpu_percent - config.resources.max_cpu_percent)
        
        # Memory available
        memory = psutil.virtual_memory()
        memory_idle = max(0, memory.available / (1024 * 1024) - config.resources.max_memory_mb)
        
        # Network bandwidth (calculate over 2 seconds)
        net_before = psutil.net_io_counters()
        await asyncio.sleep(2)
        net_after = psutil.net_io_counters()
        
        bytes_sent = net_after.bytes_sent - net_before.bytes_sent
        bytes_recv = net_after.bytes_recv - net_before.bytes_recv
        total_bytes = bytes_sent + bytes_recv
        bandwidth_mbps = (total_bytes * 8) / (2 * 1_000_000)  # Convert to Mbps
        bandwidth_idle = max(0, config.resources.max_bandwidth_mbps - bandwidth_mbps)
        
        # Store samples for smoothing
        self.cpu_samples.append(cpu_idle)
        self.network_samples.append(bandwidth_idle)
        
        # Keep last 60 samples (1 minute at 1s intervals)
        if len(self.cpu_samples) > 60:
            self.cpu_samples.pop(0)
            self.network_samples.pop(0)
        
        # Calculate smoothed values (simple moving average)
        smooth_cpu = sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0
        smooth_bandwidth = sum(self.network_samples) / len(self.network_samples) if self.network_samples else 0
        
        self.last_measurement = datetime.utcnow()
        
        return {
            "cpu_idle_pct": round(smooth_cpu, 2),
            "memory_idle_mb": round(memory_idle, 2),
            "bandwidth_idle_mbps": round(smooth_bandwidth, 2),
            "timestamp": self.last_measurement.isoformat()
        }
    
    def is_system_idle(self, idle_time_seconds: int = 300) -> bool:
        """Check if system has been idle for specified time"""
        if not self.last_measurement:
            return False
        
        idle_duration = datetime.utcnow() - self.last_measurement
        return idle_duration.total_seconds() >= idle_time_seconds

class IdleCreditMinter:
    """Convert idle resources to verifiable IdleCredits"""
    
    def __init__(self):
        self.credit_history = []
        
    def calculate_credits(self, resources: Dict[str, float]) -> float:
        """
        Calculate IdleCredits based on resource availability
        Formula: (cpu_idle * 0.4 + memory_idle * 0.3 + bandwidth_idle * 0.3) / 100
        """
        cpu_weight = resources["cpu_idle_pct"] * 0.4
        memory_weight = min(resources["memory_idle_mb"], 1000) * 0.3  # Cap memory influence
        bandwidth_weight = resources["bandwidth_idle_mbps"] * 0.3
        
        raw_credits = cpu_weight + memory_weight + bandwidth_weight
        normalized_credits = raw_credits / 100.0
        
        # Apply diminishing returns for very high idle resources
        if normalized_credits > 10:
            normalized_credits = 10 + (normalized_credits - 10) * 0.5
        
        return round(max(0, normalized_credits), 4)
    
    def create_attestation(self, 
                          resources: Dict[str, float], 
                          credits: float,
                          private_key: rsa.RSAPrivateKey) -> Dict[str, Any]:
        """Create cryptographically signed attestation"""
        attestation_data = {
            "resources": resources,
            "credits": credits,
            "timestamp": datetime.utcnow().isoformat(),
            "nonce": hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
        }
        
        # Sign the attestation
        message = json.dumps(attestation_data, sort_keys=True).encode()
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        attestation_data["signature"] = signature.hex()
        attestation_data["public_key"] = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        
        return attestation_data

class SecureEnclave:
    """In-memory key management with zero disk persistence"""
    
    def __init__(self):
        self._private_key = None
        self._fernet_key = None
        self._key_generated_at = None
        
    def generate_keys(self):
        """Generate new RSA keypair and Fernet key (in memory only)"""
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self._fernet_key = Fernet.generate_key()
        self._key_generated_at = datetime.utcnow()
        
        logger.info("keys_generated", 
                   timestamp=self._key_generated_at.isoformat(),
                   key_size=2048)
    
    @property
    def private_key(self) -> Optional[rsa.RSAPrivateKey]:
        """Get private key (None if not generated)"""
        return self._private_key
    
    @property
    def fernet(self) -> Optional[Fernet]:
        """Get Fernet instance for symmetric encryption"""
        if self._fernet_key:
            return Fernet(self._fernet_key)
        return None
    
    def should_rotate_keys(self, rotation_hours: int = 24) -> bool:
        """Check if keys should be rotated"""
        if not self._key_generated_at:
            return True
        
        rotation_time = self._key_generated_at + timedelta(hours=rotation_hours)
        return datetime.utcnow() > rotation_time

class BellJar:
    """Main Bell Jar coordinator"""
    
    def __init__(self):
        self.monitor = ResourceMonitor()
        self.minter = IdleCreditMinter()
        self.enclave = SecureEnclave()
        self.running = False
        
    async def start(self):
        """Start the Bell Jar main loop"""
        self.running = True
        self.enclave.generate_keys()
        
        logger.info("bell_jar_started", 
                   timestamp=datetime.utcnow().isoformat())
        
        while self.running:
            try:
                # Measure resources
                resources = await self.monitor.measure_idle_resources()
                
                # Calculate credits
                credits = self.minter.calculate_credits(resources)
                
                # Create attestation if we have credits
                if credits > 0 and self.enclave.private_key:
                    attestation = self.minter.create_attestation(
                        resources, credits, self.enclave.private_key
                    )
                    
                    logger.info("credits_minted",
                              credits=credits,
                              resources=resources)
                    
                    # TODO: Store attestation in Firestore
                    # await self._store_attestation(attestation)
                
                # Check key rotation
                if self.enclave.should_rotate_keys():
                    logger.warning("key_rotation_required")
                    # TODO: Implement graceful key rotation
                
                # Sleep before next measurement
                await asyncio.sleep(60)  # Measure every minute
                
            except Exception as e:
                logger.error("bell_jar_error", error=str(e), exc_info=True)
                await asyncio.sleep(30)  # Backoff on error
    
    def stop(self):
        """Stop the Bell Jar"""
        self.running = False
        logger.info("bell_jar_stopped")

async def main():
    """Main entry point for Bell Jar"""
    bell_jar = BellJar()
    
    try:
        await bell_jar.start()
    except KeyboardInterrupt:
        bell_jar.stop()
    except Exception as e:
        logger.critical("bell_jar_crash", error=str(e))
        bell_jar.stop()
        raise

if __name__ == "__main__":
    asyncio.run(main())