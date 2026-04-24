from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .viewsets import (
    AuthViewSet, AdminUserViewSet, ProductViewSet, 
    OrderViewSet, PickDropViewSet, ChatViewSet, 
    MedConsultViewSet, NotificationViewSet, PrescriptionViewSet
)

router = DefaultRouter()
router.register(r'auth', AuthViewSet, basename='auth')
router.register(r'admin/users', AdminUserViewSet, basename='admin-users')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'pickdrops', PickDropViewSet, basename='pickdrops')
router.register(r'chats', ChatViewSet, basename='chats')
router.register(r'med-consults', MedConsultViewSet, basename='med-consults')
router.register(r'notifications', NotificationViewSet, basename='notifications')
router.register(r'prescriptions', PrescriptionViewSet, basename='prescriptions')

urlpatterns = [
    path('', include(router.urls)),
]
