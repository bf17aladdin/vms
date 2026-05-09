# vms/backend/core/rbac.py - Role-Based Access Control (Sprint 6)

import logging
from enum import Enum
from typing import List, Dict, Set, Optional
from functools import wraps

logger = logging.getLogger(__name__)

class Role(str, Enum):
    """Rôles utilisateurs avec permissions hiérarchiques"""
    ADMIN = "admin"              # Accès complet
    SUPERVISOR = "supervisor"    # Gestion + config
    OPERATOR = "operator"        # Lecture + basic actions
    VIEWER = "viewer"            # Lecture seule

class Permission(str, Enum):
    """Permissions granulaires"""
    # Personnel
    PERSONNEL_READ = "personnel:read"
    PERSONNEL_CREATE = "personnel:create"
    PERSONNEL_UPDATE = "personnel:update"
    PERSONNEL_DELETE = "personnel:delete"
    PERSONNEL_BLACKLIST = "personnel:blacklist"
    
    # Vehicles
    VEHICLE_READ = "vehicle:read"
    VEHICLE_CREATE = "vehicle:create"
    VEHICLE_UPDATE = "vehicle:update"
    VEHICLE_DELETE = "vehicle:delete"
    
    # Cameras
    CAMERA_READ = "camera:read"
    CAMERA_CREATE = "camera:create"
    CAMERA_UPDATE = "camera:update"
    CAMERA_DELETE = "camera:delete"
    CAMERA_CONTROL = "camera:control"  # PTZ, etc.
    
    # System
    SYSTEM_CONFIG = "system:config"
    SYSTEM_EXPORT = "system:export"
    SYSTEM_LOGS = "system:logs"
    ADMIN_PANEL = "admin:panel"

class RBACManager:
    """
    Gère les rôles et permissions utilisateurs.
    Enforce lors des requêtes API.
    
    **Sprint 6 Deliverable**: Security & Roles (RBAC)
    """
    
    # Mappages rôle → permissions
    ROLE_PERMISSIONS = {
        Role.ADMIN: set(Permission),  # Tous
        Role.SUPERVISOR: {
            Permission.PERSONNEL_READ, Permission.PERSONNEL_UPDATE,
            Permission.PERSONNEL_BLACKLIST,
            Permission.VEHICLE_READ, Permission.VEHICLE_UPDATE,
            Permission.CAMERA_READ, Permission.CAMERA_UPDATE,
            Permission.CAMERA_CONTROL,
            Permission.SYSTEM_CONFIG, Permission.SYSTEM_EXPORT,
            Permission.SYSTEM_LOGS
        },
        Role.OPERATOR: {
            Permission.PERSONNEL_READ, Permission.PERSONNEL_UPDATE,
            Permission.VEHICLE_READ,
            Permission.CAMERA_READ,
            Permission.SYSTEM_EXPORT
        },
        Role.VIEWER: {
            Permission.PERSONNEL_READ,
            Permission.VEHICLE_READ,
            Permission.CAMERA_READ
        }
    }
    
    def __init__(self):
        self.user_roles: Dict[int, Set[Role]] = {}  # user_id -> roles
    
    def assign_role(self, user_id: int, role: Role):
        """Assigner un rôle à un utilisateur"""
        if user_id not in self.user_roles:
            self.user_roles[user_id] = set()
        self.user_roles[user_id].add(role)
        logger.info(f"✓ Role {role} assigned to user {user_id}")
    
    def remove_role(self, user_id: int, role: Role):
        """Retirer un rôle d'un utilisateur"""
        if user_id in self.user_roles:
            self.user_roles[user_id].discard(role)
            logger.info(f"✓ Role {role} removed from user {user_id}")
    
    def get_permissions(self, user_id: int) -> Set[Permission]:
        """Récupérer toutes les permissions d'un utilisateur"""
        roles = self.user_roles.get(user_id, set())
        permissions = set()
        for role in roles:
            permissions.update(self.ROLE_PERMISSIONS.get(role, set()))
        return permissions
    
    def has_permission(self, user_id: int, permission: Permission) -> bool:
        """Vérifier si utilisateur a une permission"""
        return permission in self.get_permissions(user_id)
    
    def has_role(self, user_id: int, role: Role) -> bool:
        """Vérifier si utilisateur a un rôle"""
        return role in self.user_roles.get(user_id, set())
    
    def is_admin(self, user_id: int) -> bool:
        """Raccourci: vérifier si admin"""
        return self.has_role(user_id, Role.ADMIN)
    
    def enforce_permission(self, permission: Permission):
        """
        Décorateur pour enforcer une permission sur une route
        
        Usage:
            @rbac.enforce_permission(Permission.PERSONNEL_CREATE)
            async def create_personnel(...)
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, current_user: dict, **kwargs):
                user_id = current_user.get('user_id')
                if not self.has_permission(user_id, permission):
                    logger.warning(f"⚠️ User {user_id} denied: {permission}")
                    from fastapi import HTTPException
                    raise HTTPException(status_code=403, detail="Permission denied")
                return await func(*args, current_user=current_user, **kwargs)
            return wrapper
        return decorator
    
    def get_user_profile(self, user_id: int) -> Dict:
        """Profil complet d'un utilisateur"""
        roles = self.user_roles.get(user_id, set())
        return {
            'user_id': user_id,
            'roles': [r.value for r in roles],
            'permissions': [p.value for p in self.get_permissions(user_id)],
            'is_admin': self.is_admin(user_id)
        }

# Instance globale
_rbac: Optional[RBACManager] = None

def get_rbac_manager() -> RBACManager:
    """Get or create global RBAC manager"""
    global _rbac
    if _rbac is None:
        _rbac = RBACManager()
    return _rbac
