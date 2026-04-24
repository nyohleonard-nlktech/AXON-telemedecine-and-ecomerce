from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.utils import timezone
import datetime

from .models import User
from .serializers import UserSerializer
from .permissions import IsAdminUserLegacy

class AuthViewSet(viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=['post'])
    def register(self, request):
        d = request.data
        email = d.get('email', '').strip().lower()
        password = d.get('password', '')
        name = d.get('name', '').strip()
        phone = d.get('phone', '').strip()
        role = d.get('role', 'customer')

        if not all([email, password, name, phone]):
            return Response({'error': 'Name, phone, email and password are required.'}, status=400)
        if len(password) < 8: # Increased from 6 to 8 for better security
            return Response({'error': 'Password must be at least 8 characters.'}, status=400)
        if User.objects.filter(email=email).exists():
            return Response({'error': 'An account with this email already exists.'}, status=400)
        
        user = User(
            username=email,
            email=email,
            first_name=name,
            role=role,
            phone=phone,
        )
        user.set_password(password)

        if role in ('vendor', 'medical'):
            user.biz_name = d.get('biz_name', '').strip()
            user.zone = d.get('zone', '').strip()
            # Vendors and medical personnel can start immediately
            user.status = 'active'
            # Set 40-day grace period
            user.expires_at = timezone.now() + datetime.timedelta(days=40)
            
            # If they uploaded IDs immediately, they still need admin verification for the "tick"
            if 'id_front' in request.FILES and 'id_back' in request.FILES:
                user.is_verified = False # Still needs admin to check and confirm
            
            if role == 'medical':
                user.med_role = d.get('med_role', 'doctor')
        else:
            user.status = 'active'
            user.is_verified = True # Customers/Patients don't need ID verification for a tick

        if role == 'patient':
            user.conditions = d.get('conditions', '').strip()

        # Handle file uploads
        for field in ['profile_pic', 'logo', 'id_front', 'id_back']:
            if field in request.FILES:
                setattr(user, field, request.FILES[field])

        user.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def login(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')
        if not email or not password:
            return Response({'error': 'Email and password required.'}, status=400)

        user = authenticate(username=email, password=password)
        if not user:
            # Fallback for email-based login if username is different
            try:
                u = User.objects.get(email=email)
                user = authenticate(username=u.username, password=password)
            except User.DoesNotExist:
                pass

        if not user:
            return Response({'error': 'Incorrect email or password.'}, status=401)

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user, context={'request': request}).data,
        })

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        return Response(UserSerializer(request.user, context={'request': request}).data)

class AdminUserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUserLegacy]

    @action(detail=False, methods=['get'])
    def pending(self, request):
        pending = self.queryset.filter(status='pending', role__in=['vendor', 'medical'])
        serializer = self.get_serializer(pending, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        user = self.get_object()
        user.status = 'active'
        user.is_verified = True # Admin confirmation grants the "verified tick"
        user.save(update_fields=['status', 'is_verified'])
        return Response({'ok': True, 'user': self.get_serializer(user).data})

    @action(detail=False, methods=['get'])
    def vendors(self, request):
        return Response({
            'vendors': self.get_serializer(self.queryset.filter(role='vendor'), many=True).data,
            'medical': self.get_serializer(self.queryset.filter(role='medical'), many=True).data,
        })

from django.db.models import F, Q
from django.db import transaction
from .models import Product, Order, Chat, Message
from .serializers import ProductSerializer, OrderSerializer
from .permissions import IsVendorOrMedical, IsOwnerOrAdmin

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().select_related('vendor')
    serializer_class = ProductSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsVendorOrMedical()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        qs = super().get_queryset()
        is_med = self.request.query_params.get('medical', 'false').lower() == 'true'
        mine = self.request.query_params.get('mine', 'false').lower() == 'true'
        
        qs = qs.filter(is_medical=is_med)
        if mine and self.request.user.is_authenticated:
            qs = qs.filter(vendor=self.request.user)
        elif mine:
            return qs.none()
        return qs

    def perform_create(self, serializer):
        serializer.save(
            vendor=self.request.user,
            vendor_name=self.request.user.biz_name or self.request.user.first_name
        )

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().select_related('customer')
    serializer_class = OrderSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        if self.action in ['partial_update', 'update', 'release_escrow']:
            return [IsAdminUserLegacy()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        user = self.request.user
        if user.email in getattr(settings, 'ADMIN_EMAILS', []):
            return self.queryset
        return self.queryset.filter(customer=user)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        d = request.data
        items = d.get('items', [])

        if not items:
            return Response({'error': 'Order must contain at least one item.'}, status=400)
        if not d.get('customer_name', '').strip():
            return Response({'error': 'Customer name is required.'}, status=400)

        # Calculate totals
        sub = sum(int(float(i.get('price', 0))) * int(float(i.get('qty', 1))) for i in items)
        com = round(sub * 0.03)
        tot = sub + 800 + com

        gps = d.get('delivery_gps') or {}
        order = Order.objects.create(
            customer=request.user if request.user.is_authenticated else None,
            customer_name=d.get('customer_name', '').strip(),
            phone=d.get('phone', '').strip(),
            address=d.get('address', '').strip(),
            delivery_lat=gps.get('lat'),
            delivery_lng=gps.get('lng'),
            delivery_method=d.get('delivery_method', 'rider'),
            items=items,
            subtotal=sub,
            commission=com,
            total=tot,
        )

        # Atomic stock deduction
        for item in items:
            Product.objects.filter(pk=item.get('id'), stock__gte=item.get('qty', 1)).update(stock=F('stock') - item.get('qty', 1))

        # Create Chat
        booking_id = f'ORD-{order.id}'
        chat = Chat.objects.create(
            booking_id=booking_id,
            customer_name=order.customer_name,
            phone=order.phone,
            chat_type='order',
            address=order.address,
            pickup_lat=order.delivery_lat,
            pickup_lng=order.delivery_lng,
        )

        # System Message
        item_str = ', '.join(f"{i.get('name','?')} x{i.get('qty',1)}" for i in items)
        Message.objects.create(
            chat=chat,
            text=f"AXONFORGE ORDER — {booking_id}\n\nItems: {item_str}\nTotal: {tot:,} XAF\nPayment held in escrow.",
            sender_type='system',
            sender_name='AxonForge'
        )

        return Response({'order': OrderSerializer(order).data, 'chat_id': booking_id}, status=201)

    @action(detail=True, methods=['post'])
    def release_escrow(self, request, pk=None):
        order = self.get_object()
        order.escrow_status = 'released'
        order.status = 'delivered'
        order.save(update_fields=['escrow_status', 'status'])
        return Response({'ok': True, 'order': self.get_serializer(order).data})

from .models import PickDrop, MedConsult, Notification, Prescription
from .serializers import (
    PickDropSerializer, ChatSerializer, MessageSerializer, 
    MedConsultSerializer, NotificationSerializer, PrescriptionSerializer
)
import time

class PickDropViewSet(viewsets.ModelViewSet):
    queryset = PickDrop.objects.all()
    serializer_class = PickDropSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [permissions.IsAuthenticated()]
        if self.action in ['partial_update', 'update', 'approve']:
            return [IsAdminUserLegacy()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        user = self.request.user
        if user.email in getattr(settings, 'ADMIN_EMAILS', []):
            return self.queryset
        return self.queryset.filter(customer=user)

    def create(self, request, *args, **kwargs):
        d = request.data
        # Validation (simplified for brevity, should use Serializer validation)
        required = ['customer_name', 'description', 'pickup_text', 'drop_text']
        if not all(d.get(f, '').strip() for f in required):
            return Response({'error': 'Missing required fields.'}, status=400)

        pgps = d.get('pickup_gps') or {}
        dgps = d.get('drop_gps') or {}

        pd = PickDrop.objects.create(
            customer=request.user if request.user.is_authenticated else None,
            customer_name=d.get('customer_name', '').strip(),
            customer_phone=d.get('customer_phone', '').strip(),
            description=d.get('description', '').strip(),
            estimated_value=int(float(d.get('estimated_value', 0))),
            item_type=d.get('item_type', 'commerce'),
            pickup_text=d.get('pickup_text', '').strip(),
            pickup_lat=pgps.get('lat'),
            pickup_lng=pgps.get('lng'),
            drop_text=d.get('drop_text', '').strip(),
            drop_lat=dgps.get('lat'),
            drop_lng=dgps.get('lng'),
        )

        booking_id = f'PD-{pd.id}'
        chat = Chat.objects.create(
            booking_id=booking_id,
            customer_name=pd.customer_name,
            phone=pd.customer_phone,
            chat_type='pickdrop',
            pickup_text=pd.pickup_text,
            drop_text=pd.drop_text,
        )

        Message.objects.create(
            chat=chat,
            text=f"AXONFORGE PICK & DROP — {booking_id}\nItem: {pd.description}\nUnder security screening.",
            sender_type='system',
            sender_name='AxonForge'
        )

        return Response({'pickdrop': PickDropSerializer(pd).data, 'chat_id': booking_id}, status=201)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        pd = self.get_object()
        pd.security_status = 'approved'
        pd.status = 'dispatching'
        pd.save(update_fields=['security_status', 'status'])
        return Response({'ok': True, 'pickdrop': self.get_serializer(pd).data})

class ChatViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Chat.objects.all().prefetch_related('messages')
    serializer_class = ChatSerializer
    lookup_field = 'booking_id'

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            ids = [i.strip() for i in self.request.query_params.get('ids', '').split(',') if i.strip()]
            return self.queryset.filter(booking_id__in=ids)
        
        if user.email in getattr(settings, 'ADMIN_EMAILS', []):
            return self.queryset
        
        if user.role == 'vendor':
            vendor_name = user.biz_name or user.first_name
            # Optimization: Use filter instead of loop
            return self.queryset.filter(
                Q(booking_id__startswith='ORD-') & Q(booking_id__in=[f"ORD-{o.id}" for o in Order.objects.filter(items__contains=[{'vendor_name': vendor_name}])]) |
                Q(booking_id__in=[f"PD-{p.id}" for p in PickDrop.objects.filter(customer=user)])
            )
        
        if user.role == 'medical':
            return self.queryset.filter(assigned_to=user)
            
        # Customer
        order_ids = Order.objects.filter(customer=user).values_list('id', flat=True)
        pd_ids = PickDrop.objects.filter(customer=user).values_list('id', flat=True)
        chat_ids = [f'ORD-{oid}' for oid in order_ids] + [f'PD-{pid}' for pid in pd_ids]
        return self.queryset.filter(booking_id__in=chat_ids)

    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, booking_id=None):
        chat = self.get_object()
        if request.method == 'GET':
            after = request.query_params.get('after')
            qs = chat.messages.all()
            if after:
                qs = qs.filter(id__gt=after)
            return Response(MessageSerializer(qs, many=True).data)
        
        # POST
        text = request.data.get('text', '').strip()
        if not text:
            return Response({'error': 'Message text is required.'}, status=400)

        sender_type, sender_name = 'customer', request.data.get('sender_name', 'Customer')
        if request.user.is_authenticated:
            if request.user.email in getattr(settings, 'ADMIN_EMAILS', []):
                sender_type, sender_name = 'admin', 'AxonForge Team'
            else:
                sender_type = request.user.role
                sender_name = request.user.biz_name or request.user.first_name or 'User'

        msg = Message.objects.create(
            chat=chat, text=text,
            sender_type=sender_type, sender_name=sender_name,
        )
        return Response(MessageSerializer(msg).data, status=201)

class MedConsultViewSet(viewsets.ModelViewSet):
    queryset = MedConsult.objects.all()
    serializer_class = MedConsultSerializer

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def start(self, request):
        d = request.data
        patient_name = d.get('patient_name', '').strip()
        consult_type = d.get('consult_type', 'doctor')
        symptoms = d.get('symptoms', '').strip()

        if not patient_name or not symptoms:
            return Response({'error': 'Patient name and symptoms are required.'}, status=400)

        available = User.objects.filter(role='medical', med_role=consult_type, status='active').first()
        booking_id = f'MED-{int(time.time() * 1000)}'

        chat = Chat.objects.create(
            booking_id=booking_id,
            customer_name=patient_name,
            chat_type='medical_consult',
            consult_type=consult_type,
            assigned_to=available,
        )

        consult = MedConsult.objects.create(
            booking_id=booking_id,
            patient_name=patient_name,
            patient_age=d.get('patient_age'),
            patient_weight=d.get('patient_weight'),
            allergies=d.get('allergies', '').strip(),
            current_meds=d.get('current_meds', '').strip(),
            consult_type=consult_type,
            symptoms=symptoms,
            status='active' if available else 'queued',
            assigned_to=available,
            chat=chat,
        )

        if available:
            Notification.objects.create(
                to_user=available, notif_type='new_consult',
                chat_id=booking_id, patient_name=patient_name,
                consult_type=consult_type, symptoms=symptoms,
            )

        return Response({
            'consult': MedConsultSerializer(consult).data,
            'chat_id': booking_id,
            'assigned': bool(available)
        }, status=201)

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def mine(self, request):
        user = request.user
        if user.role != 'medical' and user.email not in getattr(settings, 'ADMIN_EMAILS', []):
            return Response({'error': 'Medical personnel only.'}, status=403)
        assigned = self.queryset.filter(assigned_to=user, status='active')
        queued = self.queryset.filter(status='queued', consult_type=user.med_role)
        return Response({
            'assigned': MedConsultSerializer(assigned, many=True).data,
            'queued': MedConsultSerializer(queued, many=True).data,
        })

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def self_assign(self, request, pk=None):
        consult = self.get_object()
        if consult.status != 'queued':
            return Response({'error': 'Consultation is not queued.'}, status=400)
        consult.assigned_to = request.user
        consult.status = 'active'
        consult.save()
        return Response(MedConsultSerializer(consult).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def add_prescription(self, request, pk=None):
        consult = self.get_object()
        if request.user.role != 'medical' or consult.assigned_to != request.user:
            return Response({'error': 'Only the assigned medical professional can prescribe.'}, status=403)
        
        serializer = PrescriptionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(consult=consult, doctor=request.user)
            
            # Send a system message to the chat about the new prescription
            if consult.chat:
                Message.objects.create(
                    chat=consult.chat,
                    text=f"NEW PRESCRIPTION ISSUED: {request.data.get('medication')}. Please check your consultation details.",
                    sender_type='system',
                    sender_name='AxonForge Medical'
                )
            
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class PrescriptionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Prescription.objects.all()
    serializer_class = PrescriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.email in getattr(settings, 'ADMIN_EMAILS', []):
            return self.queryset
        if user.role == 'medical':
            return self.queryset.filter(doctor=user)
        # Patients can see prescriptions linked to their consults
        return self.queryset.filter(consult__chat__booking_id__in=[f"MED-{c.id}" for c in MedConsult.objects.filter(patient_name=user.first_name)]) # Simplified check

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(to_user=self.request.user, read=False)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        data = self.get_serializer(qs, many=True).data
        qs.update(read=True)
        return Response(data)
