import uuid
import re
import json
import time
import html
import base64
import webbrowser
import threading
import socket
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Callable, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import minecraft_launcher_lib.microsoft_account as ms_account
from minecraft_launcher_lib.exceptions import (
    AzureAppNotPermitted,
    AccountNotOwnMinecraft,
    InvalidRefreshToken,
    SecurityError,
)

from utils.crypto import get_encryption


@dataclass
class AuthProfile:
    username: str
    uuid: str
    token: str
    refresh_token: str = ""
    expires_at: int = 0
    auth_type: str = "offline"  # "offline" or "microsoft"
    user_properties: str = ""  # Base64 encoded user properties from Mojang

    def is_expired(self) -> bool:
        if self.auth_type == "offline":
            return False
        return time.time() >= self.expires_at - 60  # 60s buffer

    def is_valid(self) -> bool:
        return bool(self.username and self.uuid)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AuthProfile":
        return cls(**data)


class OfflineAuthError(Exception):
    pass


class MicrosoftAuthError(Exception):
    pass


class AuthManager:
    """
    Manages authentication: offline mode and Microsoft OAuth (Authorization Code Flow with PKCE).
    Uses minecraft-launcher-lib for Microsoft authentication.
    """
    
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]{3,16}$')
    OFFLINE_NAMESPACE = uuid.UUID('00000000-0000-0000-0000-000000000000')

    def __init__(
        self,
        config_path: Path,
        client_id: str = "3b42bcd5-9b4e-4f8b-85e8-5f3a749d0267",
        redirect_uri: str = "http://localhost:8080/callback",
        on_login_url: Optional[Callable[[str], None]] = None,
        on_auth_complete: Optional[Callable[[bool, str, Optional[AuthProfile]], None]] = None
    ):
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.client_id = client_id
        self.redirect_uri = redirect_uri  # Will be updated with dynamic port in start_microsoft_login
        self.on_login_url = on_login_url  # Callback: (login_url) -> show to user
        self.on_auth_complete = on_auth_complete  # Callback: (success, message, profile)

        # PKCE state
        self._code_verifier: Optional[str] = None
        self._state: Optional[str] = None

        # Callback server
        self._callback_server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None

        # Initialize encryption
        self.encryption = get_encryption(self.config_path.parent)

        self.profile: Optional[AuthProfile] = None
        self._load_session()

    # ==================== OFFLINE AUTH ====================

    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        """Validate offline username: 3-16 chars, alphanumeric + underscore."""
        if not username:
            return False, "Имя пользователя не может быть пустым"
        if not AuthManager.USERNAME_PATTERN.match(username):
            return False, "Имя пользователя: 3-16 символов, только буквы, цифры и _"
        return True, ""

    @staticmethod
    def generate_offline_uuid(username: str) -> str:
        """Generate deterministic offline UUID using uuid.uuid3 (MD5-based)."""
        name_uuid = uuid.uuid3(AuthManager.OFFLINE_NAMESPACE, f"OfflinePlayer:{username}")
        return str(name_uuid).replace("-", "")

    def login_offline(self, username: str) -> AuthProfile:
        """Authenticate in offline mode."""
        valid, error = self.validate_username(username)
        if not valid:
            raise OfflineAuthError(error)

        profile = AuthProfile(
            username=username,
            uuid=self.generate_offline_uuid(username),
            token="0",  # Offline token
            auth_type="offline"
        )
        self.profile = profile
        self._save_session()
        return profile

    # ==================== MICROSOFT OAUTH (Auth Code Flow + PKCE) ====================

    def get_microsoft_login_url(self) -> str:
        """
        Generate Microsoft login URL using PKCE (Authorization Code Flow).
        Returns the login URL to open in browser.

        Notes:
        - We keep the library's default /consumers/ tenant and its
          'XboxLive.signin offline_access' scope. The /consumers/ endpoint accepts
          XboxLive.signin for this app out of the box, whereas /common/ rejects it
          with 'invalid_scope ... not configured for this tenant' unless the Azure
          app explicitly has the Xbox Live API permission.
        - The XboxLive.signin scope is REQUIRED: complete_login() exchanges the
          token for an Xbox Live (XBL) token. OIDC-only scopes break that step.
        """
        try:
            # Generate secure login data with PKCE (verifier/challenge + state)
            login_url, state, code_verifier = ms_account.get_secure_login_data(
                client_id=self.client_id,
                redirect_uri=self.redirect_uri
            )

            # Store PKCE verifier and state for the token exchange step
            self._code_verifier = code_verifier
            self._state = state

            # Notify UI (browser is opened by start_microsoft_login)
            if self.on_login_url:
                self.on_login_url(login_url)

            return login_url

        except Exception as e:
            raise MicrosoftAuthError(f"Failed to generate login URL: {e}")

    @staticmethod
    def _build_user_properties(profile_response: dict) -> str:
        """
        Build the base64-encoded --userProperties value from the Mojang profile
        (skins/capes), so the game can render the player's skin and cape.
        """
        textures: dict = {}
        for skin in profile_response.get("skins") or []:
            textures["SKIN"] = {"url": skin.get("url", "")}
        for cape in profile_response.get("capes") or []:
            textures["CAPE"] = {"url": cape.get("url", "")}

        if not textures:
            return ""

        inner = json.dumps({"textures": textures}, separators=(",", ":"))
        inner_b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
        outer = json.dumps([{"name": "textures", "value": inner_b64}], separators=(",", ":"))
        return base64.b64encode(outer.encode("utf-8")).decode("ascii")

    def complete_microsoft_login(self, redirect_url: str) -> AuthProfile:
        """
        Complete Microsoft login using the redirect URL from the browser.
        The redirect_url should contain the auth code returned by Microsoft.

        The OAuth -> XBL -> XSTS -> Minecraft handshake is performed step by step
        (instead of a single library call) so that a failure reports the real
        reason from Xbox/Minecraft instead of a generic "AzureAppNotPermitted".
        """
        try:
            auth_code = ms_account.parse_auth_code_url(redirect_url, self._state)

            # 1) Exchange the auth code for an OAuth token
            token_request = ms_account.get_authorization_token(
                client_id=self.client_id,
                client_secret=None,  # Public client with PKCE
                redirect_uri=self.redirect_uri,
                auth_code=auth_code,
                code_verifier=self._code_verifier
            )
            if "access_token" not in token_request:
                raise MicrosoftAuthError(
                    "Не удалось обменять код авторизации на токен: "
                    f"{token_request.get('error_description') or token_request.get('error')}"
                )

            # 2) Xbox Live authentication
            xbl_request = ms_account.authenticate_with_xbl(token_request["access_token"])
            if "Token" not in xbl_request:
                x_err = xbl_request.get("XErr")
                raise MicrosoftAuthError(self._describe_xbox_error(x_err, "Xbox Live"))

            userhash = xbl_request["DisplayClaims"]["xui"][0]["uhs"]

            # 3) Xbox Security Token Service
            xsts_request = ms_account.authenticate_with_xsts(xbl_request["Token"])
            if "Token" not in xsts_request:
                x_err = xsts_request.get("XErr")
                raise MicrosoftAuthError(self._describe_xbox_error(x_err, "XSTS"))

            # 4) Minecraft services
            account_request = ms_account.authenticate_with_minecraft(
                userhash, xsts_request["Token"]
            )

            # Depending on the API version this endpoint answers with either
            # "access_token" (MCSA) or "identityToken". Both are valid Bearer
            # tokens for the Minecraft services endpoints.
            minecraft_token = (
                account_request.get("access_token")
                or account_request.get("identityToken")
            )
            if not minecraft_token:
                x_err = account_request.get("XErr")
                if x_err is not None:
                    raise MicrosoftAuthError(self._describe_xbox_error(x_err, "Minecraft"))

                # Minecraft Services keep an allowlist of approved Azure client ids.
                error_message = str(
                    account_request.get("errorMessage")
                    or account_request.get("error")
                    or ""
                )
                if "invalid app registration" in error_message.lower():
                    raise MicrosoftAuthError(
                        "Minecraft Services отклонил приложение: "
                        f"client_id {self.client_id} не входит в список "
                        "одобренных.\n"
                        "Все шаги входа (OAuth, Xbox Live, XSTS) прошли успешно — "
                        "не хватает только регистрации client_id.\n"
                        "Подайте заявку на одобрение: https://aka.ms/mce-reviewappid\n"
                        "Либо укажите в настройках уже одобренный client_id."
                    )

                keys = ", ".join(account_request.keys()) or "(пустой ответ)"
                raise MicrosoftAuthError(
                    "Minecraft API не вернул токен. "
                    f"Поля ответа: {keys}. "
                    f"Ответ: {str(account_request)[:300]}"
                )

            # 5) Minecraft profile (name, uuid, skins)
            profile_response = ms_account.get_profile(minecraft_token)
            if profile_response.get("error") == "NOT_FOUND":
                raise MicrosoftAuthError("У аккаунта нет профиля Minecraft")

            profile_response = dict(profile_response)
            profile_response["access_token"] = minecraft_token
            profile_response["refresh_token"] = token_request.get("refresh_token", "")

            profile = self._profile_from_response(profile_response)

            self.profile = profile
            self._save_session()

            if self.on_auth_complete:
                self.on_auth_complete(True, "Авторизация успешна", profile)

            return profile

        except MicrosoftAuthError as e:
            if self.on_auth_complete:
                self.on_auth_complete(False, str(e), None)
            raise
        except Exception as e:
            error_msg = f"Ошибка авторизации: {e}"
            if self.on_auth_complete:
                self.on_auth_complete(False, error_msg, None)
            raise MicrosoftAuthError(error_msg)

    @staticmethod
    def _describe_xbox_error(x_err, stage: str) -> str:
        """Translate a known Xbox XErr code into a helpful message."""
        known = {
            "2148916233": "у аккаунта Microsoft нет действующего профиля Xbox Live "
                          "(обычно значит, что на аккаунте не куплена Minecraft: Java Edition)",
            "2148916235": "Minecraft не поддерживается в регионе этого аккаунта",
            "2148916236": "Minecraft недоступен в Южной Корее (требуется корейский аккаунт)",
            "2148916237": "Minecraft недоступен в Китае",
            "2148916238": "аккаунт детский - его нужно добавить в семейную группу взрослым",
        }
        if x_err is None:
            return f"Xbox отклонил запрос на этапе {stage}"
        detail = known.get(str(x_err))
        if detail:
            return f"Ошибка {stage} (XErr {x_err}): {detail}"
        return f"Ошибка {stage} (XErr {x_err})"

    def _profile_from_response(self, response: dict) -> AuthProfile:
        """Build an AuthProfile from a CompleteLoginResponse TypedDict."""
        return AuthProfile(
            username=response["name"],
            uuid=response["id"].replace("-", ""),
            token=response["access_token"],
            refresh_token=response.get("refresh_token", ""),
            expires_at=int(time.time() + 3600),
            auth_type="microsoft",
            user_properties=self._build_user_properties(response)
        )

    def start_microsoft_login(self) -> str:
        """
        Start Microsoft login flow with local callback server.
        Opens browser with login URL and starts local server to receive callback.
        No manual copy/paste required.
        """
        # Find a free port for local callback server
        port = self._find_free_port()
        self.redirect_uri = f"http://localhost:{port}/callback"
        
        login_url = self.get_microsoft_login_url()
        
        # Start local callback server
        self._callback_server = self._start_callback_server(port)
        self._server_thread = threading.Thread(target=self._callback_server.serve_forever, daemon=True)
        self._server_thread.start()
        
        webbrowser.open(login_url)
        return login_url

    def _find_free_port(self) -> int:
        """Find a free port for local callback server.
        
        Tries to use port 8080 (must be registered in Azure Portal).
        Falls back to any free port if 8080 is unavailable.
        """
        # First try the preferred port 8080 (must be registered in Azure)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', 8080))
                return 8080
        except OSError:
            pass
        
        # Fallback: find any free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            return s.getsockname()[1]

    def _start_callback_server(self, port: int) -> HTTPServer:
        """Start local HTTP server to receive OAuth callback."""
        auth_manager = self
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def _respond(self, status: int, title: str, message: str):
                """Send a simple HTML page to the browser."""
                page = (
                    "<html><body style=\"font-family: sans-serif; text-align: center; padding: 50px;\">"
                    f"<h2>{title}</h2><p>{message}</p></body></html>"
                )
                self.send_response(status)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(page.encode('utf-8'))

            def do_GET(self):
                # Parse the callback URL
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)

                if 'code' in query:
                    auth_code = query['code'][0]
                    state = query.get('state', [None])[0]

                    self._respond(
                        200,
                        "✅ Авторизация успешна",
                        "Вы можете закрыть это окно и вернуться в лаунчер."
                    )

                    # Complete auth in background
                    threading.Thread(
                        target=auth_manager._complete_auth_callback,
                        args=(auth_code, state),
                        daemon=True
                    ).start()
                    return

                # Microsoft reports failures as ?error=...&error_description=...
                error = query.get('error', [None])[0]
                if error:
                    description = query.get('error_description', [''])[0]
                    if description:
                        description = description.replace('+', ' ')
                    message = f"{error}: {description}" if description else error

                    self._respond(400, "❌ Ошибка авторизации", html.escape(message))

                    threading.Thread(
                        target=auth_manager._fail_auth,
                        args=(message,),
                        daemon=True
                    ).start()
                    return

                self._respond(400, "❌ Ошибка", "В запросе отсутствует код авторизации.")

            def log_message(self, format, *args):
                pass  # Suppress logging

        server = HTTPServer(('localhost', port), CallbackHandler)
        return server

    def _fail_auth(self, message: str):
        """Report an authorization failure and stop the callback server."""
        try:
            if self.on_auth_complete:
                self.on_auth_complete(False, message, None)
        finally:
            self.stop_callback_server()

    def _complete_auth_callback(self, auth_code: str, state: Optional[str]):
        """Complete authentication after receiving callback."""
        try:
            # Build redirect URL for complete_login
            redirect_url = f"{self.redirect_uri}?code={auth_code}"
            if state:
                redirect_url += f"&state={state}"
            
            profile = self.complete_microsoft_login(redirect_url)
        except Exception as e:
            if self.on_auth_complete:
                self.on_auth_complete(False, f"Ошибка завершения авторизации: {e}", None)
        finally:
            # Stop callback server after auth completes (success or failure)
            self.stop_callback_server()

    def stop_callback_server(self):
        """Stop the local callback server."""
        if hasattr(self, '_callback_server') and self._callback_server:
            self._callback_server.shutdown()
            self._callback_server.server_close()
            self._callback_server = None

    def refresh_microsoft_token(self) -> bool:
        """Refresh Microsoft access token using the stored refresh token."""
        if not self.profile or self.profile.auth_type != "microsoft" or not self.profile.refresh_token:
            return False

        try:
            # complete_refresh returns the same shape as complete_login:
            # id, name, access_token, refresh_token, skins, capes
            response = ms_account.complete_refresh(
                client_id=self.client_id,
                client_secret=None,  # Public client
                redirect_uri=self.redirect_uri,
                refresh_token=self.profile.refresh_token
            )

            refreshed = self._profile_from_response(response)

            self.profile.token = refreshed.token
            self.profile.refresh_token = refreshed.refresh_token or self.profile.refresh_token
            self.profile.expires_at = refreshed.expires_at
            self.profile.username = refreshed.username
            self.profile.uuid = refreshed.uuid
            if refreshed.user_properties:
                self.profile.user_properties = refreshed.user_properties

            self._save_session()
            return True

        except (InvalidRefreshToken, AccountNotOwnMinecraft,
                AzureAppNotPermitted, SecurityError) as e:
            print(f"Token refresh failed: {e}")
            return False
        except Exception as e:
            print(f"Token refresh failed: {e}")
            return False

    # ==================== SESSION MANAGEMENT ====================

    def _load_session(self):
        """Load session from config file (encrypted)."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    encrypted_data = f.read()
                
                # Decrypt
                decrypted = self.encryption.decrypt(encrypted_data)
                if not decrypted:
                    print("Failed to decrypt session")
                    self.profile = None
                    return
                
                data = json.loads(decrypted)
                self.profile = AuthProfile.from_dict(data)
                
                # Auto-refresh if Microsoft session expired
                if self.profile and self.profile.auth_type == "microsoft" and self.profile.is_expired():
                    print("Session expired, attempting refresh...")
                    if not self.refresh_microsoft_token():
                        print("Refresh failed, clearing session")
                        self.profile = None
                        self._clear_session()
                        
            except Exception as e:
                print(f"Failed to load session: {e}")
                self.profile = None

    def _save_session(self):
        """Save session to config file (encrypted)."""
        if self.profile:
            try:
                data = json.dumps(self.profile.to_dict(), indent=2)
                encrypted = self.encryption.encrypt(data)
                if not encrypted:
                    print("Failed to encrypt session")
                    return
                
                with open(self.config_path, "w", encoding="utf-8") as f:
                    f.write(encrypted)
            except Exception as e:
                print(f"Failed to save session: {e}")

    def _clear_session(self):
        """Clear session file."""
        try:
            if self.config_path.exists():
                self.config_path.unlink()
        except Exception:
            pass

    def logout(self):
        """Logout and clear session."""
        self.profile = None
        self._clear_session()

    def get_profile(self) -> Optional[AuthProfile]:
        """Get current auth profile."""
        return self.profile

    def is_logged_in(self) -> bool:
        return self.profile is not None and self.profile.is_valid()