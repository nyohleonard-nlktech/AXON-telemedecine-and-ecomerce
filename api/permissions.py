from rest_framework import permissions
from django.conf import settings
from django.utils import timezone

class IsAdminUserLegacy(permissions.BasePermission):
    """
    Allows access only to users whose email is in the ADMIN_EMAILS list.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.email in getattr(settings, 'ADMIN_EMAILS', [])
        )

class IsVendorOrMedical(permissions.BasePermission):
    """
    Allows access to vendors or medical personnel if they are active and not expired.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
            
        if request.user.role not in ('vendor', 'medical'):
            return False
            
        # Check if account is active
        if request.user.status != 'active':
            return False
            
        # Check if grace period has expired (only if not verified)
        if not request.user.is_verified and request.user.expires_at:
            if timezone.now() > request.user.expires_at:
                return False
                
        return True

class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or admins to edit/delete it.
    """
    def has_object_permission(self, request, view, obj):
        # Admin check
        if request.user.email in getattr(settings, 'ADMIN_EMAILS', []):
            return True
        
        # Ownership check
        if hasattr(obj, 'vendor'):
            return obj.vendor == request.user
        if hasattr(obj, 'customer'):
            return obj.customer == request.user
        if hasattr(obj, 'user'):
            return obj.user == request.user
            
        return False
