import hashlib
import secrets
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

class AuthService:
    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            base_dir = Path(__file__).resolve().parent.parent.parent
            db_path = str(base_dir / "users_db.json")
        self.db_path = db_path
        self.users: Dict[str, Dict[str, Any]] = {}
        self.sessions: Dict[str, str] = {} # token -> email
        self.load_users()

    def hash_password(self, password: str, salt: Optional[str] = None) -> tuple[str, str]:
        if not salt:
            salt = secrets.token_hex(16)
        salted = (salt + password).encode('utf-8')
        pwd_hash = hashlib.sha256(salted).hexdigest()
        return pwd_hash, salt

    def verify_password(self, password: str, stored_hash: str, salt: str) -> bool:
        pwd_hash, _ = self.hash_password(password, salt)
        return pwd_hash == stored_hash

    def load_users(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.users = json.load(f)
            except Exception:
                self.users = {}
        
        # Initial default users matching Protégé individuals if empty
        if not self.users:
            self.create_default_users()

    def create_default_users(self):
        defaults = [
            {
                "email": "assure1@hestia.fr",
                "password": "password123",
                "nom": "Dupont",
                "prenom": "Alexandre",
                "cin": "11223344",
                "telephone": "0612345678",
                "adresse": "42 Avenue des Gobelins, Paris",
                "role": "Assure",
                "ontology_id": "Assure1"
            },
            {
                "email": "agent1@hestia.fr",
                "password": "password123",
                "nom": "Ben Salem",
                "prenom": "Hiba",
                "cin": "09887766",
                "telephone": "0140203040",
                "adresse": "Siège Hestia Assur, Paris",
                "role": "Agent",
                "ontology_id": "Agent1"
            },
            {
                "email": "expert1@hestia.fr",
                "password": "password123",
                "nom": "Vernier",
                "prenom": "Bernard",
                "cin": "07665544",
                "telephone": "0699887766",
                "adresse": "Cabinet Expertises, Bordeaux",
                "role": "Expert",
                "ontology_id": "Expert1"
            },
            {
                "email": "admin@hestia.fr",
                "password": "admin123",
                "nom": "Admin",
                "prenom": "Superviseur",
                "cin": "00000001",
                "telephone": "0100000000",
                "adresse": "Centre Technique Hestia",
                "role": "Admin",
                "ontology_id": "Admin1"
            }
        ]
        for u in defaults:
            pwd_hash, salt = self.hash_password(u["password"])
            self.users[u["email"]] = {
                "email": u["email"],
                "password_hash": pwd_hash,
                "salt": salt,
                "nom": u["nom"],
                "prenom": u["prenom"],
                "cin": u["cin"],
                "telephone": u["telephone"],
                "adresse": u["adresse"],
                "role": u["role"],
                "ontology_id": u["ontology_id"]
            }
        self.save_users()

    def save_users(self):
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, indent=2)

    def register(self, data: Dict[str, Any]) -> Dict[str, Any]:
        email = data["email"].strip().lower()
        if email in self.users:
            raise ValueError("Un utilisateur avec cette adresse e-mail existe déjà.")

        role = data.get("role", "Assure")
        if role not in ["Assure", "Agent", "Expert", "Beneficiaire", "Admin"]:
            role = "Assure"

        pwd_hash, salt = self.hash_password(data["password"])
        ont_id = f"{role}_{secrets.token_hex(3)}"

        user_obj = {
            "email": email,
            "password_hash": pwd_hash,
            "salt": salt,
            "nom": data.get("nom", "").strip(),
            "prenom": data.get("prenom", "").strip(),
            "cin": data.get("cin", "").strip(),
            "telephone": data.get("telephone", "").strip(),
            "adresse": data.get("adresse", "").strip(),
            "role": role,
            "ontology_id": ont_id
        }
        self.users[email] = user_obj
        self.save_users()

        token = secrets.token_hex(24)
        self.sessions[token] = email

        return {
            "token": token,
            "user": {
                "email": email,
                "nom": user_obj["nom"],
                "prenom": user_obj["prenom"],
                "role": user_obj["role"],
                "cin": user_obj["cin"],
                "telephone": user_obj["telephone"],
                "adresse": user_obj["adresse"],
                "ontology_id": ont_id
            }
        }

    def login(self, email: str, password: str) -> Dict[str, Any]:
        clean_email = email.strip().lower()
        user_obj = self.users.get(clean_email)
        if not user_obj:
            raise ValueError("Identifiants incorrects (email non trouvé).")

        if not self.verify_password(password, user_obj["password_hash"], user_obj["salt"]):
            raise ValueError("Mot de passe incorrect.")

        token = secrets.token_hex(24)
        self.sessions[token] = clean_email

        return {
            "token": token,
            "user": {
                "email": clean_email,
                "nom": user_obj["nom"],
                "prenom": user_obj["prenom"],
                "role": user_obj["role"],
                "cin": user_obj["cin"],
                "telephone": user_obj["telephone"],
                "adresse": user_obj["adresse"],
                "ontology_id": user_obj["ontology_id"]
            }
        }

    def get_current_user(self, token: str) -> Optional[Dict[str, Any]]:
        email = self.sessions.get(token)
        if not email or email not in self.users:
            return None
        u = self.users[email]
        return {
            "email": u["email"],
            "nom": u["nom"],
            "prenom": u["prenom"],
            "role": u["role"],
            "cin": u["cin"],
            "telephone": u["telephone"],
            "adresse": u["adresse"],
            "ontology_id": u["ontology_id"]
        }

auth_service = AuthService()
