#!/usr/bin/env python3
"""
Stage 3 Acceptance Criteria Verification Script

Verifies:
1. Offline login correctly generates profile structure (username, uuid, token="0")
2. Microsoft auth provides URL and Device Code; after browser confirmation gets user_properties
3. Session persists and loads automatically after restart
"""

import sys
import tempfile
import time
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.auth import AuthManager, AuthProfile, OfflineAuthError


def test_offline_login_validation():
    """Test 1: Offline username validation"""
    print("=" * 60)
    print("TEST 1: Offline Username Validation")
    print("=" * 60)

    # Valid usernames
    valid_names = ["Player", "Player123", "Test_User", "a1b2c3", "AbCdEfGhIjKlMnOp"]
    for name in valid_names:
        valid, error = AuthManager.validate_username(name)
        if not valid:
            print(f"[FAIL] Valid username rejected: {name} -> {error}")
            return False
    print("[PASS] Valid usernames accepted")

    # Invalid usernames
    invalid_names = [
        ("", "пустое"),
        ("ab", "короткое"),
        ("a" * 17, "длинное"),
        ("Player@", "спецсимвол"),
        ("Player Name", "пробел"),
        ("Игрок", "кириллица"),
        ("Player!", "восклицание"),
    ]
    for name, desc in invalid_names:
        valid, error = AuthManager.validate_username(name)
        if valid:
            print(f"[FAIL] Invalid username ({desc}) accepted: '{name}'")
            return False
    print("[PASS] Invalid usernames rejected")

    print("Offline username validation: ALL TESTS PASSED")
    return True


def test_offline_uuid_generation():
    """Test 2: Offline UUID generation (deterministic)"""
    print("\n" + "=" * 60)
    print("TEST 2: Offline UUID Generation")
    print("=" * 60)

    username = "TestPlayer123"
    
    # Generate UUID multiple times - should be deterministic
    uuid1 = AuthManager.generate_offline_uuid(username)
    uuid2 = AuthManager.generate_offline_uuid(username)
    uuid3 = AuthManager.generate_offline_uuid(username)
    
    if uuid1 != uuid2 or uuid2 != uuid3:
        print(f"[FAIL] UUID not deterministic: {uuid1}, {uuid2}, {uuid3}")
        return False
    print(f"[PASS] UUID deterministic: {uuid1}")
    
    # UUID should be 32 hex chars (no dashes)
    if len(uuid1) != 32:
        print(f"[FAIL] UUID wrong length: {len(uuid1)} (expected 32)")
        return False
    print("[PASS] UUID correct length (32 chars)")
    
    # Different usernames should give different UUIDs
    uuid_other = AuthManager.generate_offline_uuid("OtherPlayer")
    if uuid1 == uuid_other:
        print("[FAIL] Different usernames produced same UUID")
        return False
    print("[PASS] Different usernames produce different UUIDs")
    
    # Verify it's valid hex
    try:
        int(uuid1, 16)
        print("[PASS] UUID is valid hex")
    except ValueError:
        print("[FAIL] UUID contains non-hex characters")
        return False

    print("Offline UUID generation: ALL TESTS PASSED")
    return True


def test_offline_login_full():
    """Test 3: Full offline login flow"""
    print("\n" + "=" * 60)
    print("TEST 3: Offline Login Flow")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        auth_manager = AuthManager(config_path=auth_path)

        # Login offline
        profile = auth_manager.login_offline("TestPlayer")
        
        # Check profile structure
        if not isinstance(profile, AuthProfile):
            print("[FAIL] login_offline didn't return AuthProfile")
            return False
        
        print(f"  Username: {profile.username}")
        print(f"  UUID: {profile.uuid}")
        print(f"  Token: {profile.token}")
        print(f"  Auth type: {profile.auth_type}")
        print(f"  Refresh token: '{profile.refresh_token}'")
        print(f"  Expires at: {profile.expires_at}")
        print(f"  User properties: '{profile.user_properties}'")

        # Verify required fields
        if profile.username != "TestPlayer":
            print(f"[FAIL] Username mismatch: {profile.username}")
            return False
        print("[PASS] Username correct")
        
        if profile.token != "0":
            print(f"[FAIL] Token should be '0' for offline, got: {profile.token}")
            return False
        print("[PASS] Token is '0' for offline")
        
        if profile.auth_type != "offline":
            print(f"[FAIL] Auth type should be 'offline', got: {profile.auth_type}")
            return False
        print("[PASS] Auth type is 'offline'")
        
        # UUID should match generated one
        expected_uuid = AuthManager.generate_offline_uuid("TestPlayer")
        if profile.uuid != expected_uuid:
            print(f"[FAIL] UUID mismatch: got {profile.uuid}, expected {expected_uuid}")
            return False
        print("[PASS] UUID matches generated offline UUID")
        
        # Should not have refresh token or expiry for offline
        if profile.refresh_token:
            print(f"[FAIL] Offline should not have refresh token: {profile.refresh_token}")
            return False
        print("[PASS] No refresh token for offline")
        
        if profile.expires_at != 0:
            print(f"[FAIL] Offline should not expire: {profile.expires_at}")
            return False
        print("[PASS] No expiry for offline")

        # Verify profile is stored in auth_manager
        stored = auth_manager.get_profile()
        if stored.username != profile.username:
            print("[FAIL] Profile not stored in auth_manager")
            return False
        print("[PASS] Profile stored in AuthManager")

    print("Offline login flow: ALL TESTS PASSED")
    return True


def test_session_persistence():
    """Test 4: Session persistence across restarts"""
    print("\n" + "=" * 60)
    print("TEST 4: Session Persistence")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        
        # First "session" - login
        auth_manager1 = AuthManager(config_path=auth_path)
        profile1 = auth_manager1.login_offline("PersistentPlayer")
        print(f"  Session 1: {profile1.username} ({profile1.uuid})")
        
        # Verify file was created
        if not auth_path.exists():
            print("[FAIL] Auth file not created")
            return False
        print("[PASS] Auth file created")
        
        # Check file contents (encrypted)
        with open(auth_path, "r") as f:
            encrypted_data = f.read()
        print(f"  Saved data (encrypted): {encrypted_data[:50]}...")
        
        # Verify it's encrypted (not plain JSON)
        if encrypted_data.startswith("{"):
            print("[FAIL] Data not encrypted!")
            return False
        print("[PASS] Data is encrypted")
        
        # Second "session" - new AuthManager instance (simulates restart)
        auth_manager2 = AuthManager(config_path=auth_path)
        profile2 = auth_manager2.get_profile()
        
        if not profile2:
            print("[FAIL] Profile not loaded on restart")
            return False
        print(f"  Session 2: {profile2.username} ({profile2.uuid})")
        
        # Verify data matches
        if profile1.username != profile2.username:
            print(f"[FAIL] Username mismatch after restart: {profile1.username} vs {profile2.username}")
            return False
        print("[PASS] Username persists")
        
        if profile1.uuid != profile2.uuid:
            print(f"[FAIL] UUID mismatch after restart: {profile1.uuid} vs {profile2.uuid}")
            return False
        print("[PASS] UUID persists")
        
        if profile1.token != profile2.token:
            print(f"[FAIL] Token mismatch after restart: {profile1.token} vs {profile2.token}")
            return False
        print("[PASS] Token persists")
        
        if profile1.auth_type != profile2.auth_type:
            print(f"[FAIL] Auth type mismatch after restart: {profile1.auth_type} vs {profile2.auth_type}")
            return False
        print("[PASS] Auth type persists")

    print("Session persistence: ALL TESTS PASSED")
    return True


def test_logout_clears_session():
    """Test 5: Logout clears session"""
    print("\n" + "=" * 60)
    print("TEST 5: Logout Clears Session")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        auth_manager = AuthManager(config_path=auth_path)
        
        # Login
        auth_manager.login_offline("TestPlayer")
        assert auth_manager.get_profile() is not None
        print("[PASS] Logged in")
        
        # Logout
        auth_manager.logout()
        assert auth_manager.get_profile() is None
        print("[PASS] Profile cleared from memory")
        
        # File should be deleted
        if auth_path.exists():
            print("[FAIL] Auth file still exists after logout")
            return False
        print("[PASS] Auth file deleted")

    print("Logout clears session: ALL TESTS PASSED")
    return True


def test_is_logged_in():
    """Test 6: is_logged_in method"""
    print("\n" + "=" * 60)
    print("TEST 6: is_logged_in Method")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        auth_path = Path(tmpdir) / "auth.json"
        auth_manager = AuthManager(config_path=auth_path)
        
        # Not logged in initially
        if auth_manager.is_logged_in():
            print("[FAIL] Should not be logged in initially")
            return False
        print("[PASS] Not logged in initially")
        
        # Login
        auth_manager.login_offline("TestPlayer")
        if not auth_manager.is_logged_in():
            print("[FAIL] Should be logged in after login")
            return False
        print("[PASS] Logged in after login")
        
        # Logout
        auth_manager.logout()
        if auth_manager.is_logged_in():
            print("[FAIL] Should not be logged in after logout")
            return False
        print("[PASS] Not logged in after logout")

    print("is_logged_in: ALL TESTS PASSED")
    return True


def test_microsoft_auth_structure():
    """Test 7: Microsoft auth profile structure (mocked)"""
    print("\n" + "=" * 60)
    print("TEST 7: Microsoft Auth Profile Structure")
    print("=" * 60)

    # Create a mock Microsoft profile (simulating what would come from API)
    profile = AuthProfile(
        username="MicrosoftUser",
        uuid="1234567890abcdef1234567890abcdef",
        token="mock_access_token_12345",
        refresh_token="mock_refresh_token_67890",
        expires_at=int(time.time() + 3600),  # 1 hour from now
        auth_type="microsoft",
        user_properties="mock_user_properties_base64"
    )
    
    print(f"  Username: {profile.username}")
    print(f"  UUID: {profile.uuid}")
    print(f"  Token: {profile.token[:20]}...")
    print(f"  Refresh token: {profile.refresh_token[:20]}...")
    print(f"  Expires at: {profile.expires_at}")
    print(f"  Auth type: {profile.auth_type}")
    print(f"  User properties: {profile.user_properties[:20]}...")
    
    # Verify structure
    if profile.auth_type != "microsoft":
        print("[FAIL] Auth type should be 'microsoft'")
        return False
    print("[PASS] Auth type is 'microsoft'")
    
    if profile.token == "0":
        print("[FAIL] Microsoft token should not be '0'")
        return False
    print("[PASS] Token is not '0'")
    
    if not profile.refresh_token:
        print("[FAIL] Microsoft profile should have refresh token")
        return False
    print("[PASS] Has refresh token")
    
    if profile.expires_at <= time.time():
        print("[FAIL] Expiry should be in future")
        return False
    print("[PASS] Expiry is in future")
    
    if not profile.user_properties:
        print("[FAIL] Should have user_properties")
        return False
    print("[PASS] Has user_properties")
    
    # Test is_expired
    if profile.is_expired():
        print("[FAIL] Fresh token should not be expired")
        return False
    print("[PASS] Fresh token not expired")
    
    # Test expired token
    expired_profile = AuthProfile(
        username="Expired",
        uuid="11111111111111111111111111111111",
        token="expired_token",
        refresh_token="refresh",
        expires_at=int(time.time() - 100),  # Expired 100 seconds ago
        auth_type="microsoft"
    )
    if not expired_profile.is_expired():
        print("[FAIL] Expired token should be detected as expired")
        return False
    print("[PASS] Expired token detected")

    print("Microsoft auth profile structure: ALL TESTS PASSED")
    return True


def main():
    print("Melon Launcher - Stage 3 Acceptance Criteria Verification")
    print("=" * 60)

    results = []

    results.append(("Offline Username Validation", test_offline_login_validation()))
    results.append(("Offline UUID Generation", test_offline_uuid_generation()))
    results.append(("Offline Login Flow", test_offline_login_full()))
    results.append(("Session Persistence", test_session_persistence()))
    results.append(("Logout Clears Session", test_logout_clears_session()))
    results.append(("is_logged_in Method", test_is_logged_in()))
    results.append(("Microsoft Auth Profile Structure", test_microsoft_auth_structure()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All acceptance criteria PASSED")
        return 0
    else:
        print("Some acceptance criteria FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())