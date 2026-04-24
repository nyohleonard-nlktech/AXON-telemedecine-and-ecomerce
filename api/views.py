import time
import datetime
from django.conf import settings
from django.contrib.auth import authenticate
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import User, Product, Order, PickDrop, Chat, Message, MedConsult, Notification
from .serializers import (UserSerializer, ProductSerializer, OrderSerializer,
                           PickDropSerializer, ChatSerializer, MessageSerializer,
                           MedConsultSerializer, NotificationSerializer)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_admin(user):
    return user.is_authenticated and user.email in getattr(settings, 'ADMIN_EMAILS', [])


def safe_int(value, default=0):
    """Convert to int safely — prevents crashes from empty strings or None."""
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return default


def safe_float(value):
    """Convert to float safely — used for GPS coordinates."""
    try:
        return float(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def sys_msg(chat, text):
    Message.objects.create(
        chat=chat, text=text,
        sender_type='system', sender_name='AxonForge'
    )


def make_chat(booking_id, customer_name, phone, chat_type, **kwargs):
    return Chat.objects.create(
        booking_id=booking_id,
        customer_name=customer_name,
        phone=phone,
        chat_type=chat_type,
        **kwargs
    )


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def register(request):
    d        = request.data
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')
    name     = d.get('name', '').strip()
    phone    = d.get('phone', '').strip()
    role     = d.get('role', 'customer')

    if not all([email, password, name, phone]):
        return Response({'error': 'Name, phone, email and password are required.'}, status=400)
    if len(password) < 6:
        return Response({'error': 'Password must be at least 6 characters.'}, status=400)
    if User.objects.filter(email=email).exists():
        return Response({'error': 'An account with this email already exists.'}, status=400)
    if role not in ('customer', 'vendor', 'medical', 'patient'):
        return Response({'error': 'Invalid role.'}, status=400)

    user = User(
        username   = email,
        email      = email,
        first_name = name,
        role       = role,
        phone      = phone,
    )
    user.set_password(password)

    if role in ('vendor', 'medical'):
        user.biz_name   = d.get('biz_name', '').strip()
        user.zone       = d.get('zone', '').strip()
        user.status     = 'pending'
        user.expires_at = timezone.now() + datetime.timedelta(days=40)
        if role == 'medical':
            user.med_role = d.get('med_role', 'doctor')
    else:
        user.status = 'active'

    if role == 'patient':
        user.conditions = d.get('conditions', '').strip()

    # Attach files before single save
    if 'profile_pic' in request.FILES:
        user.profile_pic = request.FILES['profile_pic']
    if 'logo' in request.FILES:
        user.logo = request.FILES['logo']
    if 'id_front' in request.FILES:
        user.id_front = request.FILES['id_front']
    if 'id_back' in request.FILES:
        user.id_back = request.FILES['id_back']

    user.save()

    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token.key,
        'user':  UserSerializer(user, context={'request': request}).data,
    }, status=201)


@api_view(['POST'])
def login(request):
    email    = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '')
    if not email or not password:
        return Response({'error': 'Email and password required.'}, status=400)

    user = authenticate(username=email, password=password)
    if not user:
        try:
            u    = User.objects.get(email=email)
            user = authenticate(username=u.username, password=password)
        except User.DoesNotExist:
            pass

    if not user:
        return Response({'error': 'Incorrect email or password.'}, status=401)

    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token.key,
        'user':  UserSerializer(user, context={'request': request}).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializer(request.user, context={'request': request}).data)


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def products(request):
    is_med = request.query_params.get('medical', 'false').lower() == 'true'
    mine   = request.query_params.get('mine',    'false').lower() == 'true'

    if request.method == 'GET':
        # FIX: unauthenticated + mine=true returns empty, not all products
        if mine and not request.user.is_authenticated:
            return Response([])
        qs = Product.objects.filter(is_medical=is_med).select_related('vendor')
        if mine and request.user.is_authenticated:
            qs = qs.filter(vendor=request.user)
        return Response(ProductSerializer(qs, many=True, context={'request': request}).data)

    # POST
    if not request.user.is_authenticated:
        return Response({'error': 'Login required to list products.'}, status=401)
    if request.user.role not in ('vendor', 'medical') and not is_admin(request.user):
        return Response({'error': 'Only vendors or medical personnel can list products.'}, status=403)
    if request.user.status == 'pending':
        return Response({'error': 'Your account is pending admin confirmation.'}, status=403)

    d     = request.data
    price = safe_int(d.get('price', 0))
    stock = safe_int(d.get('stock', 1))

    if not d.get('name', '').strip():
        return Response({'error': 'Product name is required.'}, status=400)
    if price <= 0:
        return Response({'error': 'Price must be greater than 0.'}, status=400)
    if stock <= 0:
        return Response({'error': 'Stock must be at least 1.'}, status=400)

    prod = Product(
        vendor      = request.user,
        vendor_name = request.user.biz_name or request.user.first_name,
        name        = d.get('name', '').strip(),
        desc        = d.get('desc', '').strip(),
        category    = d.get('category', 'Other'),
        price       = price,
        stock       = stock,
        emoji       = d.get('emoji', '📦'),
        is_medical  = is_med,
    )
    if 'image' in request.FILES:
        prod.image = request.FILES['image']
    prod.save()
    return Response(ProductSerializer(prod, context={'request': request}).data, status=201)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def product_detail(request, pk):
    try:
        prod = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found.'}, status=404)
    if prod.vendor != request.user and not is_admin(request.user):
        return Response({'error': 'Not authorised.'}, status=403)
    prod.delete()
    return Response({'ok': True})


# ─────────────────────────────────────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def orders(request):
    if request.method == 'POST':
        d     = request.data
        items = d.get('items', [])

        if not items:
            return Response({'error': 'Order must contain at least one item.'}, status=400)
        if not d.get('customer_name', '').strip():
            return Response({'error': 'Customer name is required.'}, status=400)

        sub = sum(safe_int(i.get('price', 0)) * safe_int(i.get('qty', 1)) for i in items)
        com = round(sub * 0.03)
        tot = sub + 800 + com

        gps   = d.get('delivery_gps') or {}
        order = Order.objects.create(
            customer        = request.user if request.user.is_authenticated else None,
            customer_name   = d.get('customer_name', '').strip(),
            phone           = d.get('phone', '').strip(),
            address         = d.get('address', '').strip(),
            delivery_lat    = safe_float(gps.get('lat')),
            delivery_lng    = safe_float(gps.get('lng')),
            delivery_method = d.get('delivery_method', 'rider'),
            items           = items,
            subtotal        = sub,
            commission      = com,
            total           = tot,
        )

        # FIX: decrement product stock on order
        for item in items:
            try:
                prod = Product.objects.get(pk=safe_int(item.get('id')))
                qty  = safe_int(item.get('qty', 1))
                if prod.stock >= qty:
                    prod.stock -= qty
                    prod.save(update_fields=['stock'])
            except Product.DoesNotExist:
                pass

        chat = make_chat(
            booking_id    = f'ORD-{order.id}',
            customer_name = order.customer_name,
            phone         = order.phone,
            chat_type     = 'order',
            address       = order.address,
            pickup_lat    = safe_float(gps.get('lat')),
            pickup_lng    = safe_float(gps.get('lng')),
        )

        item_str = ', '.join(f"{i.get('name','?')} x{safe_int(i.get('qty',1))}" for i in items)
        gps_str  = f" (GPS: {gps.get('lat')}, {gps.get('lng')})" if gps.get('lat') else ''

        sys_msg(chat,
            f"AXONFORGE ORDER — ORD-{order.id}\n\n"
            f"Customer : {order.customer_name} | {order.phone}\n"
            f"Address  : {order.address}{gps_str}\n"
            f"Items    : {item_str}\n"
            f"Subtotal : {sub:,} XAF | Commission: {com:,} XAF | Total: {tot:,} XAF\n\n"
            f"Payment held in escrow. Released only after delivery confirmed."
        )

        return Response({'order': OrderSerializer(order).data, 'chat_id': chat.booking_id}, status=201)

    if request.user.is_authenticated and is_admin(request.user):
        qs = Order.objects.all()
    elif request.user.is_authenticated:
        qs = Order.objects.filter(customer=request.user)
    else:
        return Response([])
    return Response(OrderSerializer(qs, many=True).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def order_detail(request, pk):
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found.'}, status=404)
    if 'escrow_status' in request.data:
        if not is_admin(request.user):
            return Response({'error': 'Admin only.'}, status=403)
        order.escrow_status = request.data['escrow_status']
        order.status        = 'delivered'
    if 'status' in request.data:
        order.status = request.data['status']
    order.save()
    return Response(OrderSerializer(order).data)


# ─────────────────────────────────────────────────────────────────────────────
# PICK & DROP
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def pickdrops(request):
    if request.method == 'POST':
        d = request.data
        if not d.get('customer_name', '').strip():
            return Response({'error': 'Your name is required.'}, status=400)
        if not d.get('description', '').strip():
            return Response({'error': 'Item description is required.'}, status=400)
        if not d.get('pickup_text', '').strip():
            return Response({'error': 'Pickup location is required.'}, status=400)
        if not d.get('drop_text', '').strip():
            return Response({'error': 'Drop-off location is required.'}, status=400)

        pgps = d.get('pickup_gps') or {}
        dgps = d.get('drop_gps')   or {}

        pd = PickDrop.objects.create(
            customer             = request.user if request.user.is_authenticated else None,
            customer_name        = d.get('customer_name', '').strip(),
            customer_phone       = d.get('customer_phone', '').strip(),
            description          = d.get('description', '').strip(),
            estimated_value      = safe_int(d.get('estimated_value', 0)),
            item_type            = d.get('item_type', 'commerce'),
            pickup_text          = d.get('pickup_text', '').strip(),
            pickup_lat           = safe_float(pgps.get('lat')),
            pickup_lng           = safe_float(pgps.get('lng')),
            pickup_contact_name  = d.get('pickup_contact_name', '').strip(),
            pickup_contact_phone = d.get('pickup_contact_phone', '').strip(),
            drop_text            = d.get('drop_text', '').strip(),
            drop_lat             = safe_float(dgps.get('lat')),
            drop_lng             = safe_float(dgps.get('lng')),
            drop_contact_name    = d.get('drop_contact_name', '').strip(),
            drop_contact_phone   = d.get('drop_contact_phone', '').strip(),
        )

        chat = make_chat(
            booking_id    = f'PD-{pd.id}',
            customer_name = pd.customer_name,
            phone         = pd.customer_phone,
            chat_type     = 'pickdrop',
            pickup_text   = pd.pickup_text,
            drop_text     = pd.drop_text,
            pickup_lat    = pd.pickup_lat,
            pickup_lng    = pd.pickup_lng,
            drop_lat      = pd.drop_lat,
            drop_lng      = pd.drop_lng,
        )

        pg = f" (GPS: {pd.pickup_lat}, {pd.pickup_lng})" if pd.pickup_lat else ''
        dg = f" (GPS: {pd.drop_lat},  {pd.drop_lng})"   if pd.drop_lat   else ''

        sys_msg(chat,
            f"AXONFORGE PICK & DROP — PD-{pd.id}\n\n"
            f"Sender   : {pd.customer_name} | {pd.customer_phone}\n"
            f"Item     : {pd.description}\n"
            f"Type     : {pd.item_type} | Value: {pd.estimated_value:,} XAF\n"
            f"Pickup   : {pd.pickup_text}{pg}\n"
            f"Drop-off : {pd.drop_text}{dg}\n"
            f"Pickup contact  : {pd.pickup_contact_name} | {pd.pickup_contact_phone}\n"
            f"Receiver        : {pd.drop_contact_name} | {pd.drop_contact_phone}\n\n"
            f"Under security screening. Team will confirm shortly."
        )

        return Response({'pickdrop': PickDropSerializer(pd).data, 'chat_id': chat.booking_id}, status=201)

    if request.user.is_authenticated and is_admin(request.user):
        qs = PickDrop.objects.all()
    elif request.user.is_authenticated:
        qs = PickDrop.objects.filter(customer=request.user)
    else:
        return Response([])
    return Response(PickDropSerializer(qs, many=True).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def pickdrop_detail(request, pk):
    try:
        pd = PickDrop.objects.get(pk=pk)
    except PickDrop.DoesNotExist:
        return Response({'error': 'Not found.'}, status=404)
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    pd.security_status = request.data.get('security_status', pd.security_status)
    pd.status          = request.data.get('status', pd.status)
    pd.save()
    return Response(PickDropSerializer(pd).data)


# ─────────────────────────────────────────────────────────────────────────────
# CHATS & MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def chats(request):
    if request.user.is_authenticated and is_admin(request.user):
        qs = Chat.objects.all()

    elif request.user.is_authenticated and request.user.role == 'vendor':
        # FIX: vendors see order chats for orders containing their products
        vendor_name = request.user.biz_name or request.user.first_name
        chat_ids    = []
        for order in Order.objects.all():
            for item in (order.items or []):
                if item.get('vendor_name', '') == vendor_name:
                    chat_ids.append(f'ORD-{order.id}')
                    break
        # Also their pick-drop chats
        for pid in PickDrop.objects.filter(customer=request.user).values_list('id', flat=True):
            chat_ids.append(f'PD-{pid}')
        qs = Chat.objects.filter(booking_id__in=chat_ids)

    elif request.user.is_authenticated and request.user.role == 'medical':
        qs = Chat.objects.filter(assigned_to=request.user)

    elif request.user.is_authenticated:
        # Customer — order chats + pick-drop chats
        order_ids = Order.objects.filter(customer=request.user).values_list('id', flat=True)
        pd_ids    = PickDrop.objects.filter(customer=request.user).values_list('id', flat=True)
        chat_ids  = [f'ORD-{oid}' for oid in order_ids] + [f'PD-{pid}' for pid in pd_ids]
        qs = Chat.objects.filter(booking_id__in=chat_ids)

    else:
        ids = [i.strip() for i in request.query_params.get('ids', '').split(',') if i.strip()]
        qs  = Chat.objects.filter(booking_id__in=ids)

    return Response(ChatSerializer(qs, many=True).data)


@api_view(['GET'])
def chat_by_booking(request, booking_id):
    try:
        chat = Chat.objects.get(booking_id=booking_id)
    except Chat.DoesNotExist:
        return Response({'error': 'Chat not found.'}, status=404)
    return Response(ChatSerializer(chat).data)


@api_view(['GET', 'POST'])
def messages(request, booking_id):
    try:
        chat = Chat.objects.get(booking_id=booking_id)
    except Chat.DoesNotExist:
        return Response({'error': 'Chat not found.'}, status=404)

    if request.method == 'GET':
        after    = request.query_params.get('after')
        qs       = chat.messages.all()
        after_id = safe_int(after, default=0)
        if after_id > 0:
            qs = qs.filter(id__gt=after_id)
        return Response(MessageSerializer(qs, many=True).data)

    # POST
    text = request.data.get('text', '').strip()
    if not text:
        return Response({'error': 'Message text is required.'}, status=400)

    if request.user.is_authenticated:
        if is_admin(request.user):
            sender_type, sender_name = 'admin', 'AxonForge Team'
        elif request.user.role == 'vendor':
            sender_type = 'vendor'
            sender_name = request.user.biz_name or request.user.first_name
        elif request.user.role == 'medical':
            sender_type = 'medical'
            sender_name = request.user.first_name
        else:
            sender_type = 'customer'
            sender_name = request.user.first_name or 'Customer'
    else:
        sender_type = 'customer'
        sender_name = request.data.get('sender_name', 'Customer')

    msg = Message.objects.create(
        chat=chat, text=text,
        sender_type=sender_type, sender_name=sender_name,
    )
    return Response(MessageSerializer(msg).data, status=201)


# ─────────────────────────────────────────────────────────────────────────────
# MEDICAL CONSULTATIONS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def start_consult(request):
    d            = request.data
    patient_name = d.get('patient_name', '').strip()
    consult_type = d.get('consult_type', 'doctor')
    symptoms     = d.get('symptoms', '').strip()

    if not patient_name:
        return Response({'error': 'Patient name is required.'}, status=400)
    if not symptoms:
        return Response({'error': 'Please describe your symptoms.'}, status=400)
    if consult_type not in ('doctor', 'nurse', 'pharmacist'):
        return Response({'error': 'Invalid consultation type.'}, status=400)

    available  = User.objects.filter(role='medical', med_role=consult_type, status='active').first()
    booking_id = f'MED-{int(time.time() * 1000)}'

    chat = make_chat(
        booking_id    = booking_id,
        customer_name = patient_name,
        phone         = '',
        chat_type     = 'medical_consult',
        consult_type  = consult_type,
        assigned_to   = available,
    )

    consult = MedConsult.objects.create(
        booking_id   = booking_id,
        patient_name = patient_name,
        consult_type = consult_type,
        symptoms     = symptoms,
        status       = 'active' if available else 'queued',
        assigned_to  = available,
        chat         = chat,
    )

    if available:
        sys_msg(chat,
            f"AXONFORGE MEDICAL CONSULTATION\n"
            f"Patient     : {patient_name}\n"
            f"Type        : {consult_type.upper()}\n"
            f"Assigned to : {available.first_name}"
            f"{' (' + available.biz_name + ')' if available.biz_name else ''}\n\n"
            f"Symptoms: {symptoms}\n\n"
            f"A licensed {consult_type} has been assigned. They will respond shortly."
        )
        Notification.objects.create(
            to_user=available, notif_type='new_consult',
            chat_id=booking_id, patient_name=patient_name,
            consult_type=consult_type, symptoms=symptoms,
        )
    else:
        sys_msg(chat,
            f"CONSULTATION REQUEST RECEIVED\n"
            f"Patient  : {patient_name}\n"
            f"Type     : {consult_type.upper()}\n"
            f"Symptoms : {symptoms}\n\n"
            f"No {consult_type} is currently available. Your request has been queued. "
            f"An AxonForge coordinator will assign a {consult_type} shortly."
        )

    return Response({
        'consult':       MedConsultSerializer(consult).data,
        'chat_id':       booking_id,
        'assigned':      bool(available),
        'assigned_name': available.first_name if available else None,
    }, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_consults(request):
    user = request.user
    if user.role != 'medical' and not is_admin(user):
        return Response({'error': 'Medical personnel only.'}, status=403)
    assigned = MedConsult.objects.filter(assigned_to=user, status='active').select_related('chat')
    queued   = MedConsult.objects.filter(status='queued', consult_type=user.med_role)
    return Response({
        'assigned': MedConsultSerializer(assigned, many=True).data,
        'queued':   MedConsultSerializer(queued,   many=True).data,
    })


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def consult_detail(request, pk):
    try:
        consult = MedConsult.objects.get(pk=pk)
    except MedConsult.DoesNotExist:
        return Response({'error': 'Not found.'}, status=404)

    action = request.data.get('action')

    if action == 'self_assign':
        if consult.status != 'queued':
            return Response({'error': 'Consultation is not queued.'}, status=400)
        consult.assigned_to = request.user
        consult.status      = 'active'
        consult.save()
        if consult.chat:
            sys_msg(consult.chat,
                f"{request.user.first_name} ({request.user.med_role or 'Medical Personnel'}) "
                f"has accepted your consultation. You can now type your questions."
            )
        return Response(MedConsultSerializer(consult).data)

    if action == 'close':
        consult.status = 'closed'
        consult.save()
        return Response(MedConsultSerializer(consult).data)

    return Response({'error': 'Unknown action. Use: self_assign or close.'}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notifications(request):
    notifs = Notification.objects.filter(to_user=request.user, read=False)
    data   = NotificationSerializer(notifs, many=True).data
    notifs.update(read=True)
    return Response(data)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_stats(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    return Response({
        'vendors':   User.objects.filter(role__in=['vendor', 'medical']).count(),
        'products':  Product.objects.count(),
        'orders':    Order.objects.count(),
        'pickdrops': PickDrop.objects.count(),
        'pending':   User.objects.filter(status='pending').count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_pending(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    pending = User.objects.filter(status='pending', role__in=['vendor', 'medical'])
    return Response(UserSerializer(pending, many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_confirm_user(request, pk):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)
    user.status = 'active'
    user.save(update_fields=['status'])
    return Response({'ok': True, 'user': UserSerializer(user, context={'request': request}).data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_reject_user(request, pk):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    try:
        User.objects.get(pk=pk).delete()
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_all_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    return Response(OrderSerializer(Order.objects.all(), many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_release_escrow(request, pk):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found.'}, status=404)
    order.escrow_status = 'released'
    order.status        = 'delivered'
    order.save(update_fields=['escrow_status', 'status'])
    return Response({'ok': True, 'order': OrderSerializer(order).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_all_pickdrops(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    return Response(PickDropSerializer(PickDrop.objects.all(), many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_approve_pickdrop(request, pk):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    try:
        pd = PickDrop.objects.get(pk=pk)
    except PickDrop.DoesNotExist:
        return Response({'error': 'Not found.'}, status=404)
    pd.security_status = 'approved'
    pd.status          = 'dispatching'
    pd.save(update_fields=['security_status', 'status'])
    return Response({'ok': True, 'pickdrop': PickDropSerializer(pd).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_all_vendors(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    return Response({
        'vendors': UserSerializer(User.objects.filter(role='vendor'),  many=True, context={'request': request}).data,
        'medical': UserSerializer(User.objects.filter(role='medical'), many=True, context={'request': request}).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_all_products(request):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    return Response(
        ProductSerializer(Product.objects.all().select_related('vendor'), many=True, context={'request': request}).data
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def admin_delete_product(request, pk):
    if not is_admin(request.user):
        return Response({'error': 'Admin only.'}, status=403)
    try:
        Product.objects.get(pk=pk).delete()
    except Product.DoesNotExist:
        return Response({'error': 'Product not found.'}, status=404)
    return Response({'ok': True})
