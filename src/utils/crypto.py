"""
Token encryption utilities using Fernet (symmetric encryption).
"""
import os
import base64
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class TokenEncryption:
    """
    Handles encryption/decryption of sensitive tokens.
    Uses Fernet (AES-128-GCM) with a key derived from a master password + salt.
    """
    
    def __init__(self, config_dir: Path, master_password: str = None):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.key_file = self.config_dir / ".encryption_key"
        self.salt_file = self.config_dir / ".encryption_salt"
        
        # Use provided password or derive from machine-specific data
        if master_password:
            self._master_password = master_password.encode()
        else:
            # Derive from machine-specific data (not highly secure but better than plaintext)
            import platform
            machine_id = f"{platform.node()}{platform.machine()}{platform.processor()}"
            self._master_password = hashlib.sha256(machine_id.encode()).digest()
        
        self._fernet = self._get_or_create_fernet()
    
    def _get_or_create_fernet(self) -> Fernet:
        """Get existing Fernet key or create new one."""
        if self.key_file.exists() and self.salt_file.exists():
            try:
                with open(self.salt_file, "rb") as f:
                    salt = f.read()
                with open(self.key_file, "rb") as f:
                    encrypted_key = f.read()
                
                # Derive key from password + salt
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                )
                key = base64.urlsafe_b64encode(kdf.derive(self._master_password))
                
                # Decrypt the stored key
                f = Fernet(key)
                decrypted_key = f.decrypt(encrypted_key)
                return Fernet(decrypted_key)
            except Exception:
                # If decryption fails, create new key
                pass
        
        # Create new key
        return self._create_new_key()
    
    def _create_new_key(self) -> Fernet:
        """Create a new encryption key and save it encrypted."""
        # Generate new Fernet key
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        
        # Generate salt
        salt = os.urandom(16)
        
        # Derive encryption key for storing the Fernet key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        storage_key = base64.urlsafe_b64encode(kdf.derive(self._master_password))
        storage_fernet = Fernet(storage_key)
        
        # Encrypt and store the Fernet key
        encrypted_key = storage_fernet.encrypt(fernet_key)
        
        with open(self.key_file, "wb") as f:
            f.write(encrypted_key)
        with open(self.salt_file, "wb") as f:
            f.write(salt)
        
        # Set restrictive permissions (Unix only)
        try:
            os.chmod(self.key_file, 0o600)
            os.chmod(self.salt_file, 0o600)
        except Exception:
            pass
        
        return fernet
    
    def encrypt(self, data: str) -> str:
        """Encrypt a string and return base64 encoded result."""
        if not data:
            return ""
        encrypted = self._fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt a base64 encoded string."""
        if not encrypted_data:
            return ""
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted = self._fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception:
            return ""


import hashlib


def get_encryption(config_dir: Path, master_password: str = None) -> TokenEncryption:
    """Factory function to get TokenEncryption instance."""
    return TokenEncryption(config_dir, master_password)